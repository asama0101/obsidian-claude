"""close_day.py のユニットテスト。

実際の一時gitリポジトリ(tempfile.TemporaryDirectory)を構築し、
close_day.py をサブプロセスとして実行して検証する。
標準ライブラリの unittest のみを使用する。
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
_CLOSE_DAY = _SCRIPTS_DIR / "close_day.py"

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


class NotOnDailyBranchTest(unittest.TestCase):
    def test_日付形式でないブランチではerrorを返す(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            _write(root / "00_Daily" / ".gitkeep", "")
            _commit_all(root, "initial commit")
            # main ブランチのまま(日付形式ではない)実行する

            result = _run_close_day(root)

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertEqual(payload, {"status": "error", "reason": "not_on_daily_branch"})


class NoChangesTest(unittest.TestCase):
    def test_変更が無い場合はコミットをスキップする(self):
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

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["updated_notes"], [])
            self.assertFalse(payload["committed"])
            self.assertFalse(payload["pushed"])


class UpdatedNotesBlockTest(unittest.TestCase):
    def test_更新ノート一覧の反映と除外対象の除外(self):
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

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["updated_notes"], ["Alpha", "Beta"])
            self.assertTrue(payload["committed"])

            # main にマージ後の内容を確認する
            _run_git(["checkout", "main"], cwd=root)
            merged_note_text = (root / "00_Daily" / f"{branch}.md").read_text(encoding="utf-8")
            self.assertIn("- [[Alpha]]", merged_note_text)
            self.assertIn("- [[Beta]]", merged_note_text)
            self.assertNotIn("scratch", merged_note_text)


class QuotedPathTest(unittest.TestCase):
    def test_gitがクォートするファイル名も一覧に含まれる(self):
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

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["updated_notes"], ["status --check(x)"])


class NewProjectDirectoryTest(unittest.TestCase):
    def test_全く新規のディレクトリ内のファイルも個別に一覧化される(self):
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

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["updated_notes"], ["FirstTask"])


class AlreadyClosedTest(unittest.TestCase):
    def test_mainとHEADが一致していれば_already_closed(self):
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

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload, {"status": "already_closed"})


class MergeFailedTest(unittest.TestCase):
    def test_mainが分岐している場合はff_onlyマージに失敗する(self):
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

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "merge_failed")
            self.assertIn("detail", payload)
            self.assertTrue(payload["detail"])


if __name__ == "__main__":
    unittest.main()
