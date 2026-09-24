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
import stat
import subprocess
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


def _clear_readonly(path: str) -> None:
    """パスに付いた読み取り専用属性を解除する。

    OneDriveが（特に空になった直後の）フォルダ・ファイルへ読み取り専用属性を
    自動付与し、Windows上での削除操作をブロックすることがあるための前処理。
    属性解除自体が失敗しても、直後の削除リトライの失敗に委ねるためここでは無視する。
    """
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass


def _rmtree_onexc(func, path, exc: BaseException) -> None:
    """shutil.rmtreeの失敗時コールバック（Python 3.12以降のonexc引数）。

    PermissionErrorの場合のみ、読み取り専用属性を解除したうえで渡された削除関数
    （os.rmdir/os.remove）を1回だけ再試行する（`_unlink_with_retry`と同じ判定方針）。
    再試行でも失敗した場合はその例外をそのまま呼び出し元へ伝播させる（onexcは自ら
    再送出しない限りrmtree側で握りつぶされてしまうため）。PermissionError以外
    （真のファイルロック等）はチェック無しでそのまま再送出し、無関係なos.chmod
    副作用を発生させない（既存の「削除中のOSErrorはロールバックせず伝播する」
    方針は変えない）。
    """
    if not isinstance(exc, PermissionError):
        raise exc
    _clear_readonly(path)
    func(path)


def _unlink_with_retry(path: Path) -> None:
    """ファイルを削除する。

    PermissionError発生時は読み取り専用属性を解除して1回だけ再試行する
    （OneDriveが読み取り専用属性を自動付与したファイルへの対処）。
    再試行でも失敗すればそのまま例外を伝播させる。
    """
    try:
        path.unlink()
    except PermissionError:
        _clear_readonly(path)
        path.unlink()


