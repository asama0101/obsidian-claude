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

_TASK_WITH_BODY_TEMPLATE = (
    "---\n"
    "type: task\n"
    'project: ""\n'
    "status: {status}\n"
    "start_date: {start_date}\n"
    "due_date: {due_date}\n"
    "---\n"
    "# {title}\n"
    "\n"
    "{body}\n"
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
    # start_dateも枠外にして新条件(start_date基準の包含)が発火しないようにし、
    # due_dateのみの境界を検証する。
    far_start = _WINDOW_END + timedelta(days=1)
    fields = _fields(start_date=str(far_start), due_date=str(_TODAY + timedelta(days=91)))
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


# --- _classify_task (start_date基準の新条件) ---


def test_due_dateが枠超でもstart_dateが枠内で未着手でなければbar():
    fields = _fields(status="1_todo", start_date="2026-09-01", due_date=str(_WINDOW_END + timedelta(days=100)))
    assert task_gantt._classify_task(fields, _TODAY, _WINDOW_END) == "bar"


def test_due_dateが枠超でstart_dateも枠外なら従来通りexcluded():
    far_start = _WINDOW_END + timedelta(days=10)
    far_due = _WINDOW_END + timedelta(days=100)
    fields = _fields(status="1_todo", start_date=str(far_start), due_date=str(far_due))
    assert task_gantt._classify_task(fields, _TODAY, _WINDOW_END) == "excluded"


def test_星付き最終タスクは新条件の対象外で従来通りexcluded():
    fields = _fields(status="1_todo", start_date="2026-09-01", due_date=str(_WINDOW_END + timedelta(days=100)))
    fields["title"] = "★イベント★"
    assert task_gantt._classify_task(fields, _TODAY, _WINDOW_END) == "excluded"


def test_新条件でもstatusがdoneなら含まれない():
    fields = _fields(status="4_done", start_date="2026-09-01", due_date=str(_WINDOW_END + timedelta(days=100)))
    assert task_gantt._classify_task(fields, _TODAY, _WINDOW_END) == "excluded"


def test_start_dateがwindow_endちょうどでも新条件でbar():
    fields = _fields(status="1_todo", start_date=str(_WINDOW_END), due_date=str(_WINDOW_END + timedelta(days=100)))
    assert task_gantt._classify_task(fields, _TODAY, _WINDOW_END) == "bar"


def test_新条件はtodo以外のstatusでも機能する():
    fields = _fields(status="2_doing", start_date="2026-09-01", due_date=str(_WINDOW_END + timedelta(days=100)))
    assert task_gantt._classify_task(fields, _TODAY, _WINDOW_END) == "bar"


def test_start_dateがwindow_endの翌日なら新条件は発火せずexcluded():
    far_start = _WINDOW_END + timedelta(days=1)
    fields = _fields(status="1_todo", start_date=str(far_start), due_date=str(_WINDOW_END + timedelta(days=100)))
    assert task_gantt._classify_task(fields, _TODAY, _WINDOW_END) == "excluded"


def test_due_dateがwindow_endを1日だけ超過してもstart_dateが枠内なら新条件でbar():
    fields = _fields(status="1_todo", start_date="2026-09-01", due_date=str(_WINDOW_END + timedelta(days=1)))
    assert task_gantt._classify_task(fields, _TODAY, _WINDOW_END) == "bar"


# --- _is_overdue ---


def test_is_overdueはtodoかつ期限超過でTrue():
    fields = _fields(status="1_todo", due_date="2026-09-01")
    assert task_gantt._is_overdue(fields, _TODAY) is True


def test_is_overdueはdoingかつ期限超過でTrue():
    fields = _fields(status="2_doing", due_date="2026-09-01")
    assert task_gantt._is_overdue(fields, _TODAY) is True


def test_is_overdueはpendingかつ期限超過でTrue():
    fields = _fields(status="3_pending", due_date="2026-09-01")
    assert task_gantt._is_overdue(fields, _TODAY) is True


def test_is_overdueはdoneなら期限超過でもFalse():
    fields = _fields(status="4_done", due_date="2026-09-01")
    assert task_gantt._is_overdue(fields, _TODAY) is False


def test_is_overdueはcancelなら期限超過でもFalse():
    fields = _fields(status="5_cancel", due_date="2026-09-01")
    assert task_gantt._is_overdue(fields, _TODAY) is False


def test_is_overdueは期限内ならFalse():
    fields = _fields(status="1_todo", due_date="2026-09-24")
    assert task_gantt._is_overdue(fields, _TODAY) is False


def test_is_overdueはdue_dateが不正形式でも例外を投げずFalse():
    fields = _fields(status="1_todo", due_date="2026/09/01")
    assert task_gantt._is_overdue(fields, _TODAY) is False


def test_is_overdueはdisplay_due_dateが設定されていても実際のdue_date基準で判定する():
    # 打ち切り表示用のdisplay_due_dateキーが未来日でも、overdue判定は実due_date基準のまま。
    fields = _fields(status="1_todo", due_date="2026-09-01")
    fields["display_due_date"] = "2027-06-01"
    assert task_gantt._is_overdue(fields, _TODAY) is True


# --- _is_late_start ---


def test_is_late_startはtodoかつstart_dateが過去でTrue():
    fields = _fields(status="1_todo", start_date="2026-09-01", due_date="2026-10-01")
    assert task_gantt._is_late_start(fields, _TODAY) is True


def test_is_late_startは対象外statusならFalse():
    fields = _fields(status="2_doing", start_date="2026-09-01", due_date="2026-10-01")
    assert task_gantt._is_late_start(fields, _TODAY) is False


def test_is_late_startはstart_dateが未来ならFalse():
    fields = _fields(status="1_todo", start_date="2026-10-01", due_date="2026-10-10")
    assert task_gantt._is_late_start(fields, _TODAY) is False


def test_is_late_startはtodoかつstart_dateが今日と同じ日でTrue():
    fields = _fields(status="1_todo", start_date=str(_TODAY), due_date="2026-10-01")
    assert task_gantt._is_late_start(fields, _TODAY) is True


def test_is_late_startはstart_dateが不正形式や空でも例外を投げずFalse():
    fields = _fields(status="1_todo", start_date="2026/09/01", due_date="2026-10-01")
    assert task_gantt._is_late_start(fields, _TODAY) is False
    fields_empty = _fields(status="1_todo", start_date="", due_date="2026-10-01")
    assert task_gantt._is_late_start(fields_empty, _TODAY) is False


# --- _is_due_today ---


def test_is_due_todayはtodoかつdue_dateが今日でTrue():
    fields = _fields(status="1_todo", due_date=str(_TODAY))
    assert task_gantt._is_due_today(fields, _TODAY) is True


def test_is_due_todayはdoingかつdue_dateが今日でTrue():
    fields = _fields(status="2_doing", due_date=str(_TODAY))
    assert task_gantt._is_due_today(fields, _TODAY) is True


def test_is_due_todayはpendingかつdue_dateが今日でTrue():
    fields = _fields(status="3_pending", due_date=str(_TODAY))
    assert task_gantt._is_due_today(fields, _TODAY) is True


def test_is_due_todayはdoneならdue_dateが今日でもFalse():
    fields = _fields(status="4_done", due_date=str(_TODAY))
    assert task_gantt._is_due_today(fields, _TODAY) is False


def test_is_due_todayはcancelならdue_dateが今日でもFalse():
    fields = _fields(status="5_cancel", due_date=str(_TODAY))
    assert task_gantt._is_due_today(fields, _TODAY) is False


def test_is_due_todayはdue_dateが今日でなければFalse():
    fields = _fields(status="1_todo", due_date="2026-09-25")
    assert task_gantt._is_due_today(fields, _TODAY) is False
    fields_future = _fields(status="1_todo", due_date="2026-09-26")
    assert task_gantt._is_due_today(fields_future, date(2026, 9, 25)) is False


def test_is_due_todayはdue_dateが不正形式でも例外を投げずFalse():
    fields = _fields(status="1_todo", due_date="2026/09/24")
    assert task_gantt._is_due_today(fields, _TODAY) is False


# --- _status_tag ---


def test_status_tagはdoneならoverdueに関わらずdone():
    assert task_gantt._build_status_tag("4_done", False) == "done"
    assert task_gantt._build_status_tag("4_done", True) == "done"


def test_status_tagはdone以外でoverdueならcrit():
    assert task_gantt._build_status_tag("1_todo", True) == "crit"
    assert task_gantt._build_status_tag("2_doing", True) == "crit"
    assert task_gantt._build_status_tag("3_pending", True) == "crit"
    assert task_gantt._build_status_tag("不明", True) == "crit"


def test_status_tagはdoingかつ期限内でcrit_active():
    assert task_gantt._build_status_tag("2_doing", False) == "crit, active"


def test_status_tagはpendingかつ期限内でactive():
    assert task_gantt._build_status_tag("3_pending", False) == "active"


def test_status_tagはtodoかつ期限内で無タグ():
    assert task_gantt._build_status_tag("1_todo", False) == ""


def test_status_tagは未知の値かつ期限内で無タグ():
    assert task_gantt._build_status_tag("不明", False) == ""


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


# --- _read_task_fields (todos抽出) ---


def _write_task_with_body(vault_root, title, body, status="1_todo", start_date="2026-09-01", due_date="2026-09-24"):
    path = vault_root / f"{title}.md"
    path.write_text(
        _TASK_WITH_BODY_TEMPLATE.format(
            status=status, start_date=start_date, due_date=due_date, title=title, body=body
        ),
        encoding="utf-8",
    )
    return path


def test_read_task_fieldsは進捗メモの完了未完了チェックボックスをtodosに抽出する():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        body = "## 📌 進捗メモ\n- [x] 完了タスク\n- [ ] 未完了タスク\n"
        path = _write_task_with_body(vault_root, "task1", body)
        fields = task_gantt._read_task_fields(path)
        assert fields["todos"] == [
            {"label": "完了タスク", "done": True},
            {"label": "未完了タスク", "done": False},
        ]


def test_read_task_fieldsは進捗メモ見出しが無ければtodosは空リスト():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        body = "本文のみ、進捗メモ見出しなし\n"
        path = _write_task_with_body(vault_root, "task1", body)
        fields = task_gantt._read_task_fields(path)
        assert fields["todos"] == []


def test_read_task_fieldsは空プレースホルダーのみならtodosは空リスト():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        body = "## 📌 進捗メモ\n- [ ] \n"
        path = _write_task_with_body(vault_root, "task1", body)
        fields = task_gantt._read_task_fields(path)
        assert fields["todos"] == []


def test_read_task_fieldsは進捗メモ以外のセクションのチェックボックスを無視する():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        body = (
            "## 別セクション\n"
            "- [ ] 対象外のチェックボックス\n"
            "## 📌 進捗メモ\n"
            "- [x] 対象のチェックボックス\n"
        )
        path = _write_task_with_body(vault_root, "task1", body)
        fields = task_gantt._read_task_fields(path)
        assert fields["todos"] == [{"label": "対象のチェックボックス", "done": True}]


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


_NO_OVERDUE = object()


def _bar_task(
    title,
    start_date="2026-09-01",
    due_date="2026-09-10",
    status="1_todo",
    overdue=_NO_OVERDUE,
    display_due_date=None,
):
    task = {
        "path": Path(f"{title}.md"),
        "title": title,
        "project": "",
        "status": status,
        "start_date": start_date,
        "due_date": due_date,
    }
    if overdue is not _NO_OVERDUE:
        task["overdue"] = overdue
    if display_due_date is not None:
        task["display_due_date"] = display_due_date
    return task


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


def test_statusがdoingかつ期限内ならcrit_activeタグが付く():
    sections = [
        _section(
            "ProjectA", bar_tasks=[_bar_task("taskA", status="2_doing", overdue=False)]
        )
    ]
    block = task_gantt._build_mermaid_block(sections)
    line = next(l for l in block.splitlines() if "taskA" in l)
    assert ":crit, active, t1," in line


def test_statusがdoingかつ期限超過ならcritのみタグ():
    sections = [
        _section("ProjectA", bar_tasks=[_bar_task("taskA", status="2_doing", overdue=True)])
    ]
    block = task_gantt._build_mermaid_block(sections)
    line = next(l for l in block.splitlines() if "taskA" in l)
    assert ":crit, t1," in line
    assert "active" not in line


def test_statusがpendingかつ期限内ならactiveタグが付く():
    sections = [
        _section(
            "ProjectA", bar_tasks=[_bar_task("taskA", status="3_pending", overdue=False)]
        )
    ]
    block = task_gantt._build_mermaid_block(sections)
    line = next(l for l in block.splitlines() if "taskA" in l)
    assert ":active, t1," in line


def test_statusがpendingかつ期限超過ならcritのみタグ():
    sections = [
        _section("ProjectA", bar_tasks=[_bar_task("taskA", status="3_pending", overdue=True)])
    ]
    block = task_gantt._build_mermaid_block(sections)
    line = next(l for l in block.splitlines() if "taskA" in l)
    assert ":crit, t1," in line
    assert "active" not in line


def test_statusがtodoかつ期限超過ならcritのみタグ():
    sections = [
        _section("ProjectA", bar_tasks=[_bar_task("taskA", status="1_todo", overdue=True)])
    ]
    block = task_gantt._build_mermaid_block(sections)
    line = next(l for l in block.splitlines() if "taskA" in l)
    assert ":crit, t1," in line


def test_overdueキーが無いタスクはKeyErrorにならずoverdue_Falseとして扱われる():
    # overdueキー未設定時はfields.get("overdue", False)によりFalse扱いとなる。
    # statusが2_doingの場合、overdue=Falseは"crit, active"タグになる（表参照）。
    sections = [_section("ProjectA", bar_tasks=[_bar_task("taskA", status="2_doing")])]
    block = task_gantt._build_mermaid_block(sections)
    line = next(l for l in block.splitlines() if "taskA" in l)
    assert ":crit, active, t1," in line


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


def test_todoが未完了ならタグ無しmilestone行になる():
    task = _bar_task("taskA", start_date="2026-09-01", due_date="2026-09-15")
    task["todos"] = [{"label": "サブタスク1", "done": False}]
    sections = [_section("ProjectA", bar_tasks=[task])]
    block = task_gantt._build_mermaid_block(sections)
    line = next(l for l in block.splitlines() if "サブタスク1" in l)
    assert line.strip() == "サブタスク1 :milestone, t2, 2026-09-01, 0d"


def test_todoが完了ならdoneタグ付きmilestone行になる():
    task = _bar_task("taskA", start_date="2026-09-01", due_date="2026-09-15")
    task["todos"] = [{"label": "サブタスク1", "done": True}]
    sections = [_section("ProjectA", bar_tasks=[task])]
    block = task_gantt._build_mermaid_block(sections)
    line = next(l for l in block.splitlines() if "サブタスク1" in l)
    assert line.strip() == "サブタスク1 :done, milestone, t2, 2026-09-01, 0d"


def test_milestoneの日付は親タスクのstart_dateを継承する():
    task = _bar_task("taskA", start_date="2026-11-01", due_date="2026-12-31")
    task["todos"] = [{"label": "サブタスク1", "done": False}]
    sections = [_section("ProjectA", bar_tasks=[task])]
    block = task_gantt._build_mermaid_block(sections)
    line = next(l for l in block.splitlines() if "サブタスク1" in l)
    assert "2026-11-01, 0d" in line
    assert "2026-12-31" not in line


def test_複数のtodoがそれぞれmilestone行になる():
    task = _bar_task("taskA", start_date="2026-09-01", due_date="2026-09-15")
    task["todos"] = [
        {"label": "サブタスク1", "done": False},
        {"label": "サブタスク2", "done": True},
    ]
    sections = [_section("ProjectA", bar_tasks=[task])]
    block = task_gantt._build_mermaid_block(sections)
    lines = [l.strip() for l in block.splitlines() if "サブタスク" in l]
    assert lines == [
        "サブタスク1 :milestone, t2, 2026-09-01, 0d",
        "サブタスク2 :done, milestone, t3, 2026-09-01, 0d",
    ]


def test_todoラベルの半角コロンが全角コロンに置換される():
    task = _bar_task("taskA", due_date="2026-09-15")
    task["todos"] = [{"label": "設計:実装", "done": False}]
    sections = [_section("ProjectA", bar_tasks=[task])]
    block = task_gantt._build_mermaid_block(sections)
    line = next(l for l in block.splitlines() if "設計" in l)
    assert "設計：実装" in line
    assert "設計:実装" not in line


def test_todoが無ければmilestone行は追加されない():
    task = _bar_task("taskA", due_date="2026-09-15")
    sections = [_section("ProjectA", bar_tasks=[task])]
    block = task_gantt._build_mermaid_block(sections)
    assert "milestone" not in block


def test_statusが4_doneならtodoがあってもmilestone行は追加されない():
    task = _bar_task("taskA", due_date="2026-09-15", status="4_done")
    task["todos"] = [{"label": "サブタスク1", "done": True}]
    sections = [_section("ProjectA", bar_tasks=[task])]
    block = task_gantt._build_mermaid_block(sections)
    assert "milestone" not in block


def test_タスクIDはバー行とmilestone行を通じて連番になる():
    task_a = _bar_task("taskA", due_date="2026-09-15")
    task_a["todos"] = [{"label": "サブタスク1", "done": False}]
    task_b = _bar_task("taskB", due_date="2026-09-16")
    sections = [_section("ProjectA", bar_tasks=[task_a, task_b])]
    block = task_gantt._build_mermaid_block(sections)
    ids = re.findall(r"\bt(\d+),", block)
    assert ids == ["1", "2", "3"]  # taskA=t1, サブタスク1=t2, taskB=t3


def test_is_final_task_titleは星で囲まれたタイトルでTrue():
    assert task_gantt._is_final_task_title("★旅行に行く★") is True


def test_is_final_task_titleは星が無ければFalse():
    assert task_gantt._is_final_task_title("旅行に行く") is False


def test_is_final_task_titleは片側のみ星ならFalse():
    assert task_gantt._is_final_task_title("★旅行に行く") is False


def test_is_final_task_titleは星1文字のみならFalse():
    assert task_gantt._is_final_task_title("★") is False


def test_星で囲まれたタイトルはmilestone行になりバー行は出力されない():
    task = _bar_task(
        "★旅行に行く★", start_date="2026-09-01", due_date="2026-09-10", status="1_todo"
    )
    sections = [_section("ProjectA", bar_tasks=[task])]
    block = task_gantt._build_mermaid_block(sections)
    line = next(l for l in block.splitlines() if "旅行に行く" in l)
    assert line.strip() == "★旅行に行く★ :crit, milestone, t1, 2026-09-10, 0d"
    assert "2026-09-01" not in block


def test_星で囲まれたタイトルでstatusがdoneならdoneタグのmilestone():
    task = _bar_task(
        "★定期試験を受ける★", start_date="2026-09-01", due_date="2026-09-10", status="4_done"
    )
    sections = [_section("ProjectA", bar_tasks=[task])]
    block = task_gantt._build_mermaid_block(sections)
    line = next(l for l in block.splitlines() if "定期試験" in l)
    assert line.strip() == "★定期試験を受ける★ :done, milestone, t1, 2026-09-10, 0d"


def test_星で囲まれたタスク自身のtodoも従来通りmilestone行になる():
    task = _bar_task(
        "★旅行に行く★", start_date="2026-09-01", due_date="2026-09-10", status="1_todo"
    )
    task["todos"] = [{"label": "準備をする", "done": False}]
    sections = [_section("ProjectA", bar_tasks=[task])]
    block = task_gantt._build_mermaid_block(sections)
    todo_line = next(l for l in block.splitlines() if "準備をする" in l)
    assert todo_line.strip() == "準備をする :milestone, t2, 2026-09-01, 0d"


def test_星が無い通常タスクは従来通りバー表示のまま():
    task = _bar_task(
        "旅行に行く", start_date="2026-09-01", due_date="2026-09-10", status="1_todo"
    )
    sections = [_section("ProjectA", bar_tasks=[task])]
    block = task_gantt._build_mermaid_block(sections)
    line = next(l for l in block.splitlines() if "旅行に行く" in l)
    assert line.strip() == "旅行に行く :t1, 2026-09-01, 2026-09-10"
    assert "milestone" not in line


def test_display_due_dateが設定されているとバー終端が打ち切られラベルに実期限が注記される():
    task = _bar_task(
        "taskA", start_date="2026-09-01", due_date="2027-06-01", display_due_date="2026-12-23"
    )
    sections = [_section("ProjectA", bar_tasks=[task])]
    block = task_gantt._build_mermaid_block(sections)
    line = next(l for l in block.splitlines() if "taskA" in l)
    assert line.strip().endswith("2026-09-01, 2026-12-23")
    assert "期限" in line
    assert "2027-06-01" in line


def test_display_due_date未設定なら従来通り注記なしでdue_dateがそのまま使われる():
    task = _bar_task("taskA", start_date="2026-09-01", due_date="2026-09-10")
    sections = [_section("ProjectA", bar_tasks=[task])]
    block = task_gantt._build_mermaid_block(sections)
    line = next(l for l in block.splitlines() if "taskA" in l)
    assert line.strip() == "taskA :t1, 2026-09-01, 2026-09-10"
    assert "期限" not in line


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


def test_build_marker_innerはunscheduled_blockがNoneならmermaid_blockに全行blockquoteプレフィックスを付与():
    mermaid_block = "```mermaid\ngantt\n```"
    result = task_gantt._build_marker_inner(mermaid_block, None)
    assert result == "> ```mermaid\n> gantt\n> ```"


def test_build_marker_innerはunscheduled_blockがNoneでないとき両方を含みblockquote化される():
    mermaid_block = "```mermaid\ngantt\n```"
    unscheduled_block = "- [[taskA]]（project: ProjectA, due: 未設定）"
    result = task_gantt._build_marker_inner(mermaid_block, unscheduled_block)
    assert result == (
        "> ```mermaid\n"
        "> gantt\n"
        "> ```\n"
        ">\n"
        "> ## 日程未確定タスク\n"
        "> - [[taskA]]（project: ProjectA, due: 未設定）"
    )


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
            # start_dateも枠外にして新条件(start_date基準の包含)が発火しないようにし、
            # 純粋な期間外除外を検証する。
            start_date=str(_WINDOW_END + timedelta(days=1)),
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
            "> ```mermaid",
            "> gantt",
            ">     dateFormat YYYY-MM-DD",
            "> ```",
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


def test_run経由でoverdueタスクにcritタグが反映される():
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
            "taskOverdue",
            status="1_todo",
            start_date="2026-09-01",
            due_date="2026-09-01",
            project="[[ProjectA]]",
        )

        result = task_gantt.run(vault_root, today=_TODAY)

        assert result["status"] == "ok"
        new_text = daily_path.read_text(encoding="utf-8")
        marker_inner = vault_lib.get_marker_block(
            new_text, task_gantt._GANTT_START, task_gantt._GANTT_END
        )
        line = next(l for l in marker_inner.splitlines() if "taskOverdue" in l)
        assert ":crit, t1," in line


