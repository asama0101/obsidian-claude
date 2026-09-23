"""sync_from_vault.py のユニットテスト。

一時ディレクトリをsrc/dstとして使い、mirror_dir/copy_file関数の実際の
ファイルシステム操作を検証する統合テスト（モックなし）。
"""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sync_from_vault  # noqa: E402


def test_フルミラー対象で新規ファイルが追加される():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"
        dst = root / "dst"
        src.mkdir()
        (src / "new.md").write_text("new content", encoding="utf-8")

        logs = sync_from_vault.mirror_dir(src, dst)

        assert logs == ["ADD new.md"]
        assert (dst / "new.md").read_text(encoding="utf-8") == "new content"


def test_フルミラー対象で既存ファイルの内容が変わっていれば更新される():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"
        dst = root / "dst"
        src.mkdir()
        dst.mkdir()
        (src / "existing.md").write_text("updated content", encoding="utf-8")
        (dst / "existing.md").write_text("old content", encoding="utf-8")

        logs = sync_from_vault.mirror_dir(src, dst)

        assert logs == ["UPDATE existing.md"]
        assert (dst / "existing.md").read_text(encoding="utf-8") == "updated content"


def test_フルミラー対象でvault側で削除されたファイルはコピー先からも削除される():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"
        dst = root / "dst"
        src.mkdir()
        dst.mkdir()
        (dst / "obsolete.md").write_text("stale", encoding="utf-8")

        logs = sync_from_vault.mirror_dir(src, dst)

        assert logs == ["DELETE obsolete.md"]
        assert not (dst / "obsolete.md").exists()


def test_skip_names指定のランタイム状態はコピーも削除もされない():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"
        dst = root / "dst"
        src.mkdir()
        dst.mkdir()

        # vault側にランタイム状態フォルダ/ファイルがあってもコピーされない
        (src / ".venv").mkdir()
        (src / ".venv" / "pyvenv.cfg").write_text("venv config", encoding="utf-8")
        (src / "scheduled_tasks.lock").write_text("lock", encoding="utf-8")
        (src / "keep.md").write_text("kept", encoding="utf-8")

        # コピー先に既に存在するランタイム状態は削除判定から除外され、消されない
        (dst / "scheduled_tasks.json").write_text('{"existing": true}', encoding="utf-8")

        skip_names = {".venv", "scheduled_tasks.lock", "scheduled_tasks.json"}
        logs = sync_from_vault.mirror_dir(src, dst, skip_names=skip_names)

        assert logs == ["ADD keep.md"]
        assert not (dst / ".venv").exists()
        assert not (dst / "scheduled_tasks.lock").exists()
        assert (dst / "scheduled_tasks.json").read_text(encoding="utf-8") == '{"existing": true}'
        assert (dst / "keep.md").read_text(encoding="utf-8") == "kept"


def test_mirror_dirでdry_run指定時はファイルシステムに書き込まずログだけ返す():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"
        dst = root / "dst"
        src.mkdir()
        (src / "new.md").write_text("new content", encoding="utf-8")

        logs = sync_from_vault.mirror_dir(src, dst, dry_run=True)

        assert logs == ["ADD new.md"]
        assert not dst.exists()


def test_単一ファイルコピーで新規ファイルが追加される():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src_file = root / "CLAUDE.md"
        dst_dir = root / "dst"
        dst_dir.mkdir()
        dst_file = dst_dir / "CLAUDE.md"
        src_file.write_text("claude md content", encoding="utf-8")

        logs = sync_from_vault.copy_file(src_file, dst_file, base_dir=dst_dir, dry_run=False)

        assert logs == ["ADD CLAUDE.md"]
        assert dst_file.read_text(encoding="utf-8") == "claude md content"


def test_単一ファイルコピーで既存ファイルが上書きされる():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src_file = root / "README.md"
        dst_dir = root / "dst"
        dst_dir.mkdir()
        dst_file = dst_dir / "README.md"
        src_file.write_text("new readme", encoding="utf-8")
        dst_file.write_text("old readme", encoding="utf-8")

        logs = sync_from_vault.copy_file(src_file, dst_file, base_dir=dst_dir, dry_run=False)

        assert logs == ["UPDATE README.md"]
        assert dst_file.read_text(encoding="utf-8") == "new readme"


