"""Obsidian Vault から Claude Code プラグインの設定をリポジトリへミラーする個人運用ツール。

Vault側（Obsidianの実行環境）を正とし、リポジトリ側（Git管理下のこのプロジェクト）を
Vaultの内容に合わせて同期する。git操作（add/commit/push）は一切行わず、
ファイルのコピー・削除のみを行う。

このモジュールは複数タスクに分割して段階的に実装される。このファイル時点では
以下の2カテゴリのみを扱う。
- フルミラー・ディレクトリ（.claude/, 80_Templates/, 82_Bases/, 90_SkillFlows/）
- 単一ファイルコピー（CLAUDE.md, README.md）

`.obsidian/`許可リストミラー・個人ノート構造ミラー・エラー処理・CLIエントリポイントは
後続タスクで追加する。
"""

import filecmp
import shutil
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
    """src配下をdstへ完全ミラーする。

    dst側にあってsrc側に無いファイル・ディレクトリ（skip_names該当を除く）は削除する。
    dstが存在しない場合はエラーにせず新規作成する。

    Args:
        src: ミラー元ディレクトリ。
        dst: ミラー先ディレクトリ。
        skip_names: コピー・削除判定の両方から除外する名前の集合
            （再帰的にどの深さでも一致すれば除外）。
        structure_only: Trueならディレクトリのみ再現しファイルは無視する。
        dry_run: Trueの場合はファイルシステムに一切書き込まず、操作ログだけを返す。

    Returns:
        実行した（またはdry_run=Trueでは実行予定の）操作ログの文字列リスト
        （例: "ADD <relpath>", "UPDATE <relpath>", "DELETE <relpath>"）。
    """
    logs: list[str] = []
    _mirror_dir_recursive(src, dst, src, dst, skip_names, structure_only, dry_run, logs)
    return logs


def _mirror_dir_recursive(
    src_dir: Path,
    dst_dir: Path,
    src_root: Path,
    dst_root: Path,
    skip_names: frozenset[str],
    structure_only: bool,
    dry_run: bool,
    logs: list[str],
) -> None:
    """mirror_dirの再帰本体。1階層分の追加・更新・削除を判定し、サブディレクトリへ再帰する。"""
    if not dry_run:
        dst_dir.mkdir(parents=True, exist_ok=True)

    src_names = {entry.name for entry in src_dir.iterdir()} if src_dir.exists() else set()
    src_names -= skip_names
    dst_names = {entry.name for entry in dst_dir.iterdir()} if dst_dir.exists() else set()
    dst_names -= skip_names

    for name in sorted(src_names):
        src_path = src_dir / name
        dst_path = dst_dir / name
        if src_path.is_dir():
            _mirror_dir_recursive(
                src_path, dst_path, src_root, dst_root, skip_names, structure_only, dry_run, logs
            )
        elif not structure_only:
            rel_path = src_path.relative_to(src_root).as_posix()
            if not dst_path.exists():
                logs.append(f"ADD {rel_path}")
                if not dry_run:
                    shutil.copy2(src_path, dst_path)
            elif not filecmp.cmp(src_path, dst_path, shallow=False):
                logs.append(f"UPDATE {rel_path}")
                if not dry_run:
                    shutil.copy2(src_path, dst_path)

    for name in sorted(dst_names - src_names):
        dst_path = dst_dir / name
        rel_path = dst_path.relative_to(dst_root).as_posix()
        if dst_path.is_dir():
            logs.append(f"DELETE {rel_path}")
            if not dry_run:
                shutil.rmtree(dst_path)
        elif not structure_only:
            logs.append(f"DELETE {rel_path}")
            if not dry_run:
                dst_path.unlink()


def copy_file(src: Path, dst: Path, *, base_dir: Path, dry_run: bool) -> list[str]:
    """srcをdstへ上書きコピーする（単一ファイル）。

    操作ログの相対パス表記をmirror_dirと統一するため、dstの祖先ディレクトリを
    base_dirとして明示的に受け取る。

    Args:
        src: コピー元ファイル。
        dst: コピー先ファイル。
        base_dir: 操作ログの相対パス表記の基準ディレクトリ（dstの祖先ディレクトリ）。
        dry_run: Trueの場合はファイルシステムに一切書き込まず、操作ログだけを返す。

    Returns:
        実行した（またはdry_run=Trueでは実行予定の）操作ログの文字列リスト
        （新規なら"ADD <relpath>"、更新なら"UPDATE <relpath>"、変更が無ければ空リスト）。
    """
    rel_path = dst.relative_to(base_dir).as_posix()

    if not dst.exists():
        action = "ADD"
    elif not filecmp.cmp(src, dst, shallow=False):
        action = "UPDATE"
    else:
        return []

    if not dry_run:
        shutil.copy2(src, dst)
    return [f"{action} {rel_path}"]


def run(dry_run: bool) -> list[str]:
    """フルミラー・ディレクトリと単一ファイルコピーの同期を実行し、操作ログを集約する。

    このタスク（Task 1）ではフルミラー・ディレクトリ（.claude/, 80_Templates/,
    82_Bases/, 90_SkillFlows/）と単一ファイルコピー（CLAUDE.md, README.md）のみを扱う。
    `.obsidian/`許可リストミラー・個人ノート構造ミラーは後続タスクが追加する。

    Args:
        dry_run: Trueの場合はファイルシステムに一切書き込まず、操作ログだけを返す。

    Returns:
        全カテゴリの操作ログを連結した文字列リスト。
    """
    logs: list[str] = []

    logs += mirror_dir(
        VAULT_ROOT / ".claude",
        REPO_ROOT / ".claude",
        skip_names=CLAUDE_SKIP_NAMES,
        dry_run=dry_run,
    )
    logs += mirror_dir(VAULT_ROOT / "80_Templates", REPO_ROOT / "80_Templates", dry_run=dry_run)
    logs += mirror_dir(VAULT_ROOT / "82_Bases", REPO_ROOT / "82_Bases", dry_run=dry_run)
    logs += mirror_dir(
        VAULT_ROOT / "90_SkillFlows", REPO_ROOT / "90_SkillFlows", dry_run=dry_run
    )

    logs += copy_file(
        VAULT_ROOT / "CLAUDE.md", REPO_ROOT / "CLAUDE.md", base_dir=REPO_ROOT, dry_run=dry_run
    )
    logs += copy_file(
        VAULT_ROOT / "README.md", REPO_ROOT / "README.md", base_dir=REPO_ROOT, dry_run=dry_run
    )

    return logs