def test_run経由でtodoかつstart_dateが過去のタスクにcritタグが反映される():
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
            "taskLateStart",
            status="1_todo",
            start_date="2026-09-01",
            due_date="2026-10-01",
            project="[[ProjectA]]",
        )

        result = task_gantt.run(vault_root, today=_TODAY)

        assert result["status"] == "ok"
        new_text = daily_path.read_text(encoding="utf-8")
        marker_inner = vault_lib.get_marker_block(
            new_text, task_gantt._GANTT_START, task_gantt._GANTT_END
        )
        line = next(l for l in marker_inner.splitlines() if "taskLateStart" in l)
        assert ":crit, t1," in line


def test_run経由でdue_dateが今日のタスクにcritタグが反映される():
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
            "taskDueToday",
            status="1_todo",
            start_date="2026-09-10",
            due_date=str(_TODAY),
            project="[[ProjectA]]",
        )

        result = task_gantt.run(vault_root, today=_TODAY)

        assert result["status"] == "ok"
        new_text = daily_path.read_text(encoding="utf-8")
        marker_inner = vault_lib.get_marker_block(
            new_text, task_gantt._GANTT_START, task_gantt._GANTT_END
        )
        line = next(l for l in marker_inner.splitlines() if "taskDueToday" in l)
        assert ":crit, t1," in line


