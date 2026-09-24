"""task_gantt.py のユニットテスト。

pytest（`.claude/skills/vault/scripts/.venv/`のvenv限定の開発依存）を使用する。
"""

import json
import re
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import task_gantt  # noqa: E402
import vault_lib  # noqa: E402

_TODAY = date(2026, 9, 24)
_WINDOW_END = _TODAY + timedelta(days=90)

_TASK_TEMPLATE = (
    "---\n"
    "type: task\n"
    'project: ""\n'
    "status: {status}\n"
    "start_date: {start_date}\n"
    "due_date: {due_date}\n"
    "---\n"
    "# {title}\n"
)

_MEETING_TEMPLATE = (
    "---\n"
    "type: meeting\n"
    "---\n"
    "# ミーティング\n"
)


def _fields(status="1_todo", start_date="2026-09-01", due_date="2026-09-24"):
    return {
        "path": Path("dummy.md"),
        "title": "dummy",
        "project": "",
        "status": status,
        "start_date": start_date,
        "due_date": due_date,
    }


# --- _classify_task ---


def test_start_date未設定はunscheduled():
    fields = _fields(start_date="", due_date="2026-09-24")
    assert task_gantt._classify_task(fields, _TODAY, _WINDOW_END) == "unscheduled"


def test_due_date未設定はunscheduled():
    fields = _fields(start_date="2026-09-01", due_date="")
    assert task_gantt._classify_task(fields, _TODAY, _WINDOW_END) == "unscheduled"


def test_due_dateが不正形式でも例外を投げずunscheduled():
    fields = _fields(start_date="2026-09-01", due_date="2026/09/24")
    assert task_gantt._classify_task(fields, _TODAY, _WINDOW_END) == "unscheduled"


def test_start_dateが不正形式でも例外を投げずunscheduled():
    fields = _fields(start_date="2026/09/01", due_date="2026-09-24")
    assert task_gantt._classify_task(fields, _TODAY, _WINDOW_END) == "unscheduled"


def test_due_dateがtodayならbar():
    fields = _fields(due_date="2026-09-24")
    assert task_gantt._classify_task(fields, _TODAY, _WINDOW_END) == "bar"


def test_due_dateがtoday_plus_90ならbar():
    fields = _fields(due_date=str(_TODAY + timedelta(days=90)))
    assert task_gantt._classify_task(fields, _TODAY, _WINDOW_END) == "bar"


def test_due_dateがtoday_plus_91ならexcluded():
    fields = _fields(due_date=str(_TODAY + timedelta(days=91)))
    assert task_gantt._classify_task(fields, _TODAY, _WINDOW_END) == "excluded"


def test_期限超過かつtodoならbar():
    fields = _fields(status="1_todo", due_date="2026-09-01")
    assert task_gantt._classify_task(fields, _TODAY, _WINDOW_END) == "bar"


def test_期限超過かつ未知のstatusでもbar():
    fields = _fields(status="2_doing", due_date="2026-09-01")
    assert task_gantt._classify_task(fields, _TODAY, _WINDOW_END) == "bar"


def test_期限超過かつdoneならexcluded():
    fields = _fields(status="4_done", due_date="2026-09-01")
    assert task_gantt._classify_task(fields, _TODAY, _WINDOW_END) == "excluded"


def test_statusがcancelなら期間条件を満たしていても常にcancelled():
    fields = _fields(status="5_cancel", due_date="2026-09-24")
    assert task_gantt._classify_task(fields, _TODAY, _WINDOW_END) == "cancelled"


def test_start_dateがdue_dateより後ならunscheduled():
    fields = _fields(start_date="2026-09-24", due_date="2026-09-01")
    assert task_gantt._classify_task(fields, _TODAY, _WINDOW_END) == "unscheduled"


def test_start_date未設定かつdue_dateが期間外でもunscheduled():
    fields = _fields(start_date="", due_date=str(_TODAY + timedelta(days=100)))
    assert task_gantt._classify_task(fields, _TODAY, _WINDOW_END) == "unscheduled"


# --- _scan_task_paths / _read_task_fields ---


