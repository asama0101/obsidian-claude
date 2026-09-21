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
    'project: ""\n'
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

    def _run_main(self, argv):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = clip_save.main(argv)
        self.assertEqual(exit_code, 0)
        return json.loads(stdout.getvalue())

    def test_画像ダウンロード成功時にファイルが保存されノートに埋め込まれる(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            content_path = self._make_content_json(
                tmp,
                {
                    "title": "テスト記事",
                    "summary": ["要約1", "要約2"],
                    "key_points": ["ポイント1"],
                    "excerpt": "本文の抜粋です",
                    "image_urls": ["https://example.com/photo.png"],
                },
            )
            mock_response = self._mock_response(b"fakeimagedata", "image/png")
            with patch("clip_save.urllib.request.urlopen", return_value=mock_response):
                result = self._run_main(
                    [
                        "--url",
                        "https://example.com/article",
                        "--content-json",
                        str(content_path),
                        "--vault-root",
                        str(vault_root),
                    ]
                )

            self.assertEqual(len(result["images_saved"]), 1)
            self.assertEqual(result["images_failed"], [])

            note_path = Path(result["note_path"])
            self.assertTrue(note_path.exists())
            note_text = note_path.read_text(encoding="utf-8")

            saved_filename = result["images_saved"][0]
            self.assertTrue((vault_root / "80_Attachments" / saved_filename).exists())
            self.assertIn(f"![[80_Attachments/{saved_filename}]]", note_text)
            self.assertTrue(saved_filename.endswith(".png"))
            self.assertIn("要約1", note_text)
            self.assertIn("ポイント1", note_text)
            self.assertIn("> 本文の抜粋です", note_text)

    def test_画像ダウンロード失敗時はスキップされノート作成は続行される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            content_path = self._make_content_json(
                tmp,
                {
                    "title": "失敗テスト記事",
                    "summary": ["要約"],
                    "key_points": ["ポイント"],
                    "excerpt": "抜粋",
                    "image_urls": ["https://example.com/broken.jpg"],
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
                    ]
                )

            self.assertEqual(result["images_saved"], [])
            self.assertEqual(result["images_failed"], ["https://example.com/broken.jpg"])

            note_path = Path(result["note_path"])
            self.assertTrue(note_path.exists())
            self.assertEqual(len(list((vault_root / "80_Attachments").iterdir())), 0)

    def test_project_hintから正しく推定されfrontmatterに設定される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            (vault_root / "10_Projects" / "VaultMigration").mkdir()
            content_path = self._make_content_json(
                tmp,
                {
                    "title": "プロジェクト記事",
                    "summary": [],
                    "key_points": [],
                    "excerpt": "",
                    "image_urls": [],
                },
            )
            result = self._run_main(
                [
                    "--url",
                    "https://example.com/proj",
                    "--content-json",
                    str(content_path),
                    "--project-hint",
                    "VaultMigrationについての記事",
                    "--vault-root",
                    str(vault_root),
                ]
            )
            note_text = Path(result["note_path"]).read_text(encoding="utf-8")
            fm, _ = vault_lib.split_frontmatter(note_text)
            self.assertEqual(vault_lib.get_fm_value(fm, "project"), "[[VaultMigration]]")

    def test_project_hintが一致しない場合はfrontmatterのprojectが空欄のまま(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            (vault_root / "10_Projects" / "VaultMigration").mkdir()
            content_path = self._make_content_json(
                tmp,
                {
                    "title": "無関係記事",
                    "summary": [],
                    "key_points": [],
                    "excerpt": "",
                    "image_urls": [],
                },
            )
            result = self._run_main(
                [
                    "--url",
                    "https://example.com/unrelated",
                    "--content-json",
                    str(content_path),
                    "--project-hint",
                    "全く関係ない話題",
                    "--vault-root",
                    str(vault_root),
                ]
            )
            note_text = Path(result["note_path"]).read_text(encoding="utf-8")
            fm, _ = vault_lib.split_frontmatter(note_text)
            self.assertEqual(vault_lib.get_fm_value(fm, "project"), "")

    def test_frontmatterのurlとdateが正しく設定される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            content_path = self._make_content_json(
                tmp,
                {
                    "title": "日付テスト記事",
                    "summary": [],
                    "key_points": [],
                    "excerpt": "",
                    "image_urls": [],
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
                ]
            )
            note_text = Path(result["note_path"]).read_text(encoding="utf-8")
            fm, _ = vault_lib.split_frontmatter(note_text)
            self.assertEqual(vault_lib.get_fm_value(fm, "url"), "https://example.com/dated")
            today = datetime.date.today().strftime("%Y-%m-%d")
            self.assertEqual(vault_lib.get_fm_value(fm, "date"), today)

    def test_同タイトルで実行するとファイル名が衝突回避される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = self._make_vault(tmp)
            content_path = self._make_content_json(
                tmp,
                {
                    "title": "重複記事",
                    "summary": [],
                    "key_points": [],
                    "excerpt": "",
                    "image_urls": [],
                },
            )
            argv = [
                "--url",
                "https://example.com/dup",
                "--content-json",
                str(content_path),
                "--vault-root",
                str(vault_root),
            ]
            first = self._run_main(argv)
            second = self._run_main(argv)
            self.assertNotEqual(first["note_path"], second["note_path"])
            self.assertTrue(Path(first["note_path"]).exists())
            self.assertTrue(Path(second["note_path"]).exists())
            self.assertEqual(Path(second["note_path"]).name, "重複記事-2.md")


if __name__ == "__main__":
    unittest.main()
