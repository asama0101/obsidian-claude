"""Obsidian Vault から Claude Code プラグインの設定をリポジトリへミラーする個人運用ツール。

Vault側（Obsidianの実行環境）を正とし、リポジトリ側（Git管理下のこのプロジェクト）を
Vaultの内容に合わせて同期する。git操作（add/commit/push）は一切行わず、
ファイルのコピー・削除のみを行う。

このモジュールは複数タスクに分割して段階的に実装される。このファイル時点では
以下の4カテゴリを扱う。
- フルミラー・ディレクトリ（.claude/, 80_Templates/, 82_Bases/, 90_SkillFlows/）
- 単一ファイルコピー（CLAUDE.md, README.md）
- `.obsidian/`許可リスト方式ミラー
- 個人ノート系フォルダ（00_Inbox等）の構造のみミラー

symlink・ジャンクションのスキップ、読み取り不可ファイルのスキップ等の
エラー処理・耐性も備える。CLIエントリポイントとして`--dry-run`フラグを
サポートする（`python sync_from_vault.py --dry-run`で実際には変更せず
予定の操作を表示できる）。
"""

import argparse
import filecmp
import os
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
    """mirror_dirの再帰本体。1階層分の追加・更新・削除を判定し、サブディレクトリへ再帰する。

    structure_only=Trueの場合はファイルを一切コピーせず、ディレクトリ構造のみを再現する。
    末端ディレクトリ（サブディレクトリを持たないディレクトリ。src側の構造で判定）には
    `.gitkeep`を置き、末端でなくなったディレクトリからは`.gitkeep`を取り除く。この判定は
    毎回src側の現状から再計算する（前回の状態は記憶しない）。
    """
    if not dry_run:
        dst_dir.mkdir(parents=True, exist_ok=True)

    src_names = {entry.name for entry in src_dir.iterdir()} if src_dir.exists() else set()
    src_names -= skip_names
    dst_names = {entry.name for entry in dst_dir.iterdir()} if dst_dir.exists() else set()
    dst_names -= skip_names

    has_subdirs = False
    for name in sorted(src_names):
        src_path = src_dir / name
        dst_path = dst_dir / name
        if os.path.islink(src_path):
            # シンボリックリンク・ジャンクションはたどらない（循環参照による無限
            # 再帰を避けるため、ファイルとしてもディレクトリとしても扱わずスキップする）
            rel_path = src_path.relative_to(src_root).as_posix()
            logs.append(f"SKIP（symlink） {rel_path}")
            continue
        if src_path.is_dir():
            has_subdirs = True
            _mirror_dir_recursive(
                src_path, dst_path, src_root, dst_root, skip_names, structure_only, dry_run, logs
            )
        elif not structure_only:
            logs.extend(copy_file(src_path, dst_path, base_dir=dst_root, dry_run=dry_run))

    for name in sorted(dst_names - src_names):
        dst_path = dst_dir / name
        rel_path = dst_path.relative_to(dst_root).as_posix()
        if dst_path.is_dir():
            logs.append(f"DELETE {rel_path}")
            if not dry_run:
                shutil.rmtree(dst_path)
        elif structure_only and name == ".gitkeep":
            # .gitkeepの追加・削除はこの後の末端判定でまとめて扱うためここではスキップする
            continue
        else:
            logs.append(f"DELETE {rel_path}")
            if not dry_run:
                dst_path.unlink()

    if structure_only:
        gitkeep_path = dst_dir / ".gitkeep"
        gitkeep_rel = gitkeep_path.relative_to(dst_root).as_posix()
        gitkeep_exists = gitkeep_path.exists()
        if has_subdirs:
            if gitkeep_exists:
                logs.append(f"DELETE {gitkeep_rel}")
                if not dry_run:
                    gitkeep_path.unlink()
        elif not gitkeep_exists:
            logs.append(f"ADD {gitkeep_rel}")
            if not dry_run:
                gitkeep_path.touch()


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
        （新規なら"ADD <relpath>"、更新なら"UPDATE <relpath>"、変更が無ければ空リスト、
        読み取り時にOSError（権限エラー・OneDriveオンデマンドファイル未ダウンロード等）が
        発生すれば"SKIP（読み取り不可） <relpath>: <エラー内容>"）。

    Raises:
        OSError: 書き込み側（コピー先ディスク満杯・コピー先ファイルロック中等）で
            発生した場合。読み取り側のOSErrorとは異なりSKIPせず、ロールバックもせず
            そのまま伝播させる。
    """
    rel_path = dst.relative_to(base_dir).as_posix()

    try:
        if not dst.exists():
            action = "ADD"
            # ADDの場合はfilecmp.cmpによる読み取り確認が行われないため、実際にコピー
            # 可能かどうかをここで明示的に読み取って確認する（結果は使わず破棄する）
            src.read_bytes()
        elif not filecmp.cmp(src, dst, shallow=False):
            action = "UPDATE"
        else:
            return []
    except OSError as exc:
        # 読み取り時のOSErrorはこのファイルだけスキップし処理を続行する
        return [f"SKIP（読み取り不可） {rel_path}: {exc}"]

    # 読み取り確認後の書き込み（メタデータもコピーするためshutil.copy2を使う）は
    # tryの外に置き、書き込み・削除・ディレクトリ作成中のOSErrorはここでは捕捉せず、
    # 呼び出し元へそのまま伝播させる（ロールバックしない）
    if not dry_run:
        shutil.copy2(src, dst)

    return [f"{action} {rel_path}"]


# .obsidian/配下で許可リスト方式でミラーするファイル（この7項目 + themes/ディレクトリのみ）
OBSIDIAN_ALLOWLIST_FILES = frozenset(
    {
        "app.json",
        "appearance.json",
        "core-plugins.json",
        "daily-notes.json",
        "hotkeys.json",
        "switcher.json",
        "types.json",
    }
)


def mirror_obsidian_allowlist(
    vault_obsidian: Path, repo_obsidian: Path, *, dry_run: bool
) -> list[str]:
    """.obsidian/配下を許可リスト方式でミラーする。

    許可リスト（OBSIDIAN_ALLOWLIST_FILESの各ファイル + themes/ディレクトリ）だけを対象にする。
    許可リスト以外の.obsidian/配下のファイル・ディレクトリ（workspace.json等）には
    一切触れない（読み取らない・削除しない）。

    Args:
        vault_obsidian: Vault側の.obsidian/ディレクトリ。
        repo_obsidian: リポジトリ側の.obsidian/ディレクトリ（無ければ新規作成する）。
        dry_run: Trueの場合はファイルシステムに一切書き込まず、操作ログだけを返す。

    Returns:
        実行した（またはdry_run=Trueでは実行予定の）操作ログの文字列リスト。
    """
    logs: list[str] = []

    if not dry_run:
        repo_obsidian.mkdir(parents=True, exist_ok=True)

    for name in sorted(OBSIDIAN_ALLOWLIST_FILES):
        src_path = vault_obsidian / name
        dst_path = repo_obsidian / name
        if src_path.exists():
            logs += copy_file(src_path, dst_path, base_dir=repo_obsidian, dry_run=dry_run)
        elif dst_path.exists():
            logs.append(f"DELETE {name}")
            if not dry_run:
                dst_path.unlink()

    logs += mirror_dir(vault_obsidian / "themes", repo_obsidian / "themes", dry_run=dry_run)

    return logs


# mirror_dir(structure_only=True)でディレクトリ構造のみミラーする個人ノート系フォルダ
PERSONAL_NOTE_FOLDERS = (
    "00_Inbox",
    "10_Daily",
    "20_Projects",
    "30_Areas",
    "40_Resources",
    "50_Archives",
    "81_Attachments",
)


def run(dry_run: bool) -> list[str]:
    """全カテゴリの同期を実行し、操作ログを集約する。

    Args:
        dry_run: Trueの場合はファイルシステムに一切書き込まず、操作ログだけを返す。

    Returns:
        全カテゴリの操作ログを連結した文字列リスト。

    Raises:
        SystemExit: VAULT_ROOTが存在しない場合。フォールバックはしない。
    """
    if not VAULT_ROOT.exists():
        raise SystemExit(f"VAULT_ROOT が見つかりません: {VAULT_ROOT}")

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

    logs += mirror_obsidian_allowlist(
        VAULT_ROOT / ".obsidian", REPO_ROOT / ".obsidian", dry_run=dry_run
    )

    for folder in PERSONAL_NOTE_FOLDERS:
        logs += mirror_dir(
            VAULT_ROOT / folder, REPO_ROOT / folder, structure_only=True, dry_run=dry_run
        )

    return logs


def main() -> None:
    """CLIエントリポイント。`--dry-run`フラグを解釈しrun()を実行、結果を標準出力へ表示する。"""
    parser = argparse.ArgumentParser(description="vaultから設定をコピーする")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際には変更せず、予定の操作を表示する",
    )
    args = parser.parse_args()

    logs = run(dry_run=args.dry_run)

    for line in logs:
        print(line)
    print(f"\n{'[dry-run] ' if args.dry_run else ''}{len(logs)} 件の操作")


if __name__ == "__main__":
    main()