def test_scan_task_pathsはprojectsとareasの両方を走査する():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        project_tasks_dir = vault_root / "20_Projects" / "SampleProject" / "Tasks"
        project_tasks_dir.mkdir(parents=True)
        (project_tasks_dir / "task1.md").write_text(
            _TASK_TEMPLATE.format(
                status="1_todo",
                start_date="2026-09-01",
                due_date="2026-09-24",
                title="task1",
            ),
            encoding="utf-8",
        )

        area_tasks_dir = vault_root / "30_Areas" / "Tasks"
        area_tasks_dir.mkdir(parents=True)
        (area_tasks_dir / "task2.md").write_text(
            _TASK_TEMPLATE.format(
                status="1_todo",
                start_date="2026-09-01",
                due_date="2026-09-24",
                title="task2",
            ),
            encoding="utf-8",
        )

        paths = task_gantt._scan_task_paths(vault_root)
        stems = {path.stem for path in paths}
        assert stems == {"task1", "task2"}


def test_read_task_fieldsはtype以外なNoneを返す():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        path = vault_root / "meeting.md"
        path.write_text(_MEETING_TEMPLATE, encoding="utf-8")
        assert task_gantt._read_task_fields(path) is None


def test_read_task_fieldsは読み込みエラーでNoneを返す():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        dir_path = vault_root / "not_a_file.md"
        dir_path.mkdir()
        assert task_gantt._read_task_fields(dir_path) is None


