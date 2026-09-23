"""today_start.py のユニットテスト。

一時ディレクトリに git リポジトリを作成し、実際の git コマンドを通して
today スキル本体(today_start.run)の振る舞いを検証する。
"""

import datetime
import sys
import tempfile
from pathlib import Path

# scripts/ ディレクトリを import パスに追加する
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import today_start  # noqa: E402
import vault_lib  # noqa: E402

# 実際の 80_Templates/Daily_Template.md と同内容(テスト用に埋め込む)
TEMPLATE_TEXT = (
    "---\n"
    "tags:\n"
    "  - daily\n"
    "---\n"
    "# {{title}} (<span>{{date:ddd}}</span>)\n"
    "\n"
    "## 📅 本日の議事録\n"
    "![[Meetings.base#Today]]\n"
    "\n"
    "## 📋 本日のタスク\n"
    "![[Tasks.base#Today]]\n"
    "\n"
    "## 📂 アクティブプロジェクト\n"
    "![[Projects.base#Active]]\n"
    "\n"
    "## 🔗 本日作成・更新したノート\n"
    "<!-- UPDATED_NOTES_START -->\n"
    "（`/close` 実行時に自動更新される）\n"
    "<!-- UPDATED_NOTES_END -->\n"
    "\n"
    "---\n"
    "\n"
    "## 📝 メモ\n"
    "\n"
    "### 📌 翌日引き継ぎメモ\n"
    "<!-- CARRYOVER_START -->\n"
    "- [ ] \n"
    "<!-- CARRYOVER_END -->\n"
    "\n"
    "### 💭 本日限りのメモ\n"
    "-\n"
)


def _init_vault(vault_root: Path) -> None:
    """git init 済み・main ブランチ・テンプレート配置済みの Vault を作る。"""
    vault_lib.run_git("init", "-b", "main", cwd=vault_root)
    vault_lib.run_git("config", "user.email", "test@example.com", cwd=vault_root)
    vault_lib.run_git("config", "user.name", "Test", cwd=vault_root)

    (vault_root / "80_Templates").mkdir(parents=True, exist_ok=True)
    (vault_root / "80_Templates" / "Daily_Template.md").write_text(
        TEMPLATE_TEXT, encoding="utf-8"
    )
    (vault_root / "10_Daily").mkdir(parents=True, exist_ok=True)

    (vault_root / "README.md").write_text("init", encoding="utf-8")
    vault_lib.run_git("add", "-A", cwd=vault_root)
    vault_lib.run_git("commit", "-m", "init", cwd=vault_root)


def _current_branch(vault_root: Path) -> str:
    return vault_lib.run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=vault_root)


def test_未マージの過去日ブランチがあるとblockedを返す():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        _init_vault(vault_root)

        # 過去日ブランチを作り、main未マージのコミットを積む
        vault_lib.run_git("checkout", "-b", "2026-01-10", cwd=vault_root)
        (vault_root / "stale.md").write_text("stale work", encoding="utf-8")
        vault_lib.run_git("add", "-A", cwd=vault_root)
        vault_lib.run_git("commit", "-m", "stale work", cwd=vault_root)
        vault_lib.run_git("checkout", "main", cwd=vault_root)

        dt = datetime.datetime(2026, 1, 15, 9, 0)
        result = today_start.run(vault_root, dt=dt)

        assert result["status"] == "blocked"
        assert "2026-01-10" in result["branches"]


def test_当日ブランチが既存ならcheckoutだけする():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        _init_vault(vault_root)

        dt = datetime.datetime(2026, 1, 15, 9, 0)
        today = "2026-01-15"

        # main から当日ブランチを作成済みの状態にしておく(差分なし=main視点でmerged)
        vault_lib.run_git("branch", today, cwd=vault_root)
        vault_lib.run_git("checkout", "main", cwd=vault_root)

        result = today_start.run(vault_root, dt=dt)

        assert result["status"] == "ok"
        assert result["branch"] == "existing"
        assert _current_branch(vault_root) == today


def test_デイリーノートが既存ならスキップしCarryover転記も起きない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        _init_vault(vault_root)

        dt = datetime.datetime(2026, 1, 15, 9, 0)
        today = "2026-01-15"

        existing_content = "# 手動で作成済みのノート\n既存の内容"
        (vault_root / "10_Daily" / f"{today}.md").write_text(
            existing_content, encoding="utf-8"
        )

        result = today_start.run(vault_root, dt=dt)

        assert result["status"] == "ok"
        assert result["daily_note"] == "skipped"
        assert (
            vault_root / "10_Daily" / f"{today}.md"
        ).read_text(encoding="utf-8") == existing_content


def test_前日ノートのCarryoverが転記され元ノートは変更されない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        _init_vault(vault_root)

        dt = datetime.datetime(2026, 1, 15, 9, 0)
        today = "2026-01-15"

        prev_content = TEMPLATE_TEXT.replace("{{title}}", "2026-01-10")
        prev_content = vault_lib.set_marker_block(
            prev_content, "CARRYOVER_START", "CARRYOVER_END", "- [ ] task A"
        )
        prev_path = vault_root / "10_Daily" / "2026-01-10.md"
        prev_path.write_text(prev_content, encoding="utf-8")

        result = today_start.run(vault_root, dt=dt)

        assert result["status"] == "ok"
        assert result["daily_note"] == "created"
        assert result["carryover_source"] == "2026-01-10"

        new_content = (vault_root / "10_Daily" / f"{today}.md").read_text(encoding="utf-8")
        assert (
            vault_lib.get_marker_block(new_content, "CARRYOVER_START", "CARRYOVER_END")
            == "- [ ] task A"
        )

        # 元の前日ノートは一切変更されていないこと
        assert prev_path.read_text(encoding="utf-8") == prev_content


def test_前日ノートが無い場合はCarryoverが空のまま作成される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        _init_vault(vault_root)

        dt = datetime.datetime(2026, 1, 15, 9, 0)
        today = "2026-01-15"

        result = today_start.run(vault_root, dt=dt)

        assert result["status"] == "ok"
        assert result["daily_note"] == "created"
        assert result["carryover_source"] is None

        new_content = (vault_root / "10_Daily" / f"{today}.md").read_text(encoding="utf-8")
        expected_placeholder = vault_lib.get_marker_block(
            TEMPLATE_TEXT, "CARRYOVER_START", "CARRYOVER_END"
        )
        assert (
            vault_lib.get_marker_block(new_content, "CARRYOVER_START", "CARRYOVER_END")
            == expected_placeholder
        )