def test_単一ファイルコピーでbase_dirからの深い相対パスがログに使われる():
    # mirror_dirと同様に、base_dirを基準とした深い相対パスが返ることを確認する
    # （dst直下のファイル名だけでなく、サブディレクトリを含む相対パスに対応していること）
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src_file = root / "src" / "CLAUDE.md"
        src_file.parent.mkdir()
        src_file.write_text("claude md content", encoding="utf-8")
        base_dir = root / "dst"
        dst_file = base_dir / "sub" / "CLAUDE.md"
        dst_file.parent.mkdir(parents=True)

        logs = sync_from_vault.copy_file(src_file, dst_file, base_dir=base_dir, dry_run=False)

        assert logs == ["ADD sub/CLAUDE.md"]


# --- ここから Task 2: mirror_dir(structure_only=True) ---


def test_構造のみミラーでファイルはコピーされず末端ディレクトリにgitkeepが置かれる():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"
        dst = root / "dst"
        (src / "leaf1").mkdir(parents=True)
        (src / "leaf1" / "note.md").write_text("note", encoding="utf-8")
        (src / "parent" / "child").mkdir(parents=True)

        logs = sync_from_vault.mirror_dir(src, dst, structure_only=True)

        assert (dst / "leaf1").is_dir()
        assert not (dst / "leaf1" / "note.md").exists()
        assert (dst / "leaf1" / ".gitkeep").exists()
        assert (dst / "parent").is_dir()
        assert not (dst / "parent" / ".gitkeep").exists()
        assert (dst / "parent" / "child").is_dir()
        assert (dst / "parent" / "child" / ".gitkeep").exists()
        assert not (dst / ".gitkeep").exists()
        assert set(logs) == {"ADD leaf1/.gitkeep", "ADD parent/child/.gitkeep"}


def test_構造のみミラーでdst側の余分なファイルとディレクトリは完全ミラー方針で削除される():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"
        dst = root / "dst"
        (src / "leaf").mkdir(parents=True)
        (dst / "leaf").mkdir(parents=True)
        (dst / "leaf" / "stray.md").write_text("stray", encoding="utf-8")
        (dst / "obsolete_dir").mkdir(parents=True)
        (dst / "obsolete_dir" / "old.md").write_text("old", encoding="utf-8")

        logs = sync_from_vault.mirror_dir(src, dst, structure_only=True)

        assert not (dst / "leaf" / "stray.md").exists()
        assert (dst / "leaf" / ".gitkeep").exists()
        assert not (dst / "obsolete_dir").exists()
        assert set(logs) == {
            "DELETE leaf/stray.md",
            "ADD leaf/.gitkeep",
            "DELETE obsolete_dir",
        }


def test_構造のみミラーで末端ディレクトリにサブフォルダが増えると既存のgitkeepが削除される():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"
        dst = root / "dst"
        (src / "target" / "newsub").mkdir(parents=True)
        (dst / "target").mkdir(parents=True)
        (dst / "target" / ".gitkeep").write_text("", encoding="utf-8")

        logs = sync_from_vault.mirror_dir(src, dst, structure_only=True)

        assert not (dst / "target" / ".gitkeep").exists()
        assert (dst / "target" / "newsub").is_dir()
        assert (dst / "target" / "newsub" / ".gitkeep").exists()
        assert set(logs) == {"DELETE target/.gitkeep", "ADD target/newsub/.gitkeep"}


def test_構造のみミラーでサブフォルダが無くなり末端に戻るとgitkeepが追加される():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"
        dst = root / "dst"
        (src / "target").mkdir(parents=True)
        (dst / "target" / "newsub").mkdir(parents=True)
        (dst / "target" / "newsub" / ".gitkeep").write_text("", encoding="utf-8")

        logs = sync_from_vault.mirror_dir(src, dst, structure_only=True)

        assert not (dst / "target" / "newsub").exists()
        assert (dst / "target" / ".gitkeep").exists()
        assert set(logs) == {"DELETE target/newsub", "ADD target/.gitkeep"}