def mirror_dir(
    src: Path,
    dst: Path,
    *,
    skip_names: frozenset[str] = frozenset(),
    structure_only: bool = False,
    dry_run: bool = False,
    repo_root: Path | None = None,
) -> list[str]:
    """src配下をdstへ完全ミラーする。

    dst側にあってsrc側に無いファイル・ディレクトリ（skip_names該当を除く）は削除する。
    dstが存在しない場合はエラーにせず新規作成する。

    srcディレクトリ自体（このトップレベル呼び出しの引数）が存在しない場合は、
    OneDrive同期遅延等による一時的な不在の可能性があるため「src側が空」として
    扱わず、dst側に一切触れずSKIPする（サブディレクトリが再帰の途中で消える
    場合は、vault側で意図的に削除されたケースと区別できないため対象外。
    そちらは従来通り削除する）。

    Args:
        src: ミラー元ディレクトリ。
        dst: ミラー先ディレクトリ。
        skip_names: コピー・削除判定の両方から除外する名前の集合
            （再帰的にどの深さでも一致すれば除外）。
        structure_only: Trueならディレクトリのみ再現しファイルは無視する。
            この場合、dst側の.gitkeep以外のファイルはsrc側に同名ファイルが
            存在するかどうかに関わらず無条件で削除対象になる。
        dry_run: Trueの場合はファイルシステムに一切書き込まず、操作ログだけを返す。
        repo_root: ADD/UPDATE/DELETEログの相対パス表記の基準ディレクトリ。
            省略時はdst（このカテゴリのミラー先ディレクトリ）を基準にする
            （単体呼び出し時の従来互換）。git add対象パスとして使う場合は
            リポジトリルートを明示的に渡す。

    Returns:
        実行した（またはdry_run=Trueでは実行予定の）操作ログの文字列リスト
        （例: "ADD <relpath>", "UPDATE <relpath>", "DELETE <relpath>",
        srcディレクトリ自体が不在なら"SKIP（ミラー元ディレクトリ不在） <src>"）。
    """
    logs: list[str] = []
    if not src.exists():
        # OneDrive同期遅延等でミラー元ディレクトリ自体が一時的に見えなくなる場合がある。
        # ここで「src側が空」として扱うとdst側の既存内容が丸ごと削除対象になってしまうため、
        # トップレベル呼び出しに限りsrc不在を検知したら何もせずSKIPし、既存内容を保持する
        # （サブディレクトリが再帰の途中で消える場合は、vault側で意図的に削除されたケースと
        # 区別できないため、こちらは_mirror_dir_recursive内の従来通りの削除セマンティクスに従う）
        logs.append(f"SKIP（ミラー元ディレクトリ不在） {src}")
        return logs
    log_root = repo_root if repo_root is not None else dst
    _mirror_dir_recursive(src, dst, src, log_root, skip_names, structure_only, dry_run, logs)
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

    dst_rootはADD/UPDATE/DELETEログの相対パス表記の基準ディレクトリ（mirror_dirが
    repo_root指定時はリポジトリルート、未指定時はこのカテゴリのミラー先ディレクトリ）
    であり、再帰全体を通じて変わらない。
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

    if structure_only:
        # structure_onlyでは「名前がsrc側と一致するか」でなく「dst側にファイルが
        # 存在するかどうか」だけで削除判定する。src側に同名ファイルが存在するという
        # 理由でdst側の残留ファイル（個人ノート等）を削除対象から除外してはならない
        # （個人情報系フォルダには本来ファイルが一切存在してはいけないため）
        delete_candidates = dst_names
    else:
        delete_candidates = dst_names - src_names

    for name in sorted(delete_candidates):
        dst_path = dst_dir / name
        rel_path = dst_path.relative_to(dst_root).as_posix()
        if dst_path.is_dir():
            if structure_only and name in src_names and (src_dir / name).is_dir():
                # src側にも対応するディレクトリがあり既に再帰処理済みのため、ここでは何もしない
                continue
            logs.append(f"DELETE {rel_path}")
            if not dry_run:
                shutil.rmtree(dst_path, onexc=_rmtree_onexc)
        elif name == ".gitkeep" and structure_only:
            # .gitkeepの追加・削除はこの後の末端判定でまとめて扱うためここではスキップする
            continue
        else:
            logs.append(f"DELETE {rel_path}")
            if not dry_run:
                _unlink_with_retry(dst_path)

    if structure_only:
        _sync_gitkeep_marker(dst_dir, dst_root, has_subdirs, dry_run, logs)