def test_read_task_fieldsは読み込みエラーで標準エラー出力に警告を出す(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        dir_path = vault_root / "not_a_file.md"
        dir_path.mkdir()
        task_gantt._read_task_fields(dir_path)
        captured = capsys.readouterr()
        assert str(dir_path) in captured.err
        assert captured.out == ""


# --- _group_by_project ---


def _task(title, project="", start_date="", due_date=""):
    return {
        "path": Path(f"{title}.md"),
        "title": title,
        "project": project,
        "status": "1_todo",
        "start_date": start_date,
        "due_date": due_date,
    }


def test_複数プロジェクトのタスクがそれぞれ別sectionに分かれる():
    bar_tasks = [
        _task("taskA", project="ProjectA", start_date="2026-09-01", due_date="2026-09-10"),
        _task("taskB", project="ProjectB", start_date="2026-09-02", due_date="2026-09-11"),
    ]
    sections = task_gantt._group_by_project(bar_tasks, [])
    projects = [section["project"] for section in sections]
    assert projects == ["ProjectA", "ProjectB"]
    assert [t["title"] for t in sections[0]["bar_tasks"]] == ["taskA"]
    assert [t["title"] for t in sections[1]["bar_tasks"]] == ["taskB"]


def test_wikilink形式とプレーン表記が同一sectionに正規化される():
    bar_tasks = [
        _task("taskA", project="[[ProjectA]]", start_date="2026-09-01", due_date="2026-09-10"),
        _task("taskB", project="ProjectA", start_date="2026-09-02", due_date="2026-09-11"),
    ]
    sections = task_gantt._group_by_project(bar_tasks, [])
    assert len(sections) == 1
    assert sections[0]["project"] == "ProjectA"
    assert {t["title"] for t in sections[0]["bar_tasks"]} == {"taskA", "taskB"}


def test_project値が空文字列はプロジェクト外sectionに集約される():
    bar_tasks = [_task("taskA", project="", start_date="2026-09-01", due_date="2026-09-10")]
    sections = task_gantt._group_by_project(bar_tasks, [])
    assert len(sections) == 1
    assert sections[0]["project"] == task_gantt._UNSCOPED_SECTION_LABEL


def test_section順序はプロジェクト名昇順でプロジェクト外は常に末尾():
    # "プロジェクト外" の "プロ"(U+30ED) は "プンプン" の "プン"(U+30F3) より
    # 文字コード順で前に来るため、固定末尾でなければ本来はプロジェクト外が先に来る。
    bar_tasks = [
        _task("taskA", project="プンプン", start_date="2026-09-01", due_date="2026-09-10"),
        _task("taskB", project="", start_date="2026-09-02", due_date="2026-09-11"),
        _task("taskC", project="アルファ", start_date="2026-09-03", due_date="2026-09-12"),
    ]
    sections = task_gantt._group_by_project(bar_tasks, [])
    projects = [section["project"] for section in sections]
    assert projects == ["アルファ", "プンプン", task_gantt._UNSCOPED_SECTION_LABEL]


def test_同一section内でbarタスクがstart_date_due_date_titleの順にソートされる():
    bar_tasks = [
        _task("taskC", project="ProjectA", start_date="2026-09-01", due_date="2026-09-20"),
        _task("taskA", project="ProjectA", start_date="2026-09-01", due_date="2026-09-10"),
        _task("taskB", project="ProjectA", start_date="2026-08-30", due_date="2026-09-30"),
    ]
    sections = task_gantt._group_by_project(bar_tasks, [])
    titles = [t["title"] for t in sections[0]["bar_tasks"]]
    assert titles == ["taskB", "taskA", "taskC"]


def test_同一section内でunscheduledタスクがdue_dateNoneは末尾_titleの順にソートされる():
    unscheduled_tasks = [
        _task("taskC", project="ProjectA", due_date=""),
        _task("taskA", project="ProjectA", due_date="2026-09-20"),
        _task("taskB", project="ProjectA", due_date="2026-09-10"),
        _task("taskD", project="ProjectA", due_date="invalid-date"),
    ]
    sections = task_gantt._group_by_project([], unscheduled_tasks)
    titles = [t["title"] for t in sections[0]["unscheduled_tasks"]]
    assert titles == ["taskB", "taskA", "taskC", "taskD"]


def test_実在しないプロジェクト名でもエラーにならずそのままsection名として使われる():
    bar_tasks = [
        _task("taskA", project="架空プロジェクト", start_date="2026-09-01", due_date="2026-09-10")
    ]
    sections = task_gantt._group_by_project(bar_tasks, [])
    assert sections[0]["project"] == "架空プロジェクト"


# --- _escape_mermaid_label / _build_mermaid_block / _build_unscheduled_block / _build_marker_inner ---


def _bar_task(title, start_date="2026-09-01", due_date="2026-09-10", status="1_todo"):
    return {
        "path": Path(f"{title}.md"),
        "title": title,
        "project": "",
        "status": status,
        "start_date": start_date,
        "due_date": due_date,
    }


def _unscheduled_task(title, due_date=""):
    return {
        "path": Path(f"{title}.md"),
        "title": title,
        "project": "",
        "status": "1_todo",
        "start_date": "",
        "due_date": due_date,
    }


def _section(project, bar_tasks=None, unscheduled_tasks=None):
    return {
        "project": project,
        "bar_tasks": bar_tasks or [],
        "unscheduled_tasks": unscheduled_tasks or [],
    }


def test_mermaidブロックはヘッダ行を含む():
    sections = [_section("ProjectA", bar_tasks=[_bar_task("taskA")])]
    block = task_gantt._build_mermaid_block(sections)
    lines = block.splitlines()
    assert lines[0] == "```mermaid"
    assert "gantt" in lines[:4]
    assert "    dateFormat YYYY-MM-DD" in lines[:4]
    assert lines[-1] == "```"


def test_タスクバー行にstart_dateとdue_dateが含まれる():
    sections = [
        _section(
            "ProjectA",
            bar_tasks=[_bar_task("taskA", start_date="2026-09-10", due_date="2026-09-15")],
        )
    ]
    block = task_gantt._build_mermaid_block(sections)
    assert "2026-09-10" in block
    assert "2026-09-15" in block


def test_タイトルの半角コロンが全角コロンに置換される():
    sections = [_section("ProjectA", bar_tasks=[_bar_task("設計:実装")])]
    block = task_gantt._build_mermaid_block(sections)
    assert "設計：実装" in block
    assert "設計:実装" not in block


def test_タイトルにコンマを含んでいても出力が壊れない():
    sections = [
        _section(
            "ProjectA",
            bar_tasks=[
                _bar_task("設計,実装", start_date="2026-09-10", due_date="2026-09-15")
            ],
        )
    ]
    block = task_gantt._build_mermaid_block(sections)
    line = next(l for l in block.splitlines() if "設計,実装" in l)
    assert line.strip() == "設計,実装 :t1, 2026-09-10, 2026-09-15"


def test_statusがdoneならdoneタグが付く():
    sections = [_section("ProjectA", bar_tasks=[_bar_task("taskA", status="4_done")])]
    block = task_gantt._build_mermaid_block(sections)
    line = next(l for l in block.splitlines() if "taskA" in l)
    assert ":done, t1," in line


def test_statusがtodoならタグが付かない():
    sections = [_section("ProjectA", bar_tasks=[_bar_task("taskA", status="1_todo")])]
    block = task_gantt._build_mermaid_block(sections)
    line = next(l for l in block.splitlines() if "taskA" in l)
    assert ":t1," in line
    assert "done" not in line


def test_bar_tasksが空のsectionは見出しごと出力されない():
    sections = [
        _section("ProjectA", bar_tasks=[_bar_task("taskA")]),
        _section("ProjectB", bar_tasks=[]),
    ]
    block = task_gantt._build_mermaid_block(sections)
    assert "section ProjectA" in block
    assert "section ProjectB" not in block


def test_全sectionでbar_tasksが0件でもエラーにならずヘッダのみ返る():
    sections = [_section("ProjectA", bar_tasks=[]), _section("ProjectB", bar_tasks=[])]
    block = task_gantt._build_mermaid_block(sections)
    assert block.splitlines() == [
        "```mermaid",
        "gantt",
        "    dateFormat YYYY-MM-DD",
        "```",
    ]


def test_タスクIDが全体で重複しない():
    sections = [
        _section("ProjectA", bar_tasks=[_bar_task("taskA"), _bar_task("taskB")]),
        _section("ProjectB", bar_tasks=[_bar_task("taskC")]),
    ]
    block = task_gantt._build_mermaid_block(sections)
    ids = re.findall(r"\bt(\d+),", block)
    assert len(ids) == len(set(ids)) == 3


def test_build_unscheduled_blockはunscheduled_tasksが0件ならNone():
    sections = [_section("ProjectA", unscheduled_tasks=[])]
    assert task_gantt._build_unscheduled_block(sections) is None


def test_build_unscheduled_blockはdue_date未設定タスクに未設定文言を含む():
    sections = [
        _section("ProjectA", unscheduled_tasks=[_unscheduled_task("taskA", due_date="")])
    ]
    block = task_gantt._build_unscheduled_block(sections)
    assert "due: 未設定" in block
    assert "[[taskA]]" in block
    assert "project: ProjectA" in block


def test_build_marker_innerはunscheduled_blockがNoneならmermaid_blockのまま():
    mermaid_block = "```mermaid\ngantt\n```"
    result = task_gantt._build_marker_inner(mermaid_block, None)
    assert result == mermaid_block


def test_build_marker_innerはunscheduled_blockがNoneでないとき両方を含む():
    mermaid_block = "```mermaid\ngantt\n```"
    unscheduled_block = "- [[taskA]]（project: ProjectA, due: 未設定）"
    result = task_gantt._build_marker_inner(mermaid_block, unscheduled_block)
    assert "## 日程未確定タスク" in result
    assert mermaid_block in result
    assert unscheduled_block in result


# --- run() ---

_RUN_TASK_TEMPLATE = (
    "---\n"
    "type: task\n"
    'project: "{project}"\n'
    "status: {status}\n"
    "start_date: {start_date}\n"
    "due_date: {due_date}\n"
    "---\n"
    "# {title}\n"
)


def _write_task(dir_path, title, status="1_todo", start_date="", due_date="", project=""):
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{title}.md").write_text(
        _RUN_TASK_TEMPLATE.format(
            project=project, status=status, start_date=start_date, due_date=due_date, title=title
        ),
        encoding="utf-8",
    )


