"""list_projects.py のユニットテスト。

pytest（`.claude/skills/vault/scripts/.venv/`のvenv限定の開発依存）を使用する。
"""

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

# scripts/ ディレクトリを import パスに追加する
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import list_projects  # noqa: E402


def test_10_Projectsが無ければ空リストを返す():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        argv = ["--vault-root", str(vault_root)]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = list_projects.main(argv)

        assert result == 0
        output = json.loads(buf.getvalue())
        assert output == {"projects": []}


def test_複数プロジェクトディレクトリがソートされて返る():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        projects_dir = vault_root / "10_Projects"
        projects_dir.mkdir()
        (projects_dir / "Beta").mkdir()
        (projects_dir / "Alpha").mkdir()
        argv = ["--vault-root", str(vault_root)]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = list_projects.main(argv)

        assert result == 0
        output = json.loads(buf.getvalue())
        assert output == {"projects": ["Alpha", "Beta"]}


def test_ディレクトリ以外のファイルは除外される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        projects_dir = vault_root / "10_Projects"
        projects_dir.mkdir()
        (projects_dir / "Alpha").mkdir()
        (projects_dir / "note.md").write_text("dummy", encoding="utf-8")
        argv = ["--vault-root", str(vault_root)]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = list_projects.main(argv)

        assert result == 0
        output = json.loads(buf.getvalue())
        assert output == {"projects": ["Alpha"]}
