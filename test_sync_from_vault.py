"""sync_from_vault.py のユニットテスト。

一時ディレクトリをsrc/dstとして使い、mirror_dir/copy_file関数の実際の
ファイルシステム操作を検証する統合テスト（モックなし）。
"""

import sys
import tempfile
from pathlib import Path

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
