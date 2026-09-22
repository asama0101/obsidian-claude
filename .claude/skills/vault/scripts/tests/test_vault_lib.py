"""vault_lib.py のユニットテスト。

pytest（`.claude/skills/vault/scripts/.venv/`のvenv限定の開発依存）を使用する。
"""

import datetime
import sys
import tempfile
from pathlib import Path

import pytest

# scripts/ ディレクトリを import パスに追加する
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vault_lib  # noqa: E402


def test_禁止文字を除去する():
    title = 'a\\b/c:d*e?f"g<h>i|j'
    assert vault_lib.sanitize_filename(title) == "abcdefghij"


def test_前後空白をtrimする():
    assert vault_lib.sanitize_filename("  hello  ") == "hello"


def test_80文字超は切り詰める():
    title = "a" * 100
    result = vault_lib.sanitize_filename(title)
    assert len(result) == 80
    assert result == "a" * 80


def test_80文字以下はそのまま():
    title = "a" * 80
    assert vault_lib.sanitize_filename(title) == title


def test_衝突しない場合はそのまま返す():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        result = vault_lib.unique_path(d, "note.md")
        assert result == d / "note.md"


def test_衝突時はsuffixを付与する():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "note.md").write_text("existing", encoding="utf-8")
        result = vault_lib.unique_path(d, "note.md")
        assert result == d / "note-2.md"


def test_複数衝突時はさらにインクリメントする():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "note.md").write_text("existing", encoding="utf-8")
        (d / "note-2.md").write_text("existing", encoding="utf-8")
        result = vault_lib.unique_path(d, "note.md")
        assert result == d / "note-3.md"


def test_既存ファイルを上書きしない():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "note.md").write_text("original content", encoding="utf-8")
        vault_lib.unique_path(d, "note.md")
        assert (d / "note.md").read_text(encoding="utf-8") == "original content"


def test_frontmatterありの場合():
    text = '---\ntitle: "foo"\ntags: []\n---\nbody line1\nbody line2'
    fm, body = vault_lib.split_frontmatter(text)
    assert fm == 'title: "foo"\ntags: []'
    assert body == "body line1\nbody line2"


def test_frontmatterなしの場合():
    text = "just a plain body\nwith no frontmatter"
    fm, body = vault_lib.split_frontmatter(text)
    assert fm == ""
    assert body == text


def test_存在するキーを取得する():
    fm = 'title: "foo"\ndate: "2026-09-21"'
    assert vault_lib.get_fm_value(fm, "title") == "foo"
    assert vault_lib.get_fm_value(fm, "date") == "2026-09-21"


def test_存在しないキーはNoneを返す():
    fm = 'title: "foo"'
    assert vault_lib.get_fm_value(fm, "missing") is None


def test_クォート無しの値も取得できる():
    fm = "count: 5"
    assert vault_lib.get_fm_value(fm, "count") == "5"


def test_既存キーを置換し他行は変化しない():
    fm = 'title: "foo"\ntags: []\ndate: "2026-09-21"'
    result = vault_lib.set_fm_value(fm, "title", "bar")
    assert result == 'title: "bar"\ntags: []\ndate: "2026-09-21"'


def test_存在しないキーは末尾に追加する():
    fm = 'title: "foo"'
    result = vault_lib.set_fm_value(fm, "status", "done")
    assert result == 'title: "foo"\nstatus: "done"'


def test_既存タグリストの末尾に追加する():
    fm = 'title: "foo"\ntags:\n  - existing'
    result = vault_lib.add_tag(fm, "new-tag")
    assert result == 'title: "foo"\ntags:\n  - existing\n  - new-tag'


def test_tagsキーが無い場合は新設する():
    fm = 'title: "foo"'
    result = vault_lib.add_tag(fm, "new-tag")
    assert result == 'title: "foo"\ntags:\n  - new-tag'


def test_tagsキーが空の場合はそこに追加する():
    fm = 'title: "foo"\ntags:\ndate: "2026-09-21"'
    result = vault_lib.add_tag(fm, "new-tag")
    assert result == 'title: "foo"\ntags:\n  - new-tag\ndate: "2026-09-21"'


def test_複数タグを順番通り取得する():
    fm = "tags:\n  - alpha\n  - beta\n  - gamma"
    assert vault_lib.get_fm_tags(fm) == ["alpha", "beta", "gamma"]


def test_tagsキーが無い場合は空リスト():
    fm = 'title: "foo"'
    assert vault_lib.get_fm_tags(fm) == []


def test_tagsキーが空の場合は空リスト():
    fm = 'title: "foo"\ntags:\ndate: "2026-09-21"'
    assert vault_lib.get_fm_tags(fm) == []


def test_単一タグを取得する():
    fm = "tags:\n  - solo"
    assert vault_lib.get_fm_tags(fm) == ["solo"]


@pytest.fixture
def dt():
    # 2026-09-21 は月曜日
    return datetime.datetime(2026, 9, 21, 14, 30)


def test_title置換(dt):
    result = vault_lib.fill_template("{{title}}", title="MyTitle", dt=dt)
    assert result == "MyTitle"


def test_date置換(dt):
    result = vault_lib.fill_template("{{date:YYYY-MM-DD}}", title="t", dt=dt)
    assert result == "2026-09-21"


def test_曜日置換(dt):
    result = vault_lib.fill_template("{{date:ddd}}", title="t", dt=dt)
    assert result == "月"


def test_時刻置換(dt):
    result = vault_lib.fill_template("{{time:HH:mm}}", title="t", dt=dt)
    assert result == "14:30"


def test_複数同時使用(dt):
    template = "# {{title}} ({{date:YYYY-MM-DD}} {{date:ddd}} {{time:HH:mm}})"
    result = vault_lib.fill_template(template, title="会議", dt=dt)
    assert result == "# 会議 (2026-09-21 月 14:30)"


