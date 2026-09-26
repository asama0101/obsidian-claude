"""knowhow_save.py のユニットテスト。

pytest（`.claude/skills/vault/scripts/.venv/`のvenv限定の開発依存）を使用する。
"""

import contextlib
import datetime
import io
import json
import sys
import tempfile
from pathlib import Path

import pytest

# scripts/ ディレクトリを import パスに追加する
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import knowhow_save  # noqa: E402
import vault_lib  # noqa: E402

TEMPLATE_PATH = vault_lib.VAULT_ROOT / "80_Templates" / "Knowhow_Template.md"


def _sample_content(**overrides):
    content = {
        "title": "テストノウハウ",
        "overview": "これは概要です。",
        "steps": ["手順1を実行する", "手順2を確認する"],
        "pitfalls": ["注意点A", "注意点B"],
        "references": ["https://example.com/doc"],
        "original_text": "元のメモ行1\n元のメモ行2",
    }
    content.update(overrides)
    return content


@pytest.fixture
def template_text():
    return TEMPLATE_PATH.read_text(encoding="utf-8")


@pytest.fixture
def dt():
    return datetime.datetime(2026, 9, 21, 10, 0)


def test_categoryは書き込まれずtagsに確定タグが追加される(template_text, dt):
    content = _sample_content()
    note = knowhow_save.build_note(
        content, template_text, dt, tag="python/pandas"
    )
    fm_text, _ = vault_lib.split_frontmatter(note)
    assert vault_lib.get_fm_value(fm_text, "category") is None
    assert "python/pandas" in vault_lib.get_fm_tags(fm_text)


def test_overviewが概要セクションに入る(template_text, dt):
    content = _sample_content(overview="これは概要です。")
    note = knowhow_save.build_note(
        content, template_text, dt, tag="python/pandas"
    )
    assert "## 💡 概要・結論\n- これは概要です。" in note


def test_stepsが番号付きで手順セクションに入る(template_text, dt):
    content = _sample_content(steps=["最初の手順", "次の手順"])
    note = knowhow_save.build_note(
        content, template_text, dt, tag="python/pandas"
    )
    assert "## 🛠 手順・実行方法 / 解決策\n1. 最初の手順\n2. 次の手順" in note


def test_pitfallsが箇条書きで注意点セクションに入る(template_text, dt):
    content = _sample_content(pitfalls=["ハマりA", "ハマりB"])
    note = knowhow_save.build_note(
        content, template_text, dt, tag="python/pandas"
    )
    assert "## ⚠️ 注意点・ハマりポイント\n- ハマりA\n- ハマりB" in note


def test_referencesが箇条書きで参照セクションに入る(template_text, dt):
    content = _sample_content(
        references=["https://example.com/a", "https://example.com/b"]
    )
    note = knowhow_save.build_note(
        content, template_text, dt, tag="python/pandas"
    )
    assert (
        "## 🔗 参照・関連リンク\n- https://example.com/a\n- https://example.com/b"
        in note
    )


def test_original_textが加工されず引用形式で残る(template_text, dt):
    content = _sample_content(original_text="生ログ行1\n生ログ行2\n  インデント行")
    note = knowhow_save.build_note(
        content, template_text, dt, tag="python/pandas"
    )
    assert "## 📄 ノウハウ本文\n> 生ログ行1\n> 生ログ行2\n>   インデント行" in note


def _make_vault(tmp):
    vault_root = Path(tmp)
    (vault_root / "80_Templates").mkdir(parents=True)
    (vault_root / "80_Templates" / "Knowhow_Template.md").write_text(
        TEMPLATE_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (vault_root / "40_Resources" / "Knowledge").mkdir(parents=True)
    return vault_root


def _write_content_json(tmp, content):
    path = Path(tmp) / "content.json"
    path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    return path


def test_note_pathが出力され保存される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        content = _sample_content(title="保存テスト")
        content_json = _write_content_json(tmp, content)
        argv = [
            "--content-json",
            str(content_json),
            "--vault-root",
            str(vault_root),
            "--tag",
            "python/pandas",
        ]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = knowhow_save.main(argv)

        assert result == 0
        output = json.loads(buf.getvalue())
        note_path = Path(output["note_path"])
        assert note_path.exists()
        assert note_path.parent == vault_root / "40_Resources" / "Knowledge"
        saved_text = note_path.read_text(encoding="utf-8")
        assert "category:" not in saved_text
        assert "  - python/pandas" in saved_text


def test_ファイル名衝突時はunique_pathで回避する():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        knowledge_dir = vault_root / "40_Resources" / "Knowledge"
        existing = knowledge_dir / "衝突テスト.md"
        existing.write_text("既存ノート", encoding="utf-8")

        content = _sample_content(title="衝突テスト")
        content_json = _write_content_json(tmp, content)
        argv = [
            "--content-json",
            str(content_json),
            "--vault-root",
            str(vault_root),
            "--tag",
            "python/pandas",
        ]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            knowhow_save.main(argv)

        output = json.loads(buf.getvalue())
        note_path = Path(output["note_path"])
        assert note_path.name == "衝突テスト-2.md"
        # 既存ファイルの中身は変更されない
        assert existing.read_text(encoding="utf-8") == "既存ノート"