def _write_daily_note(vault_root, today, text):
    daily_dir = vault_root / "10_Daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    path = daily_dir / f"{today.isoformat()}.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_デイリーノートが存在しない場合はエラーで他ファイルに触れない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        (vault_root / "10_Daily").mkdir(parents=True)

        result = task_gantt.run(vault_root, today=_TODAY)

        daily_note_path = vault_root / "10_Daily" / f"{_TODAY.isoformat()}.md"
        assert result == {
            "status": "error",
            "reason": "daily_note_not_found",
            "daily_note": str(daily_note_path),
        }
        assert list((vault_root / "10_Daily").iterdir()) == []


def test_マーカーが無い場合はエラーで内容が1バイトも変わらない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        original_text = "# Daily note\n本文のみ、マーカーなし\n"
        daily_path = _write_daily_note(vault_root, _TODAY, original_text)
        original_bytes = daily_path.read_bytes()

        result = task_gantt.run(vault_root, today=_TODAY)

        assert result == {
            "status": "error",
            "reason": "gantt_marker_not_found",
            "daily_note": str(daily_path),
        }
        assert daily_path.read_bytes() == original_bytes


def test_GANTT_STARTのみでGANTT_ENDが無い場合もgantt_marker_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        original_text = f"# Daily note\n<!-- {task_gantt._GANTT_START} -->\n本文\n"
        daily_path = _write_daily_note(vault_root, _TODAY, original_text)
        original_bytes = daily_path.read_bytes()

        result = task_gantt.run(vault_root, today=_TODAY)

        assert result["status"] == "error"
        assert result["reason"] == "gantt_marker_not_found"
        assert daily_path.read_bytes() == original_bytes