def test_他のプレースホルダは残す(dt):
    result = vault_lib.fill_template("{{unknown}}", title="t", dt=dt)
    assert result == "{{unknown}}"


def test_各曜日の変換():
    # 2026-09-21(月) から 2026-09-27(日) まで
    expected = ["月", "火", "水", "木", "金", "土", "日"]
    for i, label in enumerate(expected):
        dt = datetime.datetime(2026, 9, 21 + i)
        result = vault_lib.fill_template("{{date:ddd}}", title="t", dt=dt)
        assert result == label


def test_get_marker_blockで抽出する():
    text = "before\n<!-- START -->\ninner line1\ninner line2\n<!-- END -->\nafter"
    result = vault_lib.get_marker_block(text, "START", "END")
    assert result == "inner line1\ninner line2"


def test_get_marker_blockで見つからない場合は空文字():
    text = "no markers here"
    result = vault_lib.get_marker_block(text, "START", "END")
    assert result == ""


def test_set_marker_blockでマーカー行を保持し中身を置換する():
    text = "before\n<!-- START -->\nold inner\n<!-- END -->\nafter"
    result = vault_lib.set_marker_block(text, "START", "END", "new inner")
    assert result == "before\n<!-- START -->\nnew inner\n<!-- END -->\nafter"


def test_見出し直後から次の見出し直前までの範囲を返す():
    import re

    text = "## 見出し1\nline1\nline2\n## 見出し2\nline3\n"
    pattern = re.compile(r"^## 見出し1[ \t]*$", re.MULTILINE)
    span = vault_lib.find_heading_section(text, pattern)
    assert span is not None
    assert text[span[0] : span[1]] == "\nline1\nline2\n"


def test_見出しが無ければNone():
    import re

    text = "## 別の見出し\nline1\n"
    pattern = re.compile(r"^## 見出し1[ \t]*$", re.MULTILINE)
    assert vault_lib.find_heading_section(text, pattern) is None


def test_見出しが文書末尾のセクションなら末尾までを返す():
    import re

    text = "## 見出し1\nline1\nline2"
    pattern = re.compile(r"^## 見出し1[ \t]*$", re.MULTILINE)
    span = vault_lib.find_heading_section(text, pattern)
    assert text[span[0] : span[1]] == "\nline1\nline2"


def test_複数ディレクトリがある場合ソートされた名前を返す():
    with tempfile.TemporaryDirectory() as tmp:
        projects_dir = Path(tmp) / "Projects"
        projects_dir.mkdir()
        (projects_dir / "Beta").mkdir()
        (projects_dir / "Alpha").mkdir()
        result = vault_lib.list_project_names(projects_dir)
        assert result == ["Alpha", "Beta"]


def test_ディレクトリ以外のファイルは除外される():
    with tempfile.TemporaryDirectory() as tmp:
        projects_dir = Path(tmp) / "Projects"
        projects_dir.mkdir()
        (projects_dir / "Alpha").mkdir()
        (projects_dir / "note.md").write_text("dummy", encoding="utf-8")
        result = vault_lib.list_project_names(projects_dir)
        assert result == ["Alpha"]


def test_projects_dirが存在しない場合は空リスト():
    with tempfile.TemporaryDirectory() as tmp:
        missing_dir = Path(tmp) / "NoSuchDir"
        result = vault_lib.list_project_names(missing_dir)
        assert result == []


def _make_projects(tmp, names):
    projects_dir = Path(tmp) / "Projects"
    projects_dir.mkdir()
    for name in names:
        (projects_dir / name).mkdir()
    return projects_dir


def test_1件一致():
    with tempfile.TemporaryDirectory() as tmp:
        projects_dir = _make_projects(tmp, ["VaultMigration", "OtherProj"])
        result = vault_lib.fuzzy_project_match(
            "VaultMigrationの件について相談", projects_dir
        )
        assert result == '"[[VaultMigration]]"'


def test_0件一致():
    with tempfile.TemporaryDirectory() as tmp:
        projects_dir = _make_projects(tmp, ["VaultMigration", "OtherProj"])
        result = vault_lib.fuzzy_project_match("全く関係ない文章です", projects_dir)
        assert result is None


def test_2件以上一致でNone():
    with tempfile.TemporaryDirectory() as tmp:
        projects_dir = _make_projects(tmp, ["VaultAlpha", "VaultBeta"])
        result = vault_lib.fuzzy_project_match("VaultについてAlphaとBetaの話", projects_dir)
        assert result is None


def test_projects_dirが存在しない場合はNone():
    with tempfile.TemporaryDirectory() as tmp:
        missing_dir = Path(tmp) / "NoSuchDir"
        result = vault_lib.fuzzy_project_match("何でもいい文章", missing_dir)
        assert result is None


def test_VAULT_ROOTがPathである():
    assert isinstance(vault_lib.VAULT_ROOT, Path)


def test_VAULT_ROOTは_claude_skills_vault_scriptsの親である():
    # vault_lib.py は <VAULT_ROOT>/.claude/skills/vault/scripts/vault_lib.py に配置される
    expected_file = (
        vault_lib.VAULT_ROOT / ".claude" / "skills" / "vault" / "scripts" / "vault_lib.py"
    )
    assert expected_file == Path(vault_lib.__file__).resolve()


def test_git_versionを実行できる():
    with tempfile.TemporaryDirectory() as tmp:
        result = vault_lib.run_git("--version", cwd=tmp)
        assert "git version" in result


def test_check_trueで異常終了時に例外を送出する():
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(Exception):
            vault_lib.run_git("not-a-real-git-command", cwd=tmp)
