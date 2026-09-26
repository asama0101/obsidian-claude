"""task_todo_apply.py のユニットテスト。

pytest（`.claude/skills/vault/scripts/.venv/`のvenv限定の開発依存）を使用する。
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import task_todo_apply  # noqa: E402

_NOTE_TEXT = (
    "---\n"
    "type: task\n"
    'project: ""\n'
    'source_meeting: ""\n'
    "created_date:\n"
    "start_date:\n"
    "due_date:\n"
    "status: 1_todo\n"
    'memo: ""\n'
    "---\n"
    "\n"
    "## 📌 進捗メモ\n"
    "- [ ] \n"
    "\n"
    "## 🔗 関連リンク・参照資料\n"
    "- \n"
    "\n"
    "## 📝 メモ\n"
)


# ---------------------------------------------------------------------------
# _apply_todos() 単体テスト
# ---------------------------------------------------------------------------


def test_プレースホルダーのみのセクションは置換される():
    new_section, mode, added = task_todo_apply._apply_todos("- [ ] ", ["資料を確認する"])
    assert new_section == "- [ ] 資料を確認する"
    assert mode == "replace"
    assert added == 1


def test_空セクションは置換される():
    new_section, mode, added = task_todo_apply._apply_todos("", ["資料を確認する"])
    assert new_section == "- [ ] 資料を確認する"
    assert mode == "replace"
    assert added == 1


def test_空白行だけのセクションは置換される():
    new_section, mode, added = task_todo_apply._apply_todos("\n  \n", ["資料を確認する"])
    assert new_section == "- [ ] 資料を確認する"
    assert mode == "replace"
    assert added == 1


def test_実質的な記載があるセクションは追記される():
    existing = "- [x] 完了済みタスク"
    new_section, mode, added = task_todo_apply._apply_todos(existing, ["新しいタスク"])
    assert new_section == "- [x] 完了済みタスク\n- [ ] 新しいタスク"
    assert mode == "append"
    assert added == 1


def test_複数todoを渡すと複数行になる():
    new_section, mode, added = task_todo_apply._apply_todos("- [ ] ", ["タスクA", "タスクB"])
    assert new_section == "- [ ] タスクA\n- [ ] タスクB"
    assert mode == "replace"
    assert added == 2


def test_空白のみのtodoは除外される():
    new_section, mode, added = task_todo_apply._apply_todos("- [ ] ", ["タスクA", "   ", ""])
    assert new_section == "- [ ] タスクA"
    assert mode == "replace"
    assert added == 1


def test_追記モードで完全一致のtodoは重複追加されない():
    existing = "- [ ] 既存タスク"
    new_section, mode, added = task_todo_apply._apply_todos(existing, ["既存タスク", "新規タスク"])
    assert new_section == "- [ ] 既存タスク\n- [ ] 新規タスク"
    assert mode == "append"
    assert added == 1


# ---------------------------------------------------------------------------
# CLI 統合テスト
# ---------------------------------------------------------------------------


def _make_vault(tmp):
    vault_root = Path(tmp)
    tasks_dir = vault_root / "30_Areas" / "Tasks"
    tasks_dir.mkdir(parents=True)
    note_path = tasks_dir / "資料を送る.md"
    note_path.write_text(_NOTE_TEXT, encoding="utf-8")
    return vault_root, note_path


def _run(vault_root, *extra_args):
    script_path = Path(__file__).resolve().parent.parent / "task_todo_apply.py"
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
        encoding="utf-8",
    )


def test_正常系でtodoが未チェックで追加されJSONが出力される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root, note_path = _make_vault(tmp)
        result = _run(
            vault_root,
            "--note",
            str(note_path),
            "--todo",
            "資料を確認する",
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output == {
            "status": "ok",
            "note_path": str(note_path),
            "added": 1,
            "mode": "replace",
        }
        content = note_path.read_text(encoding="utf-8")
        assert "- [ ] 資料を確認する" in content
        assert "- [x]" not in content
        # frontmatterは変更されない
        assert 'project: ""' in content
        assert "status: 1_todo" in content
        # 他セクションは変更されない
        assert "## 🔗 関連リンク・参照資料" in content
        assert "## 📝 メモ" in content


def test_相対パスはvault_root基準で解決される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root, note_path = _make_vault(tmp)
        result = _run(
            vault_root,
            "--note",
            "30_Areas/Tasks/資料を送る.md",
            "--todo",
            "資料を確認する",
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["mode"] == "replace"


def test_実質的な記載がある場合は追記されmodeがappendになる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root, note_path = _make_vault(tmp)
        # 1回目: プレースホルダーを置換
        result1 = _run(vault_root, "--note", str(note_path), "--todo", "1個目のタスク")
        assert result1.returncode == 0
        output1 = json.loads(result1.stdout)
        assert output1["mode"] == "replace"

        # 2回目: 実質的な記載があるため追記
        result2 = _run(vault_root, "--note", str(note_path), "--todo", "2個目のタスク")
        assert result2.returncode == 0
        output2 = json.loads(result2.stdout)
        assert output2["mode"] == "append"

        content = note_path.read_text(encoding="utf-8")
        assert "- [ ] 1個目のタスク" in content
        assert "- [ ] 2個目のタスク" in content


def test_複数todo指定で件数が加算される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root, note_path = _make_vault(tmp)
        result = _run(
            vault_root,
            "--note",
            str(note_path),
            "--todo",
            "タスクA",
            "--todo",
            "タスクB",
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["added"] == 2
        content = note_path.read_text(encoding="utf-8")
        assert "- [ ] タスクA" in content
        assert "- [ ] タスクB" in content


def test_todo未指定はエラーになる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root, note_path = _make_vault(tmp)
        result = _run(vault_root, "--note", str(note_path))
        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output == {"status": "error", "reason": "no_todos"}


def test_空白のみのtodoしか無ければエラーになる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root, note_path = _make_vault(tmp)
        result = _run(vault_root, "--note", str(note_path), "--todo", "   ")
        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output == {"status": "error", "reason": "no_todos"}


def test_存在しないノートはエラーになる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root, note_path = _make_vault(tmp)
        missing_path = note_path.parent / "存在しない.md"
        result = _run(vault_root, "--note", str(missing_path), "--todo", "タスクA")
        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output == {"status": "error", "reason": "note_not_found"}


def test_taskノートでなければエラーになる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        notes_dir = vault_root / "30_Areas"
        notes_dir.mkdir(parents=True)
        note_path = notes_dir / "メモ.md"
        note_path.write_text(
            "---\ntype: memo\n---\n\n## 📌 進捗メモ\n- [ ] \n",
            encoding="utf-8",
        )
        result = _run(vault_root, "--note", str(note_path), "--todo", "タスクA")
        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output == {"status": "error", "reason": "not_a_task_note"}


def test_有効todoと空白のみtodoが混在する場合は空白除外後の件数になる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root, note_path = _make_vault(tmp)
        result = _run(
            vault_root,
            "--note",
            str(note_path),
            "--todo",
            "タスクA",
            "--todo",
            "   ",
            "--todo",
            "タスクB",
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["added"] == 2
        content = note_path.read_text(encoding="utf-8")
        assert content.count("- [ ] タスクA") == 1
        assert content.count("- [ ] タスクB") == 1
        assert "- [ ]    " not in content


def test_重複するtodoのみが渡された場合addedは0になる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root, note_path = _make_vault(tmp)
        # 1回目: 1個目のタスクを追加（replace）
        result1 = _run(vault_root, "--note", str(note_path), "--todo", "既存タスク")
        assert result1.returncode == 0
        output1 = json.loads(result1.stdout)
        assert output1["added"] == 1
        assert output1["mode"] == "replace"

        # 2回目: 同じタスクを追加しようとする（重複なので実際には追加されない）
        result2 = _run(vault_root, "--note", str(note_path), "--todo", "既存タスク")
        assert result2.returncode == 0
        output2 = json.loads(result2.stdout)
        # addedは0（実際には追加されていない）
        assert output2["added"] == 0
        assert output2["mode"] == "append"

        content = note_path.read_text(encoding="utf-8")
        # 1個のタスクのみ存在する（重複が追加されていない）
        assert content.count("- [ ] 既存タスク") == 1


def test_相対パストラバーサルはvault外エラーになる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root, _ = _make_vault(tmp)
        result = _run(vault_root, "--note", "../外部.md", "--todo", "タスクA")
        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output == {"status": "error", "reason": "path_outside_vault"}


def test_vault外のパスはエラーになる():
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other_tmp:
        vault_root, _ = _make_vault(tmp)
        outside_path = Path(other_tmp) / "外部.md"
        outside_path.write_text(_NOTE_TEXT, encoding="utf-8")
        result = _run(vault_root, "--note", str(outside_path), "--todo", "タスクA")
        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output == {"status": "error", "reason": "path_outside_vault"}