def test_マーカー区間のみ書き換わり前後の本文は不変():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        before = "# Daily note\n\n## ガントチャート\n"
        after = "\n\n## メモ\n- 既存メモ\n"
        original_text = (
            f"{before}<!-- {task_gantt._GANTT_START} -->\n"
            f"（プレースホルダ）\n"
            f"<!-- {task_gantt._GANTT_END} -->{after}"
        )
        daily_path = _write_daily_note(vault_root, _TODAY, original_text)

        project_tasks_dir = vault_root / "20_Projects" / "ProjectA" / "Tasks"
        _write_task(
            project_tasks_dir,
            "taskA",
            start_date="2026-09-01",
            due_date="2026-09-24",
            project="[[ProjectA]]",
        )

        result = task_gantt.run(vault_root, today=_TODAY)

        assert result["status"] == "ok"
        new_text = daily_path.read_text(encoding="utf-8")
        assert new_text.startswith(before)
        assert new_text.endswith(after)
        assert "（プレースホルダ）" not in new_text


def test_正常時のJSONに件数が正しく入る():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        daily_path = _write_daily_note(
            vault_root,
            _TODAY,
            f"<!-- {task_gantt._GANTT_START} -->\n<!-- {task_gantt._GANTT_END} -->",
        )

        project_a = vault_root / "20_Projects" / "ProjectA" / "Tasks"
        project_b = vault_root / "20_Projects" / "ProjectB" / "Tasks"
        _write_task(
            project_a, "taskA1", start_date="2026-09-01", due_date="2026-09-24", project="[[ProjectA]]"
        )
        _write_task(project_a, "taskA2", start_date="", due_date="", project="[[ProjectA]]")
        _write_task(
            project_b, "taskB1", start_date="2026-09-01", due_date="2026-09-24", project="[[ProjectB]]"
        )

        result = task_gantt.run(vault_root, today=_TODAY)

        assert result["status"] == "ok"
        assert result["daily_note"] == str(daily_path)
        assert result["sections"] == 2
        assert result["bar_tasks"] == 2
        assert result["unscheduled_tasks"] == 1


def test_cancelledと期間外タスクはbar_unscheduledどちらにも含まれない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        daily_path = _write_daily_note(
            vault_root,
            _TODAY,
            f"<!-- {task_gantt._GANTT_START} -->\n<!-- {task_gantt._GANTT_END} -->",
        )

        tasks_dir = vault_root / "20_Projects" / "ProjectA" / "Tasks"
        _write_task(
            tasks_dir,
            "taskNormal",
            start_date="2026-09-01",
            due_date="2026-09-24",
            project="[[ProjectA]]",
        )
        _write_task(
            tasks_dir,
            "taskCancelled",
            status="5_cancel",
            start_date="2026-09-01",
            due_date="2026-09-24",
            project="[[ProjectA]]",
        )
        _write_task(
            tasks_dir,
            "taskExcluded",
            start_date="2026-09-01",
            due_date=str(_TODAY + timedelta(days=91)),
            project="[[ProjectA]]",
        )

        result = task_gantt.run(vault_root, today=_TODAY)

        assert result["status"] == "ok"
        assert result["bar_tasks"] == 1
        assert result["unscheduled_tasks"] == 0

        new_text = daily_path.read_text(encoding="utf-8")
        marker_inner = vault_lib.get_marker_block(
            new_text, task_gantt._GANTT_START, task_gantt._GANTT_END
        )
        assert "taskNormal" in marker_inner
        assert "taskCancelled" not in marker_inner
        assert "taskExcluded" not in marker_inner


def test_タスクが0件でもエラーにならずヘッダのみのMermaidブロックになる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        daily_path = _write_daily_note(
            vault_root,
            _TODAY,
            f"<!-- {task_gantt._GANTT_START} -->\n<!-- {task_gantt._GANTT_END} -->",
        )

        result = task_gantt.run(vault_root, today=_TODAY)

        assert result == {
            "status": "ok",
            "daily_note": str(daily_path),
            "sections": 0,
            "bar_tasks": 0,
            "unscheduled_tasks": 0,
        }
        new_text = daily_path.read_text(encoding="utf-8")
        marker_inner = vault_lib.get_marker_block(
            new_text, task_gantt._GANTT_START, task_gantt._GANTT_END
        )
        assert marker_inner.splitlines() == [
            "```mermaid",
            "gantt",
            "    dateFormat YYYY-MM-DD",
            "```",
        ]


