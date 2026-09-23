"""Obsidian Vault から Claude Code プラグインの設定をリポジトリへミラーする個人運用ツール。

これはシグネチャのみのスタブ実装であり、二段階RED（pytest collectはできるが
対象assertでAssertionErrorにより失敗する状態）を示すためのコミット用ファイル。
実装はこのすぐ後のコミットで追加する。
"""

from pathlib import Path

# 変更時はここを直接書き換える
VAULT_ROOT = Path(r"C:\Users\sioay\OneDrive\vault")
REPO_ROOT = Path(__file__).resolve().parent

# .claude/配下でリポジトリへミラーしないランタイム状態（このマシン限定の状態・ロック・キャッシュ）
CLAUDE_SKIP_NAMES = frozenset(
    {
        ".venv",
        "__pycache__",
        ".pytest_cache",
        "scheduled_tasks.lock",
        "scheduled_tasks.json",
        "routines",
        "worktrees",
        "checkpoints",
        "mailbox",
        "agent-registry.json",
        "agent-memory-local",
        "first-run",
        "assistant-daemon-state.json",
    }
)


def mirror_dir(
    src: Path,
    dst: Path,
    *,
    skip_names: frozenset[str] = frozenset(),
    structure_only: bool = False,
    dry_run: bool = False,
) -> list[str]:
    """未実装のスタブ。常に空リストを返す。"""
    return []


def copy_file(src: Path, dst: Path, *, base_dir: Path, dry_run: bool) -> list[str]:
    """未実装のスタブ。常に空リストを返す。"""
    return []


def run(dry_run: bool) -> list[str]:
    """未実装のスタブ。常に空リストを返す。"""
    return []