def _sync_gitkeep_marker(
    dst_dir: Path,
    dst_root: Path,
    has_subdirs: bool,
    dry_run: bool,
    logs: list[str],
) -> None:
    """structure_only用の`.gitkeep`増減簿記。

    末端ディレクトリ（has_subdirs=False）には`.gitkeep`を置き、末端でなくなった
    ディレクトリ（has_subdirs=True）からは`.gitkeep`を取り除く。この判定は
    毎回src側の現状（has_subdirs）から再計算する（前回の状態は記憶しない）。
    """
    gitkeep_path = dst_dir / ".gitkeep"
    gitkeep_rel = gitkeep_path.relative_to(dst_root).as_posix()
    gitkeep_exists = gitkeep_path.exists()
    if has_subdirs:
        if gitkeep_exists:
            logs.append(f"DELETE {gitkeep_rel}")
            if not dry_run:
                _unlink_with_retry(gitkeep_path)
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
        srcが存在せずdstが存在すれば"DELETE <relpath>"（両方存在しなければ空リスト）、
        読み取り時にOSError（権限エラー・OneDriveオンデマンドファイル未ダウンロード等）が
        発生すれば"SKIP（読み取り不可） <relpath>: <エラー内容>"）。

    Raises:
        OSError: 書き込み側（コピー先ディスク満杯・コピー先ファイルロック中等）で
            発生した場合。読み取り側のOSErrorとは異なりSKIPせず、ロールバックもせず
            そのまま伝播させる。
    """
    rel_path = dst.relative_to(base_dir).as_posix()

    if not src.exists():
        # vault側に無いのは「読み取り不可」ではなく単に存在しない状態。ディレクトリ
        # ミラーの削除セマンティクスと一貫させるため、dst側に残っていれば削除する
        if dst.exists():
            logs = [f"DELETE {rel_path}"]
            if not dry_run:
                _unlink_with_retry(dst)
            return logs
        return []

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
    vault_obsidian: Path, repo_obsidian: Path, *, dry_run: bool, repo_root: Path | None = None
) -> list[str]:
    """.obsidian/配下を許可リスト方式でミラーする。

    許可リスト（OBSIDIAN_ALLOWLIST_FILESの各ファイル + themes/ディレクトリ）だけを対象にする。
    許可リスト以外の.obsidian/配下のファイル・ディレクトリ（workspace.json等）には
    一切触れない（読み取らない・削除しない）。

    Args:
        vault_obsidian: Vault側の.obsidian/ディレクトリ。
        repo_obsidian: リポジトリ側の.obsidian/ディレクトリ（無ければ新規作成する）。
        dry_run: Trueの場合はファイルシステムに一切書き込まず、操作ログだけを返す。
        repo_root: ADD/UPDATE/DELETEログの相対パス表記の基準ディレクトリ。
            省略時はrepo_obsidianを基準にする（単体呼び出し時の従来互換）。
            git add対象パスとして使う場合はリポジトリルートを明示的に渡す。

    Returns:
        実行した（またはdry_run=Trueでは実行予定の）操作ログの文字列リスト。
    """
    logs: list[str] = []

    if not dry_run:
        repo_obsidian.mkdir(parents=True, exist_ok=True)

    log_root = repo_root if repo_root is not None else repo_obsidian

    for name in sorted(OBSIDIAN_ALLOWLIST_FILES):
        src_path = vault_obsidian / name
        dst_path = repo_obsidian / name
        if os.path.islink(src_path):
            # 他の経路（_mirror_dir_recursive）と同様、symlink・ジャンクションはたどらずスキップする
            logs.append(f"SKIP（symlink） {name}")
            continue
        if src_path.exists():
            logs += copy_file(src_path, dst_path, base_dir=log_root, dry_run=dry_run)
        elif dst_path.exists():
            rel_path = dst_path.relative_to(log_root).as_posix()
            logs.append(f"DELETE {rel_path}")
            if not dry_run:
                _unlink_with_retry(dst_path)

    logs += mirror_dir(
        vault_obsidian / "themes", repo_obsidian / "themes", dry_run=dry_run, repo_root=repo_root
    )

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
        repo_root=REPO_ROOT,
    )
    logs += mirror_dir(
        VAULT_ROOT / "80_Templates",
        REPO_ROOT / "80_Templates",
        dry_run=dry_run,
        repo_root=REPO_ROOT,
    )
    logs += mirror_dir(
        VAULT_ROOT / "82_Bases", REPO_ROOT / "82_Bases", dry_run=dry_run, repo_root=REPO_ROOT
    )
    logs += mirror_dir(
        VAULT_ROOT / "90_SkillFlows",
        REPO_ROOT / "90_SkillFlows",
        dry_run=dry_run,
        repo_root=REPO_ROOT,
    )

    logs += copy_file(
        VAULT_ROOT / "CLAUDE.md", REPO_ROOT / "CLAUDE.md", base_dir=REPO_ROOT, dry_run=dry_run
    )
    logs += copy_file(
        VAULT_ROOT / "README.md", REPO_ROOT / "README.md", base_dir=REPO_ROOT, dry_run=dry_run
    )

    logs += mirror_obsidian_allowlist(
        VAULT_ROOT / ".obsidian", REPO_ROOT / ".obsidian", dry_run=dry_run, repo_root=REPO_ROOT
    )

    for folder in PERSONAL_NOTE_FOLDERS:
        logs += mirror_dir(
            VAULT_ROOT / folder,
            REPO_ROOT / folder,
            structure_only=True,
            dry_run=dry_run,
            repo_root=REPO_ROOT,
        )

    return logs


def _get_current_branch(repo_root: Path) -> str:
    """repo_rootの現在のgitブランチ名を返す。"""
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _extract_changed_paths(logs: list[str]) -> list[str]:
    """操作ログからADD/UPDATE/DELETE行だけを抜き出し、対象パスの一覧を返す。

    SKIPで始まる行（symlinkスキップ・読み取り不可スキップ等）は無視する。
    git add対象パスの決定にはもう使わない（_get_git_status_pathsを使う）。
    ログ表示用の補助関数として残している。
    """
    paths: list[str] = []
    for line in logs:
        for prefix in ("ADD ", "UPDATE ", "DELETE "):
            if line.startswith(prefix):
                paths.append(line[len(prefix):])
                break
    return paths


# _commit_and_pushが`git status --porcelain`の対象範囲として絞り込む監視対象カテゴリパス
# （run()がミラーする全カテゴリに対応。この範囲外の変更はコミット対象にしない）
SYNC_CATEGORY_PATHS = (
    ".claude",
    "80_Templates",
    "82_Bases",
    "90_SkillFlows",
    "CLAUDE.md",
    "README.md",
    ".obsidian",
) + PERSONAL_NOTE_FOLDERS


def _parse_porcelain_paths(porcelain_output: str) -> list[str]:
    """`git status --porcelain`の出力からパス一覧を抽出する。

    各行は先頭2文字のステータスコード + 半角スペース1文字 + パスの形式
    （`git status --porcelain`はv1フォーマットを既定で使う）。
    リネーム（例: "R  old.md -> new.md"）の場合は" -> "以降の新パスのみを採用する。
    """
    paths: list[str] = []
    for line in porcelain_output.splitlines():
        if not line:
            continue
        raw_path = line[3:]
        if " -> " in raw_path:
            raw_path = raw_path.split(" -> ", 1)[1]
        paths.append(raw_path)
    return paths


def _get_git_status_paths(repo_root: Path) -> list[str]:
    """監視対象カテゴリパス（SYNC_CATEGORY_PATHS）に絞ってgit statusを実行し、変更パス一覧を返す。

    run()が今回返した操作ログとは無関係に、gitの作業ツリーに実際に残っている
    未コミットの変更（前回クラッシュ実行の取りこぼし等を含む）を都度確認するために使う。
    """
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", *SYNC_CATEGORY_PATHS],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return _parse_porcelain_paths(result.stdout)


def _commit_and_push(repo_root: Path) -> None:
    """監視対象カテゴリ配下の実際の未コミット変更を元にgit add/commit/pushを一気通貫で行う。

    判定にはrun()が返した今回の操作ログではなく、`git status --porcelain`
    （監視対象カテゴリパスに絞る）を使う。前回クラッシュした実行でミラー処理自体は
    完了済み（disk上は正しい状態）だが、コミット前にクラッシュしたため未コミットの
    変更が作業ツリーに残っているケースも、今回の操作ログの有無に関わらず検知して
    コミット・pushする。
    現在のブランチがmainでなければ、コミット・pushを行わずSystemExitで中断する
    （個人運用ツールのためロールバックは実装せず、subprocessの例外はそのまま伝播させる）。

    Args:
        repo_root: git操作の対象リポジトリのルートディレクトリ。
    """
    changed_paths = _get_git_status_paths(repo_root)
    if not changed_paths:
        print("変更なし。コミット・pushをスキップします。")
        return

    branch = _get_current_branch(repo_root)
    if branch != "main":
        raise SystemExit(
            f"現在のブランチは'{branch}'です。mainブランチでのみコミット・pushを行います。中断します。"
        )

    subprocess.run(["git", "add", "--", *changed_paths], cwd=repo_root, check=True)

    count = len(changed_paths)
    message = f"Sync from vault ({count} changes)\n\n" + "\n".join(changed_paths)
    subprocess.run(["git", "commit", "-m", message], cwd=repo_root, check=True)

    subprocess.run(["git", "push", "origin", "main"], cwd=repo_root, check=True)


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

    if not args.dry_run:
        _commit_and_push(REPO_ROOT)


if __name__ == "__main__":
    main()
