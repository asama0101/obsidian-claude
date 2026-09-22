"""webclip_save.py のユニットテスト。

pytest（`.claude/skills/vault/scripts/.venv/`のvenv限定の開発依存）を使用する。ネットワークアクセスは行わず、
urllib.request.urlopen をモックして検証する。
"""

import datetime
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

# scripts/ ディレクトリを import パスに追加する
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import webclip_save  # noqa: E402
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


def _make_vault(tmp):
    vault_root = Path(tmp)
    (vault_root / "70_Templates").mkdir(parents=True)
    (vault_root / "70_Templates" / "WebClip_Template.md").write_text(
        TEMPLATE_TEXT, encoding="utf-8"
    )
    (vault_root / "80_Attachments").mkdir()
    (vault_root / "20_Areas" / "WebClips").mkdir(parents=True)
    (vault_root / "10_Projects").mkdir()
    return vault_root


def _make_content_json(tmp, content):
    path = Path(tmp) / "content.json"
    path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    return path


def _mock_response(data: bytes, content_type: str):
    response = MagicMock()
    response.read.return_value = data
    response.headers.get_content_type.return_value = content_type
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def _mock_urlopen_by_url(responses: dict):
    """URLごとに異なるレスポンスを返すside_effect関数を作る。"""

    def _side_effect(request, timeout=10.0):
        url = request.full_url if hasattr(request, "full_url") else request
        return responses[url]

    return _side_effect


def _run_main(argv):
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exit_code = webclip_save.main(argv)
    assert exit_code == 0
    return json.loads(stdout.getvalue())