_RUN_TASK_WITH_BODY_TEMPLATE = (
    "---\n"
    "type: task\n"
    'project: "{project}"\n'
    "status: {status}\n"
    "start_date: {start_date}\n"
    "due_date: {due_date}\n"
    "---\n"
    "# {title}\n"
    "\n"
    "## 📌 進捗メモ\n"
    "{todos}\n"
)


def _write_task_with_todos(
    dir_path, title, todos_lines, status="1_todo", start_date="", due_date="", project=""
):
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{title}.md").write_text(
        _RUN_TASK_WITH_BODY_TEMPLATE.format(
            project=project,
            status=status,
            start_date=start_date,
            due_date=due_date,
            title=title,
            todos="\n".join(todos_lines),
        ),
        encoding="utf-8",
    )


def test_run経由でtodoのmilestone行が出力される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        daily_path = _write_daily_note(
            vault_root,
            _TODAY,
            f"<!-- {task_gantt._GANTT_START} -->\n<!-- {task_gantt._GANTT_END} -->",
        )
        tasks_dir = vault_root / "20_Projects" / "ProjectA" / "Tasks"
        _write_task_with_todos(
            tasks_dir,
            "taskWithTodo",
            ["- [ ] サブタスク1"],
            start_date="2026-09-01",
            due_date="2026-09-24",
            project="[[ProjectA]]",
        )

        result = task_gantt.run(vault_root, today=_TODAY)

        assert result["status"] == "ok"
        new_text = daily_path.read_text(encoding="utf-8")
        marker_inner = vault_lib.get_marker_block(
            new_text, task_gantt._GANTT_START, task_gantt._GANTT_END
        )
        line = next(l for l in marker_inner.splitlines() if "サブタスク1" in l)
        assert "milestone" in line