# --- ここから Task 2: mirror_obsidian_allowlist ---


def test_obsidian許可リストで許可リスト外のファイルは無視され許可リスト内のファイルは反映される():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        vault_obsidian = root / "vault" / ".obsidian"
        repo_obsidian = root / "repo" / ".obsidian"
        vault_obsidian.mkdir(parents=True)
        repo_obsidian.mkdir(parents=True)
        (vault_obsidian / "app.json").write_text("app content", encoding="utf-8")
        (vault_obsidian / "workspace.json").write_text("vault workspace", encoding="utf-8")
        (repo_obsidian / "app.json").write_text("old app content", encoding="utf-8")
        (repo_obsidian / "workspace.json").write_text("local workspace", encoding="utf-8")

        logs = sync_from_vault.mirror_obsidian_allowlist(
            vault_obsidian, repo_obsidian, dry_run=False
        )

        assert logs == ["UPDATE app.json"]
        assert (repo_obsidian / "app.json").read_text(encoding="utf-8") == "app content"
        # 許可リスト外のworkspace.jsonは一切触れられない（vault側の内容が反映されない）
        assert (repo_obsidian / "workspace.json").read_text(encoding="utf-8") == "local workspace"


def test_obsidian許可リストでrepo側にディレクトリが無くても新規作成され許可リスト項目が反映される():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        vault_obsidian = root / "vault" / ".obsidian"
        repo_obsidian = root / "repo" / ".obsidian"
        vault_obsidian.mkdir(parents=True)
        (vault_obsidian / "app.json").write_text("app content", encoding="utf-8")
        (vault_obsidian / "appearance.json").write_text("appearance content", encoding="utf-8")
        (vault_obsidian / "themes").mkdir()
        (vault_obsidian / "themes" / "mytheme.css").write_text("css", encoding="utf-8")

        logs = sync_from_vault.mirror_obsidian_allowlist(
            vault_obsidian, repo_obsidian, dry_run=False
        )

        assert repo_obsidian.is_dir()
        assert (repo_obsidian / "app.json").read_text(encoding="utf-8") == "app content"
        assert (
            repo_obsidian / "appearance.json"
        ).read_text(encoding="utf-8") == "appearance content"
        assert (repo_obsidian / "themes" / "mytheme.css").read_text(encoding="utf-8") == "css"
        assert set(logs) == {"ADD app.json", "ADD appearance.json", "ADD mytheme.css"}


def test_obsidian許可リストでvault側から削除された対象ファイルはコピー先からも削除される():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        vault_obsidian = root / "vault" / ".obsidian"
        repo_obsidian = root / "repo" / ".obsidian"
        vault_obsidian.mkdir(parents=True)
        repo_obsidian.mkdir(parents=True)
        (repo_obsidian / "hotkeys.json").write_text("stale hotkeys", encoding="utf-8")

        logs = sync_from_vault.mirror_obsidian_allowlist(
            vault_obsidian, repo_obsidian, dry_run=False
        )

        assert not (repo_obsidian / "hotkeys.json").exists()
        assert logs == ["DELETE hotkeys.json"]


def test_obsidian許可リストでdry_run指定時はファイルシステムに書き込まずログだけ返す():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        vault_obsidian = root / "vault" / ".obsidian"
        repo_obsidian = root / "repo" / ".obsidian"
        vault_obsidian.mkdir(parents=True)
        (vault_obsidian / "app.json").write_text("app content", encoding="utf-8")

        logs = sync_from_vault.mirror_obsidian_allowlist(
            vault_obsidian, repo_obsidian, dry_run=True
        )

        assert logs == ["ADD app.json"]
        assert not repo_obsidian.exists()


# --- ここから Task 3: エラー処理・耐性 ---