def test_today引数で期間フィルタの基準が変わる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        marker_only = f"<!-- {task_gantt._GANTT_START} -->\n<!-- {task_gantt._GANTT_END} -->"
        _write_daily_note(vault_root, date(2026, 9, 24), marker_only)
        _write_daily_note(vault_root, date(2026, 1, 1), marker_only)

        tasks_dir = vault_root / "20_Projects" / "ProjectA" / "Tasks"
        # due_date=2026-09-24 は today=2026-09-24 なら期間内(bar)、
        # today=2026-01-01 なら期間外かつ未経過のためexcluded。
        _write_task(
            tasks_dir, "taskA", start_date="2026-09-01", due_date="2026-09-24", project="[[ProjectA]]"
        )

        result_in_window = task_gantt.run(vault_root, today=date(2026, 9, 24))
        assert result_in_window["bar_tasks"] == 1

        result_out_of_window = task_gantt.run(vault_root, today=date(2026, 1, 1))
        assert result_out_of_window["bar_tasks"] == 0


def test_2回連続実行しても結果が同一で冪等():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        daily_path = _write_daily_note(
            vault_root,
            _TODAY,
            f"# note\n<!-- {task_gantt._GANTT_START} -->\n<!-- {task_gantt._GANTT_END} -->\n本文\n",
        )

        tasks_dir = vault_root / "20_Projects" / "ProjectA" / "Tasks"
        _write_task(
            tasks_dir, "taskA", start_date="2026-09-01", due_date="2026-09-24", project="[[ProjectA]]"
        )

        result1 = task_gantt.run(vault_root, today=_TODAY)
        text_after_first = daily_path.read_text(encoding="utf-8")

        result2 = task_gantt.run(vault_root, today=_TODAY)
        text_after_second = daily_path.read_text(encoding="utf-8")

        assert result1["status"] == result2["status"] == "ok"
        assert text_after_first == text_after_second


# --- CLI tests ---


def _run(vault_root, *extra_args):
    """subprocess経由でtask_gantt.pyのCLIを実行するヘルパー。"""
    script_path = Path(__file__).resolve().parent.parent / "task_gantt.py"
    return subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--vault-root",
            str(vault_root),
            *extra_args,
        ],
        capture_output=True,
        text=True,
    )


def test_CLI経由で正常系を実行すると標準出力にstatus_okのJSONが出力され終了コードが0():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        marker_only = f"<!-- {task_gantt._GANTT_START} -->\n<!-- {task_gantt._GANTT_END} -->"
        _write_daily_note(vault_root, _TODAY, marker_only)

        result = _run(vault_root)

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["status"] == "ok"


def test_CLI_today引数を指定すると基準日が変わる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        marker_only = f"<!-- {task_gantt._GANTT_START} -->\n<!-- {task_gantt._GANTT_END} -->"
        _write_daily_note(vault_root, date(2026, 9, 24), marker_only)
        _write_daily_note(vault_root, date(2026, 1, 1), marker_only)

        tasks_dir = vault_root / "20_Projects" / "ProjectA" / "Tasks"
        # due_date=2026-09-24 は today=2026-09-24 なら期間内(bar=1)、
        # today=2026-01-01 なら期間外(bar=0)。
        _write_task(
            tasks_dir, "taskA", start_date="2026-09-01", due_date="2026-09-24", project="[[ProjectA]]"
        )

        result1 = _run(vault_root, "--today", "2026-09-24")
        assert result1.returncode == 0
        output1 = json.loads(result1.stdout)
        assert output1["bar_tasks"] == 1

        result2 = _run(vault_root, "--today", "2026-01-01")
        assert result2.returncode == 0
        output2 = json.loads(result2.stdout)
        assert output2["bar_tasks"] == 0


def test_CLI_today引数に不正な形式を渡すと終了コードが1でstatus_errorが返る():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        marker_only = f"<!-- {task_gantt._GANTT_START} -->\n<!-- {task_gantt._GANTT_END} -->"
        daily_path = _write_daily_note(vault_root, date(2026, 9, 24), marker_only)
        original_bytes = daily_path.read_bytes()

        result = _run(vault_root, "--today", "2026/09/24")

        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output["status"] == "error"
        assert output["reason"] == "invalid_today"
        # Vaultのファイルが変更されていないことを確認
        assert daily_path.read_bytes() == original_bytes


def test_CLIで実行時のエラーケースが終了コード1で返される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        # デイリーノートが無い状態でCLI実行
        result = _run(vault_root, "--today", "2026-09-24")

        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output["status"] == "error"
        assert output["reason"] == "daily_note_not_found"
