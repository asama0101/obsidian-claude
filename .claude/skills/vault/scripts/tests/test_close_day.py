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
        _write(root / "00_Daily" / ".gitkeep", "")
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
        _write(root / "00_Daily" / ".gitkeep", "")
        _write(root / "70_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-09-21"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "00_Daily" / f"{branch}.md"
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
        assert payload["updated_notes"] == []
        assert not payload["committed"]
        assert not payload["pushed"]
        assert payload["branch_deleted"]


def test_更新ノート一覧の反映と除外対象の除外():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "00_Daily" / ".gitkeep", "")
        _write(root / "70_Templates" / "Daily_Template.md", "template original")
        _commit_all(root, "initial commit")

        branch = "2026-09-22"
        _run_git(["checkout", "-b", branch], cwd=root)

        daily_note = root / "00_Daily" / f"{branch}.md"
        _write(daily_note, _DAILY_NOTE_TEMPLATE.format(date=branch))
        # コミット済みの更新ノート
        _write(root / "20_Notes" / "Alpha.md", "alpha content")
        _commit_all(root, "daily work committed part")

        # 未コミットの更新ノート(新規/untracked)
        _write(root / "20_Notes" / "Beta.md", "beta content")
        # 除外対象: テンプレート配下の変更
        _write(root / "70_Templates" / "Daily_Template.md", "template modified")
        # 除外対象: .claude 配下
        _write(root / ".claude" / "scratch.md", "scratch")
        # 除外対象: .md 以外
        _write(root / "images" / "photo.png", "binary-ish")

        result = _run_close_day(root)

        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["updated_notes"] == ["Alpha", "Beta"]
        assert payload["committed"]
        assert payload["branch_deleted"]

        # main にマージ後の内容を確認する
        _run_git(["checkout", "main"], cwd=root)
        merged_note_text = (root / "00_Daily" / f"{branch}.md").read_text(encoding="utf-8")
        assert "**other**" in merged_note_text
        assert "- [[Alpha]]" in merged_note_text
        assert "- [[Beta]]" in merged_note_text
        assert "scratch" not in merged_note_text

        # 当日ブランチ自体が削除されていることを確認する
        remaining_branches = _run_git(["branch", "--list", branch], cwd=root)
        assert remaining_branches == ""


