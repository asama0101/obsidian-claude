"""clip_save.py のユニットテスト。

標準ライブラリの unittest のみを使用する。ネットワークアクセスは行わず、
urllib.request.urlopen をモックして検証する。
"""

import datetime
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

# scripts/ ディレクトリを import パスに追加する
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import clip_save  # noqa: E402
import vault_lib  # noqa: E402


# 実際のWebClip_Template.mdと同一構造のフィクスチャ(CRLFは読込時にLFへ正規化される想定)
TEMPLATE_TEXT = (
    '---\n'
    'type: webclip\n'
    'url: ""\n'
    'date: "{{date:YYYY-MM-DD}}"\n'
    'tags:\n'
    '  - webclip\n'
    '---\n'
    '# {{title}}\n'
    '\n'
    '## \U0001f4cc 概要・要約\n'
    '- \n'
    '\n'
    '## \U0001f4a1 キーポイント\n'
    '- \n'
    '\n'
    '## \U0001f4dd 自分のメモ・考察\n'
    '- \n'
    '\n'
    '---\n'
    '## \U0001f4c4 クリップ本文\n'
    '>\n'
)


class TestClipSave(unittest.TestCase):
    def _make_vault(self, tmp):
        vault_root = Path(tmp)
        (vault_root / "70_Templates").mkdir(parents=True)
        (vault_root / "70_Templates" / "WebClip_Template.md").write_text(
            TEMPLATE_TEXT, encoding="utf-8"
        )
        (vault_root / "80_Attachments").mkdir()
        (vault_root / "30_Resources" / "WebClips").mkdir(parents=True)
        (vault_root / "10_Projects").mkdir()
        return vault_root

    def _make_content_json(self, tmp, content):
        path = Path(tmp) / "content.json"
        path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        return path

    def _mock_response(self, data: bytes, content_type: str):
        response = MagicMock()
        response.read.return_value = data
        response.headers.get_content_type.return_value = content_type
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response

    def _mock_urlopen_by_url(self, responses: dict):
        """URLごとに異なるレスポンスを返すside_effect関数を作る。"""

        def _side_effect(url, timeout=10.0):
            return responses[url]

        return _side_effect

    def _run_main(self, argv):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = clip_save.main(argv)
        self.assertEqual(exit_code, 0)
        return json.loads(stdout.getvalue())

    def test_summaryとkey_pointsの項目に紐づく画像がその直下に埋め込まれる(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            content_path = self._make_content_json(
                tmp,
                {
                    "title": "テスト記事",
                    "summary": [
                        {"text": "要約1", "image_url": "https://example.com/s1.png"},
                        {"text": "要約2"},
                    ],
                    "key_points": [
                        {"text": "ポイント1", "image_url": "https://example.com/k1.jpg"},
                    ],
                    "full_text": "本文全文です",
                },
            )
            responses = {
                "https://example.com/s1.png": self._mock_response(b"s1data", "image/png"),
                "https://example.com/k1.jpg": self._mock_response(b"k1data", "image/jpeg"),
            }
            with patch(
                "clip_save.urllib.request.urlopen",
                side_effect=self._mock_urlopen_by_url(responses),
            ):
                result = self._run_main(
                    [
                        "--url",
                        "https://example.com/article",
                        "--content-json",
                        str(content_path),
                        "--vault-root",
                        str(vault_root),
                        "--tag",
                        "python/pandas",
                    ]
                )

            self.assertEqual(len(result["images_saved"]), 2)
            self.assertEqual(result["images_failed"], [])

            note_path = Path(result["note_path"])
            note_text = note_path.read_text(encoding="utf-8")

            s1_filename = next(f for f in result["images_saved"] if f.endswith(".png"))
            k1_filename = next(f for f in result["images_saved"] if f.endswith(".jpg"))

            self.assertIn(
                f"- 要約1\n  ![[80_Attachments/{s1_filename}]]\n- 要約2", note_text
            )
            self.assertIn(
                f"- ポイント1\n  ![[80_Attachments/{k1_filename}]]", note_text
            )
            self.assertIn("> 本文全文です", note_text)

    def test_image_urlを持たない項目には画像が埋め込まれない(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            content_path = self._make_content_json(
                tmp,
                {
                    "title": "画像なし記事",
                    "summary": [{"text": "要約のみ"}],
                    "key_points": [{"text": "ポイントのみ", "image_url": ""}],
                    "full_text": "本文",
                },
            )
            with patch("clip_save.urllib.request.urlopen") as mock_urlopen:
                result = self._run_main(
                    [
                        "--url",
                        "https://example.com/noimage",
                        "--content-json",
                        str(content_path),
                        "--vault-root",
                        str(vault_root),
                        "--tag",
                        "python/pandas",
                    ]
                )
                mock_urlopen.assert_not_called()

            self.assertEqual(result["images_saved"], [])
            self.assertEqual(result["images_failed"], [])

            note_text = Path(result["note_path"]).read_text(encoding="utf-8")
            self.assertNotIn("![[80_Attachments/", note_text)

    def test_同じimage_urlが複数項目で参照される場合はダウンロードが1回だけになる(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            content_path = self._make_content_json(
                tmp,
                {
                    "title": "共有画像記事",
                    "summary": [
                        {"text": "要約A", "image_url": "https://example.com/shared.png"}
                    ],
                    "key_points": [
                        {"text": "ポイントB", "image_url": "https://example.com/shared.png"}
                    ],
                    "full_text": "本文",
                },
            )
            mock_response = self._mock_response(b"shareddata", "image/png")
            with patch(
                "clip_save.urllib.request.urlopen", return_value=mock_response
            ) as mock_urlopen:
                result = self._run_main(
                    [
                        "--url",
                        "https://example.com/shared-article",
                        "--content-json",
                        str(content_path),
                        "--vault-root",
                        str(vault_root),
                        "--tag",
                        "python/pandas",
                    ]
                )
                self.assertEqual(mock_urlopen.call_count, 1)

            self.assertEqual(len(result["images_saved"]), 1)
            shared_filename = result["images_saved"][0]

            note_text = Path(result["note_path"]).read_text(encoding="utf-8")
            self.assertIn(f"- 要約A\n  ![[80_Attachments/{shared_filename}]]", note_text)
            self.assertIn(f"- ポイントB\n  ![[80_Attachments/{shared_filename}]]", note_text)

    def test_full_textが加工されず全文そのまま引用形式で本文に入る(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            long_text = "あ" * 5000
            content_path = self._make_content_json(
                tmp,
                {
                    "title": "長文記事",
                    "summary": [],
                    "key_points": [],
                    "full_text": long_text,
                },
            )
            result = self._run_main(
                [
                    "--url",
                    "https://example.com/long",
                    "--content-json",
                    str(content_path),
                    "--vault-root",
                    str(vault_root),
                    "--tag",
                    "python/pandas",
                ]
            )
            note_text = Path(result["note_path"]).read_text(encoding="utf-8")
            self.assertIn(f"> {long_text}", note_text)

    def test_画像ダウンロード失敗時はスキップされノート作成は続行される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            content_path = self._make_content_json(
                tmp,
                {
                    "title": "失敗テスト記事",
                    "summary": [
                        {"text": "要約", "image_url": "https://example.com/broken.jpg"}
                    ],
                    "key_points": [{"text": "ポイント"}],
                    "full_text": "本文",
                },
            )
            with patch(
                "clip_save.urllib.request.urlopen", side_effect=OSError("network error")
            ):
                result = self._run_main(
                    [
                        "--url",
                        "https://example.com/broken-article",
                        "--content-json",
                        str(content_path),
                        "--vault-root",
                        str(vault_root),
                        "--tag",
                        "python/pandas",
                    ]
                )

            self.assertEqual(result["images_saved"], [])
            self.assertEqual(result["images_failed"], ["https://example.com/broken.jpg"])

            note_path = Path(result["note_path"])
            self.assertTrue(note_path.exists())
            self.assertEqual(len(list((vault_root / "80_Attachments").iterdir())), 0)

            note_text = note_path.read_text(encoding="utf-8")
            self.assertIn("- 要約", note_text)
            self.assertNotIn("![[80_Attachments/", note_text)

    def test_frontmatterのurlとdateが正しく設定される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            content_path = self._make_content_json(
                tmp,
                {
                    "title": "日付テスト記事",
                    "summary": [],
                    "key_points": [],
                    "full_text": "",
                },
            )
            result = self._run_main(
                [
                    "--url",
                    "https://example.com/dated",
                    "--content-json",
                    str(content_path),
                    "--vault-root",
                    str(vault_root),
                    "--tag",
                    "python/pandas",
                ]
            )
            note_text = Path(result["note_path"]).read_text(encoding="utf-8")
            fm, _ = vault_lib.split_frontmatter(note_text)
            self.assertEqual(vault_lib.get_fm_value(fm, "url"), "https://example.com/dated")
            today = datetime.date.today().strftime("%Y-%m-%d")
            self.assertEqual(vault_lib.get_fm_value(fm, "date"), today)

    def test_full_text内の画像記法が抽出されダウンロードされblockquote内でローカル埋め込みに置換される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            content_path = self._make_content_json(
                tmp,
                {
                    "title": "本文画像記事",
                    "summary": [],
                    "key_points": [],
                    "full_text": (
                        "冒頭のテキスト\n\n"
                        "![説明](https://example.com/body1.png)\n\n"
                        "続きのテキスト"
                    ),
                },
            )
            mock_response = self._mock_response(b"body1data", "image/png")
            with patch(
                "clip_save.urllib.request.urlopen", return_value=mock_response
            ) as mock_urlopen:
                result = self._run_main(
                    [
                        "--url",
                        "https://example.com/body-article",
                        "--content-json",
                        str(content_path),
                        "--vault-root",
                        str(vault_root),
                        "--tag",
                        "python/pandas",
                    ]
                )
                self.assertEqual(mock_urlopen.call_count, 1)

            self.assertEqual(len(result["images_saved"]), 1)
            self.assertEqual(result["images_failed"], [])
            body_filename = result["images_saved"][0]

            note_text = Path(result["note_path"]).read_text(encoding="utf-8")
            self.assertIn("> 冒頭のテキスト", note_text)
            self.assertIn(f"> ![[80_Attachments/{body_filename}]]", note_text)
            self.assertIn("> 続きのテキスト", note_text)
            self.assertNotIn("https://example.com/body1.png", note_text)

    def test_full_textとsummaryで同一URLが参照される場合ダウンロードは1回で同じファイル名が両方に使われる(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            content_path = self._make_content_json(
                tmp,
                {
                    "title": "本文共有画像記事",
                    "summary": [
                        {"text": "要約A", "image_url": "https://example.com/shared2.png"}
                    ],
                    "key_points": [],
                    "full_text": "冒頭\n\n![説明](https://example.com/shared2.png)\n\n末尾",
                },
            )
            mock_response = self._mock_response(b"shared2data", "image/png")
            with patch(
                "clip_save.urllib.request.urlopen", return_value=mock_response
            ) as mock_urlopen:
                result = self._run_main(
                    [
                        "--url",
                        "https://example.com/body-shared-article",
                        "--content-json",
                        str(content_path),
                        "--vault-root",
                        str(vault_root),
                        "--tag",
                        "python/pandas",
                    ]
                )
                self.assertEqual(mock_urlopen.call_count, 1)

            self.assertEqual(len(result["images_saved"]), 1)
            shared_filename = result["images_saved"][0]

            note_text = Path(result["note_path"]).read_text(encoding="utf-8")
            self.assertIn(f"- 要約A\n  ![[80_Attachments/{shared_filename}]]", note_text)
            self.assertIn(f"> ![[80_Attachments/{shared_filename}]]", note_text)

    def test_full_text内の画像ダウンロード失敗時は該当箇所が取り除かれimages_failedに記録される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            content_path = self._make_content_json(
                tmp,
                {
                    "title": "本文画像失敗記事",
                    "summary": [],
                    "key_points": [],
                    "full_text": (
                        "冒頭のテキスト\n\n"
                        "![説明](https://example.com/broken-body.jpg)\n\n"
                        "続きのテキスト"
                    ),
                },
            )
            with patch(
                "clip_save.urllib.request.urlopen", side_effect=OSError("network error")
            ):
                result = self._run_main(
                    [
                        "--url",
                        "https://example.com/broken-body-article",
                        "--content-json",
                        str(content_path),
                        "--vault-root",
                        str(vault_root),
                        "--tag",
                        "python/pandas",
                    ]
                )

            self.assertEqual(result["images_saved"], [])
            self.assertEqual(
                result["images_failed"], ["https://example.com/broken-body.jpg"]
            )

            note_path = Path(result["note_path"])
            self.assertTrue(note_path.exists())
            note_text = note_path.read_text(encoding="utf-8")
            self.assertIn("> 冒頭のテキスト", note_text)
            self.assertIn("> 続きのテキスト", note_text)
            self.assertNotIn("https://example.com/broken-body.jpg", note_text)
            self.assertNotIn("![[80_Attachments/", note_text)

    def test_full_textに画像が無い場合は従来通りテキストのみのblockquoteになる(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            content_path = self._make_content_json(
                tmp,
                {
                    "title": "画像無し本文記事",
                    "summary": [],
                    "key_points": [],
                    "full_text": "画像を含まない本文テキスト",
                },
            )
            with patch("clip_save.urllib.request.urlopen") as mock_urlopen:
                result = self._run_main(
                    [
                        "--url",
                        "https://example.com/no-body-image",
                        "--content-json",
                        str(content_path),
                        "--vault-root",
                        str(vault_root),
                        "--tag",
                        "python/pandas",
                    ]
                )
                mock_urlopen.assert_not_called()

            self.assertEqual(result["images_saved"], [])
            self.assertEqual(result["images_failed"], [])
            note_text = Path(result["note_path"]).read_text(encoding="utf-8")
            self.assertIn("> 画像を含まない本文テキスト", note_text)

    def test_full_text内で画像行とテキスト行が混在してもblockquote化が各行に正しく行われる(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            content_path = self._make_content_json(
                tmp,
                {
                    "title": "混在本文記事",
                    "summary": [],
                    "key_points": [],
                    "full_text": (
                        "1行目のテキスト\n"
                        "![alt1](https://example.com/mix1.png)\n"
                        "2行目のテキスト\n"
                        "![alt2](https://example.com/mix2.png)\n"
                        "3行目のテキスト"
                    ),
                },
            )
            responses = {
                "https://example.com/mix1.png": self._mock_response(b"mix1", "image/png"),
                "https://example.com/mix2.png": self._mock_response(b"mix2", "image/png"),
            }
            with patch(
                "clip_save.urllib.request.urlopen",
                side_effect=self._mock_urlopen_by_url(responses),
            ):
                result = self._run_main(
                    [
                        "--url",
                        "https://example.com/mix-article",
                        "--content-json",
                        str(content_path),
                        "--vault-root",
                        str(vault_root),
                        "--tag",
                        "python/pandas",
                    ]
                )

            self.assertEqual(len(result["images_saved"]), 2)
            self.assertEqual(result["images_failed"], [])

            note_text = Path(result["note_path"]).read_text(encoding="utf-8")
            lines = note_text.splitlines()
            body_lines = [
                line for line in lines if line.startswith("> ") or line == ">"
            ]
            self.assertIn("> 1行目のテキスト", body_lines)
            self.assertIn("> 2行目のテキスト", body_lines)
            self.assertIn("> 3行目のテキスト", body_lines)
            image_lines = [line for line in body_lines if "![[80_Attachments/" in line]
            self.assertEqual(len(image_lines), 2)
            for image_line in image_lines:
                self.assertTrue(image_line.startswith("> ![[80_Attachments/"))

    def test_tagがfrontmatterのtagsリストに追加される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            content_path = self._make_content_json(
                tmp,
                {
                    "title": "タグ付き記事",
                    "summary": [],
                    "key_points": [],
                    "full_text": "",
                },
            )
            result = self._run_main(
                [
                    "--url",
                    "https://example.com/tagged",
                    "--content-json",
                    str(content_path),
                    "--vault-root",
                    str(vault_root),
                    "--tag",
                    "python/pandas",
                ]
            )
            note_text = Path(result["note_path"]).read_text(encoding="utf-8")
            fm, _ = vault_lib.split_frontmatter(note_text)
            self.assertIn("python/pandas", vault_lib.get_fm_tags(fm))

    def test_tagは既存の静的webclipタグと共存する(self):
        # 実行時点のWebClip_Template.mdのtags:ブロック(`- webclip`を含む)を前提に、
        # 既存の静的タグを壊さずカテゴリタグが追加されることを確認する。
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            content_path = self._make_content_json(
                tmp,
                {
                    "title": "共存タグ記事",
                    "summary": [],
                    "key_points": [],
                    "full_text": "",
                },
            )
            result = self._run_main(
                [
                    "--url",
                    "https://example.com/coexist",
                    "--content-json",
                    str(content_path),
                    "--vault-root",
                    str(vault_root),
                    "--tag",
                    "python/pandas",
                ]
            )
            note_text = Path(result["note_path"]).read_text(encoding="utf-8")
            fm, _ = vault_lib.split_frontmatter(note_text)
            tags = vault_lib.get_fm_tags(fm)
            self.assertIn("webclip", tags)
            self.assertIn("python/pandas", tags)

    def test_tagはtagsブロックが空でも追加される(self):
        # テンプレートのtags:ブロックが空(子要素無し)の場合でもタグが追加されることを
        # build_note_textで直接検証する。
        empty_tags_template = TEMPLATE_TEXT.replace("tags:\n  - webclip\n", "tags:\n")
        note = clip_save.build_note_text(
            template_text=empty_tags_template,
            title="空タグ記事",
            dt=datetime.datetime(2026, 9, 21, 10, 0),
            url="https://example.com/empty-tags",
            summary_items=[],
            key_points_items=[],
            full_text="",
            tag="python/pandas",
        )
        fm, _ = vault_lib.split_frontmatter(note)
        self.assertEqual(vault_lib.get_fm_tags(fm), ["python/pandas"])

    def test_同タイトルで実行するとファイル名が衝突回避される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            content_path = self._make_content_json(
                tmp,
                {
                    "title": "重複記事",
                    "summary": [],
                    "key_points": [],
                    "full_text": "",
                },
            )
            argv = [
                "--url",
                "https://example.com/dup",
                "--content-json",
                str(content_path),
                "--vault-root",
                str(vault_root),
                "--tag",
                "python/pandas",
            ]
            first = self._run_main(argv)
            second = self._run_main(argv)
            self.assertNotEqual(first["note_path"], second["note_path"])
            self.assertTrue(Path(first["note_path"]).exists())
            self.assertTrue(Path(second["note_path"]).exists())
            self.assertEqual(Path(second["note_path"]).name, "重複記事-2.md")


if __name__ == "__main__":
    unittest.main()
