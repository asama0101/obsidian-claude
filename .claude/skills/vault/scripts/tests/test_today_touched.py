"""today_touched.py のユニットテスト。

close_day.py から移設したロジック(更新ノート検出・グルーピング)を、
today_touched.py 単体として検証する。close_day.py は一切実行しない。
実際の一時gitリポジトリ(tempfile.TemporaryDirectory)を構築し、
today_touched.py をサブプロセスとして実行して検証する。
pytest（`.claude/skills/vault/scripts/.venv/`のvenv限定の開発依存）を使用する。
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import today_touched  # noqa: E402

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
_TODAY_TOUCHED = _SCRIPTS_DIR / "today_touched.py"

_DAILY_NOTE_TEMPLATE = (
    "---\n"
    "tags:\n"
    "  - daily\n"
    "---\n"
    "# {date}\n"
    "\n"
    "## 🔗 本日作成・更新したノート\n"
    "<!-- UPDATED_NOTES_START -->\n"
    "（実行時に自動更新される）\n"
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


def _run_today_touched(vault_root: Path):
    return subprocess.run(
        [sys.executable, str(_TODAY_TOUCHED), "--vault-root", str(vault_root)],
        cwd=str(vault_root),
        capture_output=True,
        text=True,
    )


# --- _read_note_type (単体テスト) ---


def test_read_note_type_typeキーが無ければNone():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "note.md"
        path.write_text("---\ntags:\n  - x\n---\nbody", encoding="utf-8")
        assert today_touched._read_note_type(path) is None


def test_read_note_type_frontmatterが無ければNone():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "note.md"
        path.write_text("plain body without frontmatter", encoding="utf-8")
        assert today_touched._read_note_type(path) is None


# --- _filter_updated_notes (単体テスト) ---


def test_stemとフルパスのtupleリストをソート済みで返す():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        _write(vault_root / "20_Notes" / "Beta.md", "beta")
        _write(vault_root / "20_Notes" / "Alpha.md", "alpha")
        paths = {
            "20_Notes/Beta.md",
            "20_Notes/Alpha.md",
            "80_Templates/x.md",
            "images/a.png",
            "10_Daily/2026-09-22.md",
        }
        entries = today_touched._filter_updated_notes(paths, "2026-09-22", vault_root)
        assert entries == [
            ("Alpha", vault_root / "20_Notes/Alpha.md"),
            ("Beta", vault_root / "20_Notes/Beta.md"),
        ]


def test_claude配下も除外される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        _write(vault_root / "20_Notes" / "Alpha.md", "alpha")
        paths = {"20_Notes/Alpha.md", ".claude/scratch.md"}
        entries = today_touched._filter_updated_notes(paths, "2026-09-22", vault_root)
        assert entries == [("Alpha", vault_root / "20_Notes/Alpha.md")]


def test_実在しないファイルは除外される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        # 実ファイルを作成しない(削除済みノートを想定)
        paths = {"20_Notes/Ghost.md"}
        entries = today_touched._filter_updated_notes(paths, "2026-09-22", vault_root)
        assert entries == []


# --- サブプロセス統合テスト ---


def test_日付形式でないブランチではerrorを返し何も書き込まない():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "10_Daily" / ".gitkeep", "")
        _commit_all(root, "initial commit")
        # main ブランチのまま(日付形式ではない)実行する

        result = _run_today_touched(root)

        assert result.returncode == 1
        payload = json.loads(result.stdout)
        assert payload == {"status": "error", "reason": "not_on_daily_branch"}
        # デイリーノート自体が存在しないので、書き込みが起きていれば例外で
        # 検出できるはずだが、ここでは10_Dailyに何も追加されていないことも確認する
        assert list((root / "10_Daily").iterdir()) == [root / "10_Daily" / ".gitkeep"]


def test_更新ノート一覧の反映と除外対象の除外():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "10_Daily" / ".gitkeep", "")
        _write(root / "80_Templates" / "Daily_Template.md", "template original")
        _commit_all(root, "initial commit")

        branch = "2026-09-22"
        _run_git(["checkout", "-b", branch], cwd=root)

        daily_note = root / "10_Daily" / f"{branch}.md"
        _write(daily_note, _DAILY_NOTE_TEMPLATE.format(date=branch))
        # コミット済みの更新ノート
        _write(root / "20_Notes" / "Alpha.md", "alpha content")
        _commit_all(root, "daily work committed part")

        # 未コミットの更新ノート(新規/untracked)
        _write(root / "20_Notes" / "Beta.md", "beta content")
        # 除外対象: テンプレート配下の変更
        _write(root / "80_Templates" / "Daily_Template.md", "template modified")
        # 除外対象: .claude 配下
        _write(root / ".claude" / "scratch.md", "scratch")
        # 除外対象: .md 以外
        _write(root / "images" / "photo.png", "binary-ish")

        result = _run_today_touched(root)

        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["updated_notes"] == ["Alpha", "Beta"]

        merged_note_text = daily_note.read_text(encoding="utf-8")
        assert "**other**" in merged_note_text
        assert "- [[Alpha]]" in merged_note_text
        assert "- [[Beta]]" in merged_note_text
        assert "scratch" not in merged_note_text

        # today_touched.pyはコミット・マージを一切行わない
        assert _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root) == branch
        status_output = _run_git(["status", "--porcelain"], cwd=root)
        assert status_output != ""


def test_gitがクォートするファイル名も一覧に含まれる():
    # スペースと括弧を含むファイル名は core.quotepath=false でも
    # git status --porcelain がダブルクォートで囲むことがある
    # (実データ検証で発見した実際のバグの再現)。
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "10_Daily" / ".gitkeep", "")
        _write(root / "80_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-09-25"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "10_Daily" / f"{branch}.md"
        _write(daily_note, _DAILY_NOTE_TEMPLATE.format(date=branch))
        _write(root / "40_Resources" / "Knowledge" / "status --check(x).md", "content")

        result = _run_today_touched(root)

        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["updated_notes"] == ["status --check(x)"]


def test_type別に固定順でグルーピングされmeeting_seriesはmeetingへ統合される():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "10_Daily" / ".gitkeep", "")
        _write(root / "80_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-09-28"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "10_Daily" / f"{branch}.md"
        _write(daily_note, _DAILY_NOTE_TEMPLATE.format(date=branch))

        _write(root / "20_Projects" / "Zeta.md", "---\ntype: project\n---\nbody")
        _write(
            root / "20_Projects" / "Meetings" / "Alpha.md",
            "---\ntype: meeting\n---\nbody",
        )
        _write(
            root / "20_Projects" / "Meetings" / "Weekly.md",
            "---\ntype: meeting_series\n---\nbody",
        )
        _write(root / "40_Tasks" / "DoThing.md", "---\ntype: task\n---\nbody")

        result = _run_today_touched(root)

        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert sorted(payload["updated_notes"]) == ["Alpha", "DoThing", "Weekly", "Zeta"]

        merged = daily_note.read_text(encoding="utf-8")
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
        _write(root / "10_Daily" / ".gitkeep", "")
        _write(root / "80_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-09-29"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "10_Daily" / f"{branch}.md"
        _write(daily_note, _DAILY_NOTE_TEMPLATE.format(date=branch))
        _write(root / "30_Knowhow" / "Tip.md", "---\ntype: knowhow\n---\nbody")

        result = _run_today_touched(root)

        assert result.returncode == 0, result.stdout + result.stderr
        merged = daily_note.read_text(encoding="utf-8")
        assert "**knowhow**" in merged
        assert "- [[Tip]]" in merged
        for absent in ("**project**", "**meeting**", "**task**", "**webclip**", "**other**"):
            assert absent not in merged


def test_未知typeはotherグループに入る():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "10_Daily" / ".gitkeep", "")
        _write(root / "80_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-09-27"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "10_Daily" / f"{branch}.md"
        _write(daily_note, _DAILY_NOTE_TEMPLATE.format(date=branch))

        # 未知のtype値を持つノート
        _write(root / "20_Notes" / "Mystery.md", "---\ntype: mystery\n---\nbody")

        result = _run_today_touched(root)

        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["updated_notes"] == ["Mystery"]

        merged = daily_note.read_text(encoding="utf-8")
        assert "**other**" in merged
        assert "- [[Mystery]]" in merged
        assert "**project**" not in merged


def test_削除済みファイルは一覧から除外される():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "10_Daily" / ".gitkeep", "")
        _write(root / "80_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-09-28"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "10_Daily" / f"{branch}.md"
        _write(daily_note, _DAILY_NOTE_TEMPLATE.format(date=branch))

        # 追跡済みファイルを削除する
        # (git statusでは'D'として検出されるが実体はもう無い)
        deleted_note = root / "20_Notes" / "Ghost.md"
        _write(deleted_note, "---\ntype: project\n---\nbody")
        _commit_all(root, "add ghost note")
        deleted_note.unlink()

        result = _run_today_touched(root)

        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert "Ghost" not in payload["updated_notes"]

        merged = daily_note.read_text(encoding="utf-8")
        assert "[[Ghost]]" not in merged


def test_途中でmainがff_onlyマージされ差分基準が動いても以前の記録を上書きしない():
    """close_day.pyのff-onlyマージでmainが当日ブランチに追いつくと、
    merge-base(main, HEAD)が前進し、次回実行時の差分は追いついた地点以降
    しか見えなくなる。これにより以前記録済みの更新ノートがマーカーブロック
    再生成で消えてしまう実データ上のバグ（2026-09-26に実際発生）を再現し、
    和集合方式で解消されていることを確認する。
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "10_Daily" / ".gitkeep", "")
        _write(root / "80_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-09-26"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "10_Daily" / f"{branch}.md"
        _write(daily_note, _DAILY_NOTE_TEMPLATE.format(date=branch))

        # 午前の更新
        _write(root / "20_Notes" / "NoteA.md", "---\ntype: project\n---\nbody")
        _commit_all(root, "morning work")

        result1 = _run_today_touched(root)
        assert result1.returncode == 0, result1.stdout + result1.stderr
        payload1 = json.loads(result1.stdout)
        assert payload1["updated_notes"] == ["NoteA"]
        _commit_all(root, "today-touched marker update (1st)")

        # close_day.py相当: main へ ff-only マージ(mainが当日ブランチに追いつく)
        _run_git(["checkout", "main"], cwd=root)
        _run_git(["merge", "--ff-only", branch], cwd=root)
        _run_git(["checkout", branch], cwd=root)

        # 午後の更新(mainが追いついた後の新規コミット)
        _write(root / "20_Notes" / "NoteB.md", "---\ntype: project\n---\nbody")
        _commit_all(root, "afternoon work")

        result2 = _run_today_touched(root)

        assert result2.returncode == 0, result2.stdout + result2.stderr
        payload2 = json.loads(result2.stdout)
        # 差分基準がafternoon workだけを指していても、以前記録済みのNoteAは
        # 消えず、NoteBと合算されて両方報告される
        assert payload2["updated_notes"] == ["NoteA", "NoteB"]

        merged = daily_note.read_text(encoding="utf-8")
        assert "- [[NoteA]]" in merged
        assert "- [[NoteB]]" in merged


def test_2回連続実行しても結果が同一で冪等():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _init_repo(root)
        _write(root / "10_Daily" / ".gitkeep", "")
        _write(root / "80_Templates" / "Daily_Template.md", "template")
        _commit_all(root, "initial commit")

        branch = "2026-09-30"
        _run_git(["checkout", "-b", branch], cwd=root)
        daily_note = root / "10_Daily" / f"{branch}.md"
        _write(daily_note, _DAILY_NOTE_TEMPLATE.format(date=branch))
        _write(root / "20_Notes" / "Alpha.md", "alpha content")

        result1 = _run_today_touched(root)
        text_after_first = daily_note.read_text(encoding="utf-8")

        result2 = _run_today_touched(root)
        text_after_second = daily_note.read_text(encoding="utf-8")

        assert result1.returncode == result2.returncode == 0
        payload1 = json.loads(result1.stdout)
        payload2 = json.loads(result2.stdout)
        assert payload1 == payload2
        assert text_after_first == text_after_second