def test_gitがクォートするファイル名も一覧に含まれる():
    # スペースと括弧を含むファイル名は core.quotepath=false でも
    # git status --porcelain がダブルクォートで囲むことがある
    # (実データ検証で発見した実際のバグの再現)。
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "00_Daily" / ".gitkeep", "")
        _write(root / "70_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-09-25"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "00_Daily" / f"{branch}.md"
        _write(daily_note, _DAILY_NOTE_TEMPLATE.format(date=branch))
        _write(root / "20_Areas" / "Knowledge" / "status --check(x).md", "content")

        result = _run_close_day(root)

        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["updated_notes"] == ["status --check(x)"]


def test_全く新規のディレクトリ内のファイルも個別に一覧化される():
    # 10_Projects/<新規プロジェクト>/Tasks/ のように、追跡済み
    # ファイルが1つも無い全く新規のディレクトリにノートを作成した
    # 場合、gitのデフォルト(untracked-files=normal)だと
    # ディレクトリ名1行に集約され、ファイルが一覧から漏れる
    # (実データ検証で発見した実際のバグの再現)。
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "00_Daily" / ".gitkeep", "")
        _write(root / "70_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-09-26"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "00_Daily" / f"{branch}.md"
        _write(daily_note, _DAILY_NOTE_TEMPLATE.format(date=branch))
        _write(
            root / "10_Projects" / "NewProject" / "Tasks" / "FirstTask.md",
            "task content",
        )

        result = _run_close_day(root)

        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["updated_notes"] == ["FirstTask"]


def test_mainとHEADが一致していれば_already_closed():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "00_Daily" / ".gitkeep", "")
        _write(root / "70_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-09-23"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "00_Daily" / f"{branch}.md"
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
        _write(root / "00_Daily" / ".gitkeep", "")
        _write(root / "70_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-09-24"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "00_Daily" / f"{branch}.md"
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


def test_normalize_meeting_seriesはmeetingに統合される():
    assert close_day._normalize_note_type("meeting_series") == "meeting"


@pytest.mark.parametrize("known", ["project", "meeting", "task", "knowhow", "webclip"])
def test_normalize_既知typeはそのまま(known):
    assert close_day._normalize_note_type(known) == known


def test_normalize_未知typeはotherになる():
    assert close_day._normalize_note_type("unknown_type") == "other"


def test_normalize_Noneはotherになる():
    assert close_day._normalize_note_type(None) == "other"


def test_read_note_type_frontmatterのtype値を取得する():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "note.md"
        path.write_text("---\ntype: project\n---\nbody", encoding="utf-8")
        assert close_day._read_note_type(path) == "project"


def test_read_note_type_typeキーが無ければNone():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "note.md"
        path.write_text("---\ntags:\n  - x\n---\nbody", encoding="utf-8")
        assert close_day._read_note_type(path) is None


def test_read_note_type_frontmatterが無ければNone():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "note.md"
        path.write_text("plain body without frontmatter", encoding="utf-8")
        assert close_day._read_note_type(path) is None


def test_read_note_type_ファイルが存在しなければNone():
    missing_path = Path(tempfile.gettempdir()) / "does_not_exist_close_day_test.md"
    assert not missing_path.exists()
    assert close_day._read_note_type(missing_path) is None


def test_stemとフルパスのtupleリストをソート済みで返す():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        paths = {
            "20_Notes/Beta.md",
            "20_Notes/Alpha.md",
            "70_Templates/x.md",
            "images/a.png",
            "00_Daily/2026-09-22.md",
        }
        entries = close_day._filter_updated_notes(paths, "2026-09-22", vault_root)
        assert entries == [
            ("Alpha", vault_root / "20_Notes/Alpha.md"),
            ("Beta", vault_root / "20_Notes/Beta.md"),
        ]


def test_type別に固定順でグルーピングされmeeting_seriesはmeetingへ統合される():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "00_Daily" / ".gitkeep", "")
        _write(root / "70_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-09-28"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "00_Daily" / f"{branch}.md"
        _write(daily_note, _DAILY_NOTE_TEMPLATE.format(date=branch))

        _write(root / "10_Projects" / "Zeta.md", "---\ntype: project\n---\nbody")
        _write(
            root / "10_Projects" / "Meetings" / "Alpha.md",
            "---\ntype: meeting\n---\nbody",
        )
        _write(
            root / "10_Projects" / "Meetings" / "Weekly.md",
            "---\ntype: meeting_series\n---\nbody",
        )
        _write(root / "40_Tasks" / "DoThing.md", "---\ntype: task\n---\nbody")

        result = _run_close_day(root)

        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert sorted(payload["updated_notes"]) == ["Alpha", "DoThing", "Weekly", "Zeta"]

        _run_git(["checkout", "main"], cwd=root)
        merged = (root / "00_Daily" / f"{branch}.md").read_text(encoding="utf-8")

        project_idx = merged.index("**project**")
        meeting_idx = merged.index("**meeting**")
        task_idx = merged.index("**task**")
        assert project_idx < meeting_idx
        assert meeting_idx < task_idx
        assert "- [[Zeta]]" in merged
        assert "- [[Alpha]]" in merged
        assert "- [[Weekly]]" in merged
        assert "- [[DoThing]]" in merged
        assert merged.count("**meeting**") == 1
        assert "**meeting_series**" not in merged
        assert "**knowhow**" not in merged
        assert "**webclip**" not in merged
        assert "**other**" not in merged


def test_単一typeのみ更新時はそのグループのみ表示される():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "00_Daily" / ".gitkeep", "")
        _write(root / "70_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-09-29"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "00_Daily" / f"{branch}.md"
        _write(daily_note, _DAILY_NOTE_TEMPLATE.format(date=branch))
        _write(root / "30_Knowhow" / "Tip.md", "---\ntype: knowhow\n---\nbody")

        result = _run_close_day(root)

        assert result.returncode == 0, result.stdout + result.stderr
        _run_git(["checkout", "main"], cwd=root)
        merged = (root / "00_Daily" / f"{branch}.md").read_text(encoding="utf-8")
        assert "**knowhow**" in merged
        assert "- [[Tip]]" in merged
        for absent in ("**project**", "**meeting**", "**task**", "**webclip**", "**other**"):
            assert absent not in merged


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
        task_path = vault_root / "10_Projects" / "ProjX" / "Tasks" / "TaskA.md"
        _write(task_path, _task_frontmatter(created_date="2026-09-23", start_date=""))

        targets = close_day._scan_task_review_targets(vault_root, "2026-09-23")

        assert targets == [{"note_path": str(task_path), "title": "TaskA"}]


def test_scan_task_review_targets_条件2_start_dateが本日かつstatusが1_todo():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        task_path = vault_root / "10_Projects" / "ProjX" / "Tasks" / "TaskB.md"
        _write(
            task_path,
            _task_frontmatter(
                created_date="2026-09-20", start_date="2026-09-23", status="1_todo"
            ),
        )

        targets = close_day._scan_task_review_targets(vault_root, "2026-09-23")

        assert [t["title"] for t in targets] == ["TaskB"]


def test_scan_task_review_targets_条件3_due_dateが本日かつstatusが未完了():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        task_path = vault_root / "10_Projects" / "ProjX" / "Tasks" / "TaskC.md"
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
        task_path = vault_root / "10_Projects" / "ProjX" / "Tasks" / "TaskD.md"
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
        task_path = vault_root / "10_Projects" / "ProjX" / "Tasks" / "TaskE.md"
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
            vault_root / "10_Projects" / "ProjX" / "Tasks" / "NotATask.md",
            "---\ntype: project\ncreated_date: 2026-09-23\nstart_date:\n---\nbody\n",
        )

        targets = close_day._scan_task_review_targets(vault_root, "2026-09-23")

        assert targets == []


def test_scan_task_review_targets_20_Areas_Tasks配下も走査対象():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        task_path = vault_root / "20_Areas" / "Tasks" / "TaskF.md"
        _write(task_path, _task_frontmatter(created_date="2026-09-23", start_date=""))

        targets = close_day._scan_task_review_targets(vault_root, "2026-09-23")

        assert [t["title"] for t in targets] == ["TaskF"]


def test_scan_task_review_targets_複数該当はtitle昇順ソート():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        _write(
            vault_root / "10_Projects" / "ProjX" / "Tasks" / "Zeta.md",
            _task_frontmatter(created_date="2026-09-23", start_date=""),
        )
        _write(
            vault_root / "10_Projects" / "ProjX" / "Tasks" / "Alpha.md",
            _task_frontmatter(created_date="2026-09-23", start_date=""),
        )

        targets = close_day._scan_task_review_targets(vault_root, "2026-09-23")

        assert [t["title"] for t in targets] == ["Alpha", "Zeta"]


def test_main_見直し対象タスクが無ければ従来通り後続処理に進む():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "00_Daily" / ".gitkeep", "")
        _write(root / "70_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-09-30"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "00_Daily" / f"{branch}.md"
        content = _DAILY_NOTE_TEMPLATE.format(date=branch).replace(
            "（`/close` 実行時に自動更新される）", "- （本日の更新ノートなし）"
        )
        _write(daily_note, content)
        # どの条件にも該当しないタスクノート
        _write(
            root / "10_Projects" / "ProjX" / "Tasks" / "Unrelated.md",
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
        _write(root / "00_Daily" / ".gitkeep", "")
        _write(root / "70_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-10-01"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "00_Daily" / f"{branch}.md"
        _write(daily_note, _DAILY_NOTE_TEMPLATE.format(date=branch))
        task_path = root / "10_Projects" / "ProjX" / "Tasks" / "NeedsReview.md"
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


def test_未知typeと削除済みファイルはotherグループに入る():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "00_Daily" / ".gitkeep", "")
        _write(root / "70_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-09-27"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "00_Daily" / f"{branch}.md"
        _write(daily_note, _DAILY_NOTE_TEMPLATE.format(date=branch))

        # 未知のtype値を持つノート
        _write(root / "20_Notes" / "Mystery.md", "---\ntype: mystery\n---\nbody")

        # 追跡済みファイルを削除する
        # (git statusでは'D'として検出されるが実体はもう無い)
        deleted_note = root / "20_Notes" / "Ghost.md"
        _write(deleted_note, "---\ntype: project\n---\nbody")
        _commit_all(root, "add ghost note")
        deleted_note.unlink()

        result = _run_close_day(root)

        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert sorted(payload["updated_notes"]) == ["Ghost", "Mystery"]

        _run_git(["checkout", "main"], cwd=root)
        merged = (root / "00_Daily" / f"{branch}.md").read_text(encoding="utf-8")
        assert "**other**" in merged
        assert "- [[Mystery]]" in merged
        assert "- [[Ghost]]" in merged
        assert "**project**" not in merged
