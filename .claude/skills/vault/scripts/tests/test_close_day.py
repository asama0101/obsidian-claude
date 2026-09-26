"""close_day.py のユニットテスト。

実際の一時gitリポジトリ(tempfile.TemporaryDirectory)を構築し、
close_day.py をサブプロセスとして実行して検証する。
pytest（`.claude/skills/vault/scripts/.venv/`のvenv限定の開発依存）を使用する。
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
_CLOSE_DAY = _SCRIPTS_DIR / "close_day.py"

sys.path.insert(0, str(_SCRIPTS_DIR))
import close_day  # noqa: E402

_DAILY_NOTE_TEMPLATE = (
    "---\n"
    "tags:\n"
    "  - daily\n"
    "---\n"
    "# {date}\n"
    "\n"
    "## 🔗 本日作成・更新したノート\n"
    "<!-- UPDATED_NOTES_START -->\n"
    "（`/close` 実行時に自動更新される）\n"
    "<!-- UPDATED_NOTES_END -->\n"
)


def _run_git(args, cwd):
    """テスト用一時リポジトリに対してgitコマンドを実行するヘルパー。"""
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {args} failed: {result.stdout}{result.stderr}")
    return result.stdout.strip()


def _init_repo(root: Path):
    """main ブランチを既定ブランチとする空リポジトリを初期化する。"""
    _run_git(["init", "-b", "main"], cwd=root)
    _run_git(["config", "user.email", "test@example.com"], cwd=root)
    _run_git(["config", "user.name", "Test User"], cwd=root)


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit_all(root: Path, message: str):
    _run_git(["add", "-A"], cwd=root)
    _run_git(["commit", "-m", message], cwd=root)


def _run_close_day(vault_root: Path):
    return subprocess.run(
        [sys.executable, str(_CLOSE_DAY), "--vault-root", str(vault_root)],
        cwd=str(vault_root),
        capture_output=True,
        text=True,
    )


def test_日付形式でないブランチではerrorを返す():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "10_Daily" / ".gitkeep", "")
        _commit_all(root, "initial commit")
        # main ブランチのまま(日付形式ではない)実行する

        result = _run_close_day(root)

        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert payload == {"status": "error", "reason": "not_on_daily_branch"}


def test_変更が無い場合はコミットをスキップする():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "10_Daily" / ".gitkeep", "")
        _write(root / "80_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-09-21"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "10_Daily" / f"{branch}.md"
        # 既に「更新ノートなし」の最終状態で作成しておき、差分が出ないようにする
        content = _DAILY_NOTE_TEMPLATE.format(date=branch).replace(
            "（`/close` 実行時に自動更新される）", "- （本日の更新ノートなし）"
        )
        _write(daily_note, content)
        _commit_all(root, "add daily note")

        result = _run_close_day(root)

        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert "updated_notes" not in payload
        assert not payload["committed"]
        assert not payload["pushed"]
        assert payload["branch_deleted"]


def test_UPDATED_NOTESマーカーは変更されずupdated_notesキーも出力されない():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "10_Daily" / ".gitkeep", "")
        _write(root / "80_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-10-02"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "10_Daily" / f"{branch}.md"
        arbitrary_marker_content = "- 任意の既存内容（close_day.pyでは変更されないはず）"
        content = _DAILY_NOTE_TEMPLATE.format(date=branch).replace(
            "（`/close` 実行時に自動更新される）", arbitrary_marker_content
        )
        _write(daily_note, content)
        _commit_all(root, "add daily note")

        # 更新ノートとなるファイルを追加する
        # (従来のclose_day.pyならマーカーが上書きされていたはず)
        _write(root / "20_Notes" / "Alpha.md", "alpha content")

        result = _run_close_day(root)

        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert "updated_notes" not in payload
        assert payload["committed"]

        _run_git(["checkout", "main"], cwd=root)
        merged = (root / "10_Daily" / f"{branch}.md").read_text(encoding="utf-8")
        assert arbitrary_marker_content in merged


def test_mainとHEADが一致していれば_already_closed():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "10_Daily" / ".gitkeep", "")
        _write(root / "80_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-09-23"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "10_Daily" / f"{branch}.md"
        content = _DAILY_NOTE_TEMPLATE.format(date=branch).replace(
            "（`/close` 実行時に自動更新される）", "- （本日の更新ノートなし）"
        )
        _write(daily_note, content)
        _commit_all(root, "add daily note")

        # 事前にclose済み(ff-onlyマージ済み)の状態を作る
        _run_git(["checkout", "main"], cwd=root)
        _run_git(["merge", "--ff-only", branch], cwd=root)
        _run_git(["checkout", branch], cwd=root)

        result = _run_close_day(root)

        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload == {"status": "already_closed"}


def test_mainが分岐している場合はff_onlyマージに失敗する():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "10_Daily" / ".gitkeep", "")
        _write(root / "80_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-09-24"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "10_Daily" / f"{branch}.md"
        content = _DAILY_NOTE_TEMPLATE.format(date=branch).replace(
            "（`/close` 実行時に自動更新される）", "- （本日の更新ノートなし）"
        )
        _write(daily_note, content)
        _commit_all(root, "add daily note")

        # main を別途進め、分岐させる(ff-onlyマージ不可能な状態にする)
        _run_git(["checkout", "main"], cwd=root)
        _write(root / "main_only.md", "main only change")
        _commit_all(root, "main diverges")
        _run_git(["checkout", branch], cwd=root)

        result = _run_close_day(root)

        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert payload["status"] == "merge_failed"
        assert "detail" in payload
        assert payload["detail"]


def _task_frontmatter(*, created_date="", start_date="", due_date="", status="1_todo"):
    """タスクノートのfrontmatterテキストを組み立てるテスト用ヘルパー。"""
    return (
        "---\n"
        "type: task\n"
        f"created_date: {created_date}\n"
        f"start_date: {start_date}\n"
        f"due_date: {due_date}\n"
        f"status: {status}\n"
        "---\n"
        "body\n"
    )


def test_scan_task_review_targets_条件1_created_dateが本日かつstart_date未設定():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        task_path = vault_root / "20_Projects" / "ProjX" / "Tasks" / "TaskA.md"
        _write(task_path, _task_frontmatter(created_date="2026-09-23", start_date=""))

        targets = close_day._scan_task_review_targets(vault_root, "2026-09-23")

        assert targets == [{"note_path": str(task_path), "title": "TaskA"}]


def test_scan_task_review_targets_条件2_start_dateが本日かつstatusが1_todo():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        task_path = vault_root / "20_Projects" / "ProjX" / "Tasks" / "TaskB.md"
        _write(
            task_path,
            _task_frontmatter(
                created_date="2026-09-20", start_date="2026-09-23", status="1_todo"
            ),
        )

        targets = close_day._scan_task_review_targets(vault_root, "2026-09-23")

        assert [t["title"] for t in targets] == ["TaskB"]


def test_scan_task_review_targets_条件2_start_dateが本日でもstatusが3_pendingなら対象外():
    """3_pendingは意図的な保留状態であり、1_todo（単純な未着手忘れ）とは異なるため対象外とする。"""
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        task_path = vault_root / "20_Projects" / "ProjX" / "Tasks" / "TaskB2.md"
        _write(
            task_path,
            _task_frontmatter(
                created_date="2026-09-20", start_date="2026-09-23", status="3_pending"
            ),
        )

        targets = close_day._scan_task_review_targets(vault_root, "2026-09-23")

        assert targets == []


def test_scan_task_review_targets_条件3_due_dateが本日かつstatusが未完了():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        task_path = vault_root / "20_Projects" / "ProjX" / "Tasks" / "TaskC.md"
        _write(
            task_path,
            _task_frontmatter(
                created_date="2026-09-10",
                start_date="2026-09-15",
                due_date="2026-09-23",
                status="2_doing",
            ),
        )

        targets = close_day._scan_task_review_targets(vault_root, "2026-09-23")

        assert [t["title"] for t in targets] == ["TaskC"]


@pytest.mark.parametrize("status", ["4_done", "5_cancel"])
def test_scan_task_review_targets_due_dateが本日でも完了済みなら対象外(status):
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        task_path = vault_root / "20_Projects" / "ProjX" / "Tasks" / "TaskD.md"
        _write(
            task_path,
            _task_frontmatter(
                created_date="2026-09-10",
                start_date="2026-09-15",
                due_date="2026-09-23",
                status=status,
            ),
        )

        targets = close_day._scan_task_review_targets(vault_root, "2026-09-23")

        assert targets == []


def test_scan_task_review_targets_いずれの条件にも該当しなければ対象外():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        task_path = vault_root / "20_Projects" / "ProjX" / "Tasks" / "TaskE.md"
        _write(
            task_path,
            _task_frontmatter(
                created_date="2026-09-10",
                start_date="2026-09-15",
                due_date="2026-09-30",
                status="2_doing",
            ),
        )

        targets = close_day._scan_task_review_targets(vault_root, "2026-09-23")

        assert targets == []


def test_scan_task_review_targets_typeがtask以外は対象外():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        _write(
            vault_root / "20_Projects" / "ProjX" / "Tasks" / "NotATask.md",
            "---\ntype: project\ncreated_date: 2026-09-23\nstart_date:\n---\nbody\n",
        )

        targets = close_day._scan_task_review_targets(vault_root, "2026-09-23")

        assert targets == []


def test_scan_task_review_targets_30_Areas_Tasks配下も走査対象():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        task_path = vault_root / "30_Areas" / "Tasks" / "TaskF.md"
        _write(task_path, _task_frontmatter(created_date="2026-09-23", start_date=""))

        targets = close_day._scan_task_review_targets(vault_root, "2026-09-23")

        assert [t["title"] for t in targets] == ["TaskF"]


def test_scan_task_review_targets_複数該当はtitle昇順ソート():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        _write(
            vault_root / "20_Projects" / "ProjX" / "Tasks" / "Zeta.md",
            _task_frontmatter(created_date="2026-09-23", start_date=""),
        )
        _write(
            vault_root / "20_Projects" / "ProjX" / "Tasks" / "Alpha.md",
            _task_frontmatter(created_date="2026-09-23", start_date=""),
        )

        targets = close_day._scan_task_review_targets(vault_root, "2026-09-23")

        assert [t["title"] for t in targets] == ["Alpha", "Zeta"]


def test_main_見直し対象タスクが無ければ従来通り後続処理に進む():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "10_Daily" / ".gitkeep", "")
        _write(root / "80_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-09-30"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "10_Daily" / f"{branch}.md"
        content = _DAILY_NOTE_TEMPLATE.format(date=branch).replace(
            "（`/close` 実行時に自動更新される）", "- （本日の更新ノートなし）"
        )
        _write(daily_note, content)
        # どの条件にも該当しないタスクノート
        _write(
            root / "20_Projects" / "ProjX" / "Tasks" / "Unrelated.md",
            _task_frontmatter(
                created_date="2026-09-10",
                start_date="2026-09-15",
                due_date="2026-09-29",
                status="2_doing",
            ),
        )
        _commit_all(root, "add daily note and task")

        result = _run_close_day(root)

        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"


def test_main_タスク見直し対象があれば中断しコミットしない():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "10_Daily" / ".gitkeep", "")
        _write(root / "80_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-10-01"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "10_Daily" / f"{branch}.md"
        _write(daily_note, _DAILY_NOTE_TEMPLATE.format(date=branch))
        task_path = root / "20_Projects" / "ProjX" / "Tasks" / "NeedsReview.md"
        _write(task_path, _task_frontmatter(created_date=branch, start_date=""))

        head_before = _run_git(["rev-parse", "HEAD"], cwd=root)

        result = _run_close_day(root)

        assert result.returncode == 1, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload == {
            "status": "needs_task_review",
            "tasks": [{"note_path": str(task_path), "title": "NeedsReview"}],
        }

        # コミット・マージ等の副作用が発生していないことを確認する
        head_after = _run_git(["rev-parse", "HEAD"], cwd=root)
        assert head_after == head_before
        assert _run_git(["status", "--porcelain"], cwd=root) != ""
        remaining_branches = _run_git(["branch", "--list", branch], cwd=root)
        assert branch in remaining_branches


def test_post_merge_diff_作業ツリーがクリーンなら空文字列():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "10_Daily" / ".gitkeep", "")
        _commit_all(root, "initial commit")

        result = close_day._post_merge_diff(root)

        assert result == ""


def test_post_merge_diff_差分があれば非空のporcelain文字列():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "10_Daily" / ".gitkeep", "")
        _commit_all(root, "initial commit")
        _write(root / "10_Daily" / "stray.md", "stray content")

        result = close_day._post_merge_diff(root)

        assert result.strip() != ""
        assert "stray.md" in result


def test_main_マージ直後に不一致があればpost_merge_mismatchでブランチ削除もpushも行わない(monkeypatch, capsys):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "10_Daily" / ".gitkeep", "")
        _write(root / "80_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-10-04"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "10_Daily" / f"{branch}.md"
        content = _DAILY_NOTE_TEMPLATE.format(date=branch).replace(
            "（`/close` 実行時に自動更新される）", "- （本日の更新ノートなし）"
        )
        _write(daily_note, content)
        _commit_all(root, "add daily note")

        # マージ自体は成功させ、直後の整合性チェックだけ強制的に不一致にする
        monkeypatch.setattr(
            close_day,
            "_post_merge_diff",
            lambda vault_root: "?? unexpected_file.md\n",
        )

        exit_code = close_day.main(["--vault-root", str(root)])

        assert exit_code == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "post_merge_mismatch"
        assert "unexpected_file.md" in payload["detail"]
        assert "pushed" not in payload
        assert "branch_deleted" not in payload

        # ブランチが削除されずに残っていることを確認する
        remaining_branches = _run_git(["branch", "--list", branch], cwd=root)
        assert branch in remaining_branches


