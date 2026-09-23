"""project_create.py のユニットテスト。

pytest（`.claude/skills/vault/scripts/.venv/`のvenv限定の開発依存）を使用する。
"""

import datetime
import sys
import tempfile
from pathlib import Path

import pytest

# scripts/ ディレクトリを import パスに追加する
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import project_create  # noqa: E402

_TEMPLATE_TEXT = (
    "---\n"
    "type: project\n"
    'start_date: "{{date:YYYY-MM-DD}}"\n'
    "due_date: \n"
    "---\n"
    "# プロジェクト: {{title}}\n"
    "\n"
    "## 🎯 概要・目的\n"
    "- \n"
)


def _make_vault(tmp) -> Path:
    vault_root = Path(tmp)
    template_dir = vault_root / "80_Templates"
    template_dir.mkdir(parents=True)
    (template_dir / "Project_Template.md").write_text(_TEMPLATE_TEXT, encoding="utf-8")
    return vault_root


@pytest.fixture
def dt():
    return datetime.datetime(2026, 9, 21, 14, 30)


def test_正常系で3つのサブフォルダとノートが作成される(dt):
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        result = project_create.create_project(
            vault_root, title="新規プロジェクト", due_date=None, dt=dt
        )

        assert result["status"] == "ok"

        project_dir = vault_root / "20_Projects" / "新規プロジェクト"
        assert (project_dir / "Tasks").is_dir()
        assert (project_dir / "Meetings").is_dir()
        assert (project_dir / "Documents").is_dir()

        note_path = Path(result["note_path"])
        assert note_path.is_file()
        assert note_path == project_dir / "新規プロジェクト.md"

        content = note_path.read_text(encoding="utf-8")
        assert 'start_date: "2026-09-21"' in content
        assert "type: project" in content
        assert "# プロジェクト: 新規プロジェクト" in content

        assert result["folders"] == ["Tasks", "Meetings", "Documents"]


def test_due_date指定時はfrontmatterにクォート無しで反映される(dt):
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        result = project_create.create_project(
            vault_root, title="期限あり", due_date="2026-10-01", dt=dt
        )

        note_path = Path(result["note_path"])
        content = note_path.read_text(encoding="utf-8")
        assert "due_date: 2026-10-01" in content
        assert 'due_date: "2026-10-01"' not in content


def test_due_date未指定ならfrontmatterは空欄のまま(dt):
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        result = project_create.create_project(
            vault_root, title="期限なし", due_date=None, dt=dt
        )

        note_path = Path(result["note_path"])
        content = note_path.read_text(encoding="utf-8")
        assert "due_date: \n" in content
        assert 'due_date: "' not in content


def test_既存プロジェクトがあれば何も作成せずエラーを返す(dt):
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        existing_dir = vault_root / "20_Projects" / "既存プロジェクト"
        existing_dir.mkdir(parents=True)

        result = project_create.create_project(
            vault_root, title="既存プロジェクト", due_date=None, dt=dt
        )

        assert result == {"status": "error", "reason": "project_already_exists"}

        # 何も新規作成されていないこと
        assert not (existing_dir / "Tasks").exists()
        assert not (existing_dir / "Meetings").exists()
        assert not (existing_dir / "Documents").exists()
        assert not (existing_dir / "既存プロジェクト.md").exists()
        assert list(existing_dir.iterdir()) == []


def test_main経由の正常系でJSONが出力される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        argv = [
            "--title",
            "CLIプロジェクト",
            "--vault-root",
            str(vault_root),
        ]
        exit_code = project_create.main(argv)

        assert exit_code == 0
        note_path = (
            vault_root / "20_Projects" / "CLIプロジェクト" / "CLIプロジェクト.md"
        )
        assert note_path.is_file()


def test_main経由の既存プロジェクトはエラー終了する():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        (vault_root / "20_Projects" / "重複プロジェクト").mkdir(parents=True)

        argv = [
            "--title",
            "重複プロジェクト",
            "--vault-root",
            str(vault_root),
        ]
        exit_code = project_create.main(argv)

        assert exit_code == 1