def test_run経由で3_pendingステータスのタスクにactiveタグが反映される():
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
            "taskPending",
            status="3_pending",
            start_date="2026-09-01",
            due_date="2026-10-01",
            project="[[ProjectA]]",
        )

        result = task_gantt.run(vault_root, today=_TODAY)

        assert result["status"] == "ok"
        new_text = daily_path.read_text(encoding="utf-8")
        marker_inner = vault_lib.get_marker_block(
            new_text, task_gantt._GANTT_START, task_gantt._GANTT_END
        )
        line = next(l for l in marker_inner.splitlines() if "taskPending" in l)
        assert ":active, t1," in line


def test_run経由でdue_dateが枠を大きく超えてもstart_dateが枠内なら表示されバーが打ち切られ注記が付く():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        daily_path = _write_daily_note(
            vault_root,
            _TODAY,
            f"<!-- {task_gantt._GANTT_START} -->\n<!-- {task_gantt._GANTT_END} -->",
        )
        tasks_dir = vault_root / "20_Projects" / "ProjectA" / "Tasks"
        far_due = _TODAY + timedelta(days=240)  # 8ヶ月後、window_end(90日後)を大きく超える
        _write_task(
            tasks_dir,
            "taskFarFuture",
            status="1_todo",
            start_date="2026-09-01",
            due_date=str(far_due),
            project="[[ProjectA]]",
        )

        result = task_gantt.run(vault_root, today=_TODAY)

        assert result["status"] == "ok"
        assert result["bar_tasks"] == 1
        new_text = daily_path.read_text(encoding="utf-8")
        marker_inner = vault_lib.get_marker_block(
            new_text, task_gantt._GANTT_START, task_gantt._GANTT_END
        )
        line = next(l for l in marker_inner.splitlines() if "taskFarFuture" in l)
        assert line.strip().endswith(f"2026-09-01, {_WINDOW_END.isoformat()}")
        assert "期限" in line
        assert far_due.isoformat() in line


