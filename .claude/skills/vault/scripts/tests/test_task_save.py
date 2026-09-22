"""task_save.py のユニットテスト。

pytest（`.claude/skills/vault/scripts/.venv/`のvenv限定の開発依存）を使用する。
"""

import datetime
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# scripts/ ディレクトリを import パスに追加する
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import task_save  # noqa: E402
import vault_lib  # noqa: E402

_TEMPLATE_TEXT = (
    "---\n"
    "type: task\n"
    'project: ""\n'
    'source_meeting: ""\n'
    "created_date:\n"
    "start_date:\n"
    "due_date:\n"
    "status: 1_todo\n"
    "tags:\n"
    "  - task\n"
    "---\n"
    "# {{title}}\n"
    "\n"
    "## 📌 作業手順・サブタスク\n"
    "- [ ] \n"
    "\n"
    "## 🔗 関連リンク・参照資料\n"
    "- \n"
    "\n"
    "## 📝 メモ\n"
)


def test_リンク形式からプロジェクト名を取り出す():
    assert vault_lib.extract_project_name("[[VaultMigration]]") == "VaultMigration"


def test_リンク形式でなければそのまま返す():
    assert vault_lib.extract_project_name("PlainName") == "PlainName"


@pytest.fixture
def dt():
    return datetime.datetime(2026, 9, 21, 14, 30)


def _split(note_text: str) -> tuple[str, str]:
    lines = note_text.split("\n")
    assert lines[0] == "---"
    for i in range(1, len(lines)):
        if lines[i] == "---":
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :])
    raise AssertionError("frontmatter終端が見つからない")


def test_projectとstatusが設定される(dt):
    note_text = task_save.build_note_text(
        _TEMPLATE_TEXT,
        title="資料を送る",
        project="[[VaultMigration]]",
        due_date=None,
        dt=dt,
    )
    fm_text, body_text = _split(note_text)
    assert 'project: "[[VaultMigration]]"' in fm_text
    assert "status: 1_todo" in fm_text
    assert "# 資料を送る" in body_text


def test_created_dateがクォート無しでセットされる(dt):
    note_text = task_save.build_note_text(
        _TEMPLATE_TEXT,
        title="資料を送る",
        project="[[VaultMigration]]",
        due_date=None,
        dt=dt,
    )
    fm_text, _ = _split(note_text)
    lines = fm_text.split("\n")
    assert "created_date: 2026-09-21" in lines
    assert 'created_date: "2026-09-21"' not in fm_text


def test_start_dateはセットされない(dt):
    note_text = task_save.build_note_text(
        _TEMPLATE_TEXT,
        title="資料を送る",
        project="[[VaultMigration]]",
        due_date=None,
        dt=dt,
    )
    fm_text, _ = _split(note_text)
    lines = fm_text.split("\n")
    # テンプレートの空欄のまま(クォート無し・日付未セット)であること
    assert "start_date:" in lines
    assert "start_date: 2026-09-21" not in lines
    assert 'start_date: "2026-09-21"' not in fm_text


def test_due_date未指定なら空欄のまま(dt):
    note_text = task_save.build_note_text(
        _TEMPLATE_TEXT,
        title="資料を送る",
        project="[[VaultMigration]]",
        due_date=None,
        dt=dt,
    )
    fm_text, _ = _split(note_text)
    lines = fm_text.split("\n")
    assert "due_date: " in lines
    assert 'due_date: ""' not in fm_text


def test_due_date指定時はクォート無しでその値が設定される(dt):
    note_text = task_save.build_note_text(
        _TEMPLATE_TEXT,
        title="資料を送る",
        project="[[VaultMigration]]",
        due_date="2026-10-01",
        dt=dt,
    )
    fm_text, _ = _split(note_text)
    lines = fm_text.split("\n")
    assert "due_date: 2026-10-01" in lines
    assert 'due_date: "2026-10-01"' not in fm_text


def test_source指定時はsource_meetingが設定される(dt):
    note_text = task_save.build_note_text(
        _TEMPLATE_TEXT,
        title="資料を送る",
        project="[[VaultMigration]]",
        due_date=None,
        source="[[2026-09-21 定例MTG]]",
        dt=dt,
    )
    fm_text, _ = _split(note_text)
    assert 'source_meeting: "[[2026-09-21 定例MTG]]"' in fm_text


def test_source未指定ならsource_meetingは空欄のまま(dt):
    note_text = task_save.build_note_text(
        _TEMPLATE_TEXT,
        title="資料を送る",
        project="[[VaultMigration]]",
        due_date=None,
        dt=dt,
    )
    fm_text, _ = _split(note_text)
    assert 'source_meeting: ""' in fm_text


def _make_vault(tmp, project_names=()):
    vault_root = Path(tmp)
    template_dir = vault_root / "70_Templates"
    template_dir.mkdir(parents=True)
    (template_dir / "Task_Template.md").write_text(_TEMPLATE_TEXT, encoding="utf-8")
    for name in project_names:
        (vault_root / "10_Projects" / name).mkdir(parents=True)
    return vault_root


def _run(vault_root, *extra_args):
    script_path = Path(__file__).resolve().parent.parent / "task_save.py"
    return subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--vault-root",
            str(vault_root),
            *extra_args,
        ],
        capture_output=True,
        text=True,
    )


def test_project未指定なら20_Areas_Tasks配下に保存される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        result = _run(vault_root, "--title", "資料を送る")
        assert result.returncode == 0
        output = json.loads(result.stdout)
        note_path = Path(output["note_path"])
        assert note_path.exists()
        assert note_path.parent == vault_root / "20_Areas" / "Tasks"
        content = note_path.read_text(encoding="utf-8")
        assert 'project: ""' in content


def test_正常系でノートが作成されJSONが出力される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp, project_names=["VaultMigration"])
        result = _run(
            vault_root,
            "--title",
            "資料を送る",
            "--project",
            "[[VaultMigration]]",
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        note_path = Path(output["note_path"])
        assert note_path.exists()
        assert note_path.parent == vault_root / "10_Projects" / "VaultMigration" / "Tasks"
        content = note_path.read_text(encoding="utf-8")
        assert 'project: "[[VaultMigration]]"' in content
        assert "status: 1_todo" in content


def test_sourceを指定するとsource_meetingが書き込まれる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp, project_names=["VaultMigration"])
        result = _run(
            vault_root,
            "--title",
            "資料を送る",
            "--project",
            "[[VaultMigration]]",
            "--source",
            "[[2026-09-21 定例MTG]]",
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        content = Path(output["note_path"]).read_text(encoding="utf-8")
        assert 'source_meeting: "[[2026-09-21 定例MTG]]"' in content


def test_存在しないプロジェクトはエラーになる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = _make_vault(tmp)
        result = _run(
            vault_root,
            "--title",
            "資料を送る",
            "--project",
            "[[NoSuchProject]]",
        )
        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output == {"status": "error", "reason": "project_not_found"}
        assert not (vault_root / "10_Projects" / "NoSuchProject").exists()