def test_symlinkはたどられずスキップされ操作ログに記録される(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"
        dst = root / "dst"
        src.mkdir()
        (src / "linked").mkdir()
        (src / "linked" / "inside.md").write_text("inside", encoding="utf-8")
        (src / "keep.md").write_text("kept", encoding="utf-8")

        original_islink = sync_from_vault.os.path.islink

        def fake_islink(path):
            # このWindows環境ではシンボリックリンク作成に管理者権限/開発者モードが必要で
            # テスト環境で再現できない（実測でos.symlinkがWinError 1314を送出することを確認済み）
            # ため、os.path.islinkをモンキーパッチしてシンボリックリンクの存在を模擬する
            if Path(path).name == "linked":
                return True
            return original_islink(path)

        monkeypatch.setattr(sync_from_vault.os.path, "islink", fake_islink)

        logs = sync_from_vault.mirror_dir(src, dst)

        assert "SKIP（symlink） linked" in logs
        assert not (dst / "linked").exists()
        assert (dst / "keep.md").read_text(encoding="utf-8") == "kept"


def test_読み取り不可なファイルがあっても他のファイルの処理は続行される(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"
        dst = root / "dst"
        src.mkdir()
        (src / "broken.md").write_text("broken", encoding="utf-8")
        (src / "ok.md").write_text("ok content", encoding="utf-8")

        original_copy2 = sync_from_vault.shutil.copy2

        def fake_copy2(src_path, dst_path, *args, **kwargs):
            # Windows上ではファイル所有者に対するchmodだけでは読み取り不能を再現できないため、
            # shutil.copy2をモンキーパッチしてOSError（権限エラー・OneDriveオンデマンド
            # ファイル未ダウンロード等）を模擬する
            if Path(src_path).name == "broken.md":
                raise OSError("simulated permission denied")
            return original_copy2(src_path, dst_path, *args, **kwargs)

        monkeypatch.setattr(sync_from_vault.shutil, "copy2", fake_copy2)

        logs = sync_from_vault.mirror_dir(src, dst)

        assert any(log.startswith("SKIP（読み取り不可） broken.md") for log in logs)
        assert "ADD ok.md" in logs
        assert (dst / "ok.md").read_text(encoding="utf-8") == "ok content"
        assert not (dst / "broken.md").exists()


def test_読み取り以外のOSErrorはロールバックせずそのまま伝播する(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"
        dst = root / "dst"
        src.mkdir()
        dst.mkdir()
        (src / "new.md").write_text("new content", encoding="utf-8")
        (dst / "obsolete_dir").mkdir()
        (dst / "obsolete_dir" / "old.md").write_text("old", encoding="utf-8")

        original_rmtree = sync_from_vault.shutil.rmtree

        def fake_rmtree(path, *args, **kwargs):
            # ディレクトリ削除中に想定外のOSError（読み取り以外）が発生するケースを
            # 再現するため、shutil.rmtreeをモンキーパッチする。sync_from_vault.shutilは
            # 実体が標準ライブラリshutilと同一モジュールのため、対象パス以外は元の実装に
            # 委譲し、tempfile.TemporaryDirectoryの後片付け処理まで巻き込まないようにする
            if Path(path).name == "obsolete_dir":
                raise OSError("simulated deletion failure")
            return original_rmtree(path, *args, **kwargs)

        monkeypatch.setattr(sync_from_vault.shutil, "rmtree", fake_rmtree)

        with pytest.raises(OSError):
            sync_from_vault.mirror_dir(src, dst)

        # 先行して完了済みのADDはロールバックされずそのまま残る
        assert (dst / "new.md").read_text(encoding="utf-8") == "new content"
        # 削除に失敗したディレクトリもロールバックされずそのまま残る
        assert (dst / "obsolete_dir").exists()


def test_VAULT_ROOTが存在しない場合エラー終了する(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fake_vault_root = root / "nonexistent_vault"
        fake_repo_root = root / "repo"
        fake_repo_root.mkdir()
        monkeypatch.setattr(sync_from_vault, "VAULT_ROOT", fake_vault_root)
        monkeypatch.setattr(sync_from_vault, "REPO_ROOT", fake_repo_root)

        with pytest.raises(SystemExit) as exc_info:
            sync_from_vault.run(dry_run=True)

        assert str(fake_vault_root) in str(exc_info.value)