def test_run経由でstart_dateも枠外なら従来通り非表示のまま():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        daily_path = _write_daily_note(
            vault_root,
            _TODAY,
            f"<!-- {task_gantt._GANTT_START} -->\n<!-- {task_gantt._GANTT_END} -->",
        )
        tasks_dir = vault_root / "20_Projects" / "ProjectA" / "Tasks"
        far_start = _WINDOW_END + timedelta(days=10)
        far_due = _WINDOW_END + timedelta(days=100)
        _write_task(
            tasks_dir,
            "taskFarBoth",
            status="1_todo",
            start_date=str(far_start),
            due_date=str(far_due),
            project="[[ProjectA]]",
        )

        result = task_gantt.run(vault_root, today=_TODAY)

        assert result["status"] == "ok"
        assert result["bar_tasks"] == 0
        assert result["unscheduled_tasks"] == 0
        new_text = daily_path.read_text(encoding="utf-8")
        marker_inner = vault_lib.get_marker_block(
            new_text, task_gantt._GANTT_START, task_gantt._GANTT_END
        )
        assert "taskFarBoth" not in marker_inner


def test_run経由で星付き最終タスクは新条件の対象外のまま非表示():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp)
        daily_path = _write_daily_note(
            vault_root,
            _TODAY,
            f"<!-- {task_gantt._GANTT_START} -->\n<!-- {task_gantt._GANTT_END} -->",
        )
        tasks_dir = vault_root / "20_Projects" / "ProjectA" / "Tasks"
        far_due = _WINDOW_END + timedelta(days=100)
        _write_task(
            tasks_dir,
            "★イベント★",
            status="1_todo",
            start_date="2026-09-01",
            due_date=str(far_due),
            project="[[ProjectA]]",
        )

        result = task_gantt.run(vault_root, today=_TODAY)

        assert result["status"] == "ok"
        assert result["bar_tasks"] == 0
        new_text = daily_path.read_text(encoding="utf-8")
        marker_inner = vault_lib.get_marker_block(
            new_text, task_gantt._GANTT_START, task_gantt._GANTT_END
        )
        assert "イベント" not in marker_inner


def test_run経由でdue_dateが枠内のタスクは打ち切りも注記も行われない():
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
            "taskInWindow",
            status="1_todo",
            start_date="2026-09-01",
            due_date="2026-10-01",
            project="[[ProjectA]]",
        )

        result = task_gantt.run(vault_root, today=_TODAY)

        assert result["status"] == "ok"
        new_text = daily_path.read_text(encoding="utf-8")
        marker_inner = vault_lib.get_marker_block(
            new_text, task_gantt._GANTT_START, task_gantt._GANTT_END
        )
        line = next(l for l in marker_inner.splitlines() if "taskInWindow" in l)
        assert "期限" not in line
        assert line.strip().endswith("2026-09-01, 2026-10-01")


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

        result = _run(vault_root, "--today", "2026-09-24")

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