def test_summaryとkey_pointsの項目に紐づく画像がその直下に埋め込まれる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        content_path = _make_content_json(
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
            "https://example.com/s1.png": _mock_response(b"s1data", "image/png"),
            "https://example.com/k1.jpg": _mock_response(b"k1data", "image/jpeg"),
        }
        with patch(
            "webclip_save.urllib.request.urlopen",
            side_effect=_mock_urlopen_by_url(responses),
        ):
            result = _run_main(
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

        assert len(result["images_saved"]) == 2
        assert result["images_failed"] == []

        note_path = Path(result["note_path"])
        note_text = note_path.read_text(encoding="utf-8")

        s1_filename = next(f for f in result["images_saved"] if f.endswith(".png"))
        k1_filename = next(f for f in result["images_saved"] if f.endswith(".jpg"))

        assert f"- 要約1\n  ![[80_Attachments/{s1_filename}]]\n- 要約2" in note_text
        assert f"- ポイント1\n  ![[80_Attachments/{k1_filename}]]" in note_text
        assert "> 本文全文です" in note_text


def test_画像ダウンロード時にUser_Agentヘッダを送る():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        content_path = _make_content_json(
            tmp,
            {
                "title": "UAテスト記事",
                "summary": [
                    {"text": "要約1", "image_url": "https://example.com/s1.png"}
                ],
                "key_points": [],
                "full_text": "本文",
            },
        )
        mock_response = _mock_response(b"s1data", "image/png")
        with patch(
            "webclip_save.urllib.request.urlopen", return_value=mock_response
        ) as mock_urlopen:
            _run_main(
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

        request_arg = mock_urlopen.call_args[0][0]
        assert request_arg.full_url == "https://example.com/s1.png"
        assert "User-agent" in request_arg.headers
        assert "Mozilla" in request_arg.headers["User-agent"]


def test_image_urlを持たない項目には画像が埋め込まれない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        content_path = _make_content_json(
            tmp,
            {
                "title": "画像なし記事",
                "summary": [{"text": "要約のみ"}],
                "key_points": [{"text": "ポイントのみ", "image_url": ""}],
                "full_text": "本文",
            },
        )
        with patch("webclip_save.urllib.request.urlopen") as mock_urlopen:
            result = _run_main(
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

        assert result["images_saved"] == []
        assert result["images_failed"] == []

        note_text = Path(result["note_path"]).read_text(encoding="utf-8")
        assert "![[80_Attachments/" not in note_text


def test_同じimage_urlが複数項目で参照される場合はダウンロードが1回だけになる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        content_path = _make_content_json(
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
        mock_response = _mock_response(b"shareddata", "image/png")
        with patch(
            "webclip_save.urllib.request.urlopen", return_value=mock_response
        ) as mock_urlopen:
            result = _run_main(
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
            assert mock_urlopen.call_count == 1

        assert len(result["images_saved"]) == 1
        shared_filename = result["images_saved"][0]

        note_text = Path(result["note_path"]).read_text(encoding="utf-8")
        assert f"- 要約A\n  ![[80_Attachments/{shared_filename}]]" in note_text
        assert f"- ポイントB\n  ![[80_Attachments/{shared_filename}]]" in note_text


def test_full_textが加工されず全文そのまま引用形式で本文に入る():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        long_text = "あ" * 5000
        content_path = _make_content_json(
            tmp,
            {
                "title": "長文記事",
                "summary": [],
                "key_points": [],
                "full_text": long_text,
            },
        )
        result = _run_main(
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
        assert f"> {long_text}" in note_text


def test_画像ダウンロード失敗時はスキップされノート作成は続行される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        content_path = _make_content_json(
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
            "webclip_save.urllib.request.urlopen", side_effect=OSError("network error")
        ):
            result = _run_main(
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

        assert result["images_saved"] == []
        assert result["images_failed"] == ["https://example.com/broken.jpg"]

        note_path = Path(result["note_path"])
        assert note_path.exists()
        assert len(list((vault_root / "80_Attachments").iterdir())) == 0

        note_text = note_path.read_text(encoding="utf-8")
        assert "- 要約" in note_text
        assert "![[80_Attachments/" not in note_text


def test_frontmatterのurlとdateが正しく設定される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        content_path = _make_content_json(
            tmp,
            {
                "title": "日付テスト記事",
                "summary": [],
                "key_points": [],
                "full_text": "",
            },
        )
        result = _run_main(
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
        assert vault_lib.get_fm_value(fm, "url") == "https://example.com/dated"
        today = datetime.date.today().strftime("%Y-%m-%d")
        assert vault_lib.get_fm_value(fm, "date") == today


def test_full_text内の画像記法が抽出されダウンロードされblockquote内でローカル埋め込みに置換される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        content_path = _make_content_json(
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
        mock_response = _mock_response(b"body1data", "image/png")
        with patch(
            "webclip_save.urllib.request.urlopen", return_value=mock_response
        ) as mock_urlopen:
            result = _run_main(
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
            assert mock_urlopen.call_count == 1

        assert len(result["images_saved"]) == 1
        assert result["images_failed"] == []
        body_filename = result["images_saved"][0]

        note_text = Path(result["note_path"]).read_text(encoding="utf-8")
        assert "> 冒頭のテキスト" in note_text
        assert f"> ![[80_Attachments/{body_filename}]]" in note_text
        assert "> 続きのテキスト" in note_text
        assert "https://example.com/body1.png" not in note_text


def test_full_textとsummaryで同一URLが参照される場合ダウンロードは1回で同じファイル名が両方に使われる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        content_path = _make_content_json(
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
        mock_response = _mock_response(b"shared2data", "image/png")
        with patch(
            "webclip_save.urllib.request.urlopen", return_value=mock_response
        ) as mock_urlopen:
            result = _run_main(
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
            assert mock_urlopen.call_count == 1

        assert len(result["images_saved"]) == 1
        shared_filename = result["images_saved"][0]

        note_text = Path(result["note_path"]).read_text(encoding="utf-8")
        assert f"- 要約A\n  ![[80_Attachments/{shared_filename}]]" in note_text
        assert f"> ![[80_Attachments/{shared_filename}]]" in note_text


def test_full_text内の画像ダウンロード失敗時は該当箇所が取り除かれimages_failedに記録される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        content_path = _make_content_json(
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
            "webclip_save.urllib.request.urlopen", side_effect=OSError("network error")
        ):
            result = _run_main(
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

        assert result["images_saved"] == []
        assert result["images_failed"] == ["https://example.com/broken-body.jpg"]

        note_path = Path(result["note_path"])
        assert note_path.exists()
        note_text = note_path.read_text(encoding="utf-8")
        assert "> 冒頭のテキスト" in note_text
        assert "> 続きのテキスト" in note_text
        assert "https://example.com/broken-body.jpg" not in note_text
        assert "![[80_Attachments/" not in note_text


def test_full_textに画像が無い場合は従来通りテキストのみのblockquoteになる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        content_path = _make_content_json(
            tmp,
            {
                "title": "画像無し本文記事",
                "summary": [],
                "key_points": [],
                "full_text": "画像を含まない本文テキスト",
            },
        )
        with patch("webclip_save.urllib.request.urlopen") as mock_urlopen:
            result = _run_main(
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

        assert result["images_saved"] == []
        assert result["images_failed"] == []
        note_text = Path(result["note_path"]).read_text(encoding="utf-8")
        assert "> 画像を含まない本文テキスト" in note_text


def test_full_text内で画像行とテキスト行が混在してもblockquote化が各行に正しく行われる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        content_path = _make_content_json(
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
            "https://example.com/mix1.png": _mock_response(b"mix1", "image/png"),
            "https://example.com/mix2.png": _mock_response(b"mix2", "image/png"),
        }
        with patch(
            "webclip_save.urllib.request.urlopen",
            side_effect=_mock_urlopen_by_url(responses),
        ):
            result = _run_main(
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

        assert len(result["images_saved"]) == 2
        assert result["images_failed"] == []

        note_text = Path(result["note_path"]).read_text(encoding="utf-8")
        lines = note_text.splitlines()
        body_lines = [
            line for line in lines if line.startswith("> ") or line == ">"
        ]
        assert "> 1行目のテキスト" in body_lines
        assert "> 2行目のテキスト" in body_lines
        assert "> 3行目のテキスト" in body_lines
        image_lines = [line for line in body_lines if "![[80_Attachments/" in line]
        assert len(image_lines) == 2
        for image_line in image_lines:
            assert image_line.startswith("> ![[80_Attachments/")


def test_tagがfrontmatterのtagsリストに追加される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        content_path = _make_content_json(
            tmp,
            {
                "title": "タグ付き記事",
                "summary": [],
                "key_points": [],
                "full_text": "",
            },
        )
        result = _run_main(
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
        assert "python/pandas" in vault_lib.get_fm_tags(fm)


def test_tagは既存の静的webclipタグと共存する():
    # 実行時点のWebClip_Template.mdのtags:ブロック(`- webclip`を含む)を前提に、
    # 既存の静的タグを壊さずカテゴリタグが追加されることを確認する。
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        content_path = _make_content_json(
            tmp,
            {
                "title": "共存タグ記事",
                "summary": [],
                "key_points": [],
                "full_text": "",
            },
        )
        result = _run_main(
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
        assert "webclip" in tags
        assert "python/pandas" in tags


def test_tagはtagsブロックが空でも追加される():
    # テンプレートのtags:ブロックが空(子要素無し)の場合でもタグが追加されることを
    # build_note_textで直接検証する。
    empty_tags_template = TEMPLATE_TEXT.replace("tags:\n  - webclip\n", "tags:\n")
    note = webclip_save.build_note_text(
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
    assert vault_lib.get_fm_tags(fm) == ["python/pandas"]


def test_同タイトルで実行するとファイル名が衝突回避される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        content_path = _make_content_json(
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
        first = _run_main(argv)
        second = _run_main(argv)
        assert first["note_path"] != second["note_path"]
        assert Path(first["note_path"]).exists()
        assert Path(second["note_path"]).exists()
        assert Path(second["note_path"]).name == "重複記事-2.md"
