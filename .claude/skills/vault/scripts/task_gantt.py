"""Obsidian Vault用 Claude Codeプラグイン「vault」の task-gantt スキル本体。

タスクノートを走査し、期間・ステータスに応じてガントチャート表示用に
分類する。このモジュールは走査・分類・グルーピング・Mermaid生成・run()
（当日デイリーノートへの統合・書き込み）に加え、CLIエントリーポイント
main()（argparse）までを実装する。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import vault_lib

# ガントチャートに表示する期間(今日から何日先まで)
_WINDOW_DAYS = 90

# project値が空文字列の場合に集約するsection名
_UNSCOPED_SECTION_LABEL = "プロジェクト外"

# デイリーノートに書き込むマーカー区間の開始/終了
_GANTT_START = "GANTT_START"
_GANTT_END = "GANTT_END"


def _scan_task_paths(vault_root: Path) -> list[Path]:
    """タスクノートの候補パスを走査する。

    close_day.py の _scan_task_review_targets と同じglobパターンを踏襲する。
    """
    paths = list(vault_root.glob("20_Projects/*/Tasks/*.md"))
    paths += list((vault_root / "30_Areas" / "Tasks").glob("*.md"))
    return paths


def _read_task_fields(path: Path) -> dict | None:
    """タスクノートを読み込み、分類に必要なfrontmatter値を取り出す。

    typeが"task"以外、または読み込みエラー(OSError)の場合はNoneを返す。
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(
            f"task-gantt: 警告: {path} の読み込みに失敗したためスキップします: {exc}",
            file=sys.stderr,
        )
        return None

    fm_text, body_text = vault_lib.split_frontmatter(text)
    if vault_lib.get_fm_value(fm_text, "type") != "task":
        return None

    progress_section = vault_lib.get_heading_section(body_text, vault_lib.PROGRESS_HEADING_PATTERN)
    todos = [
        {"label": label, "done": done}
        for label, done in vault_lib.extract_checkboxes(progress_section)
    ]

    return {
        "path": path,
        "title": path.stem,
        "project": vault_lib.get_fm_value(fm_text, "project") or "",
        "status": vault_lib.get_fm_value(fm_text, "status") or "",
        "start_date": vault_lib.get_fm_value(fm_text, "start_date") or "",
        "due_date": vault_lib.get_fm_value(fm_text, "due_date") or "",
        "todos": todos,
    }


def _parse_date(value: str) -> date | None:
    """"YYYY-MM-DD"形式の文字列をdateへ変換する。

    空文字列・不正形式(ValueError)の場合は例外を投げずNoneを返す。
    """
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _classify_task(fields: dict, today: date, window_end: date) -> str:
    """タスク1件を "cancelled"/"bar"/"unscheduled"/"excluded" のいずれかに分類する。

    due_dateが90日枠(window_end)を大きく超える場合でも、start_dateが枠内
    (start_date <= window_end、下限なし)かつstatusが4_done/5_cancel以外なら
    "bar"に含める(打ち切り表示はrun()側で行う)。ただし★で始まり★で終わる
    最終タスク(_is_final_task_titleがTrue)はこの条件の対象外とする。
    """
    if fields["status"] == "5_cancel":
        return "cancelled"

    start_date = _parse_date(fields["start_date"])
    due_date = _parse_date(fields["due_date"])
    if start_date is None or due_date is None:
        return "unscheduled"

    if start_date > due_date:
        return "unscheduled"

    if today <= due_date <= window_end:
        return "bar"

    if _is_overdue(fields, today):
        return "bar"

    if (
        not _is_final_task_title(fields["title"])
        and fields["status"] != "4_done"
        and start_date <= window_end
    ):
        return "bar"

    return "excluded"


def _is_overdue(fields: dict, today: date) -> bool:
    """タスクが期限超過(overdue)かどうかを判定する。

    _classify_taskのoverdue-bar判定条件（期限日が今日より前、かつstatusが
    4_done/5_cancel以外）と同一の式を独立関数として持つ。due_dateが未設定・
    不正形式でNoneになる場合はFalseを返す。
    """
    due_date = _parse_date(fields["due_date"])
    if due_date is None:
        return False
    return due_date < today and fields["status"] not in ("4_done", "5_cancel")


def _is_late_start(fields: dict, today: date) -> bool:
    """タスクの開始日が今日以前かどうかを判定する(色判定専用)。

    statusが"1_todo"、かつstart_dateが今日以前ならTrueを返す。
    色判定専用の関数であり、_classify_taskの分類判定には使わない
    (_is_overdueと違い_classify_taskからは呼ばれない)。start_dateが
    未設定・不正形式でNoneになる場合はFalseを返す。
    """
    if fields["status"] != "1_todo":
        return False
    start_date = _parse_date(fields["start_date"])
    if start_date is None:
        return False
    return start_date <= today


def _is_due_today(fields: dict, today: date) -> bool:
    """タスクの期限日がちょうど今日かどうかを判定する(色判定専用)。

    _is_overdueは「due_date < today」のみを対象とし、期限当日はcrit扱いに
    ならない。当日中に着手・完了すべき緊急度を色で示すため、期限当日も
    crit系タグにする専用の判定を別関数として持つ(overdueへOR結合される)。
    _is_overdueと同じくstatusが4_done/5_cancelなら対象外。due_dateが
    未設定・不正形式でNoneになる場合はFalseを返す。
    """
    due_date = _parse_date(fields["due_date"])
    if due_date is None:
        return False
    return due_date == today and fields["status"] not in ("4_done", "5_cancel")


def _build_status_tag(status: str, overdue: bool) -> str:
    """status/overdueの組からMermaid ganttのタスクタグ文字列を決定する。

    4_done: overdueに関わらず"done"。それ以外でoverdueなら"crit"。
    非overdueは status ごとに 2_doing→"crit, active"、3_pending→"active"、
    それ以外（1_todo・未知の値）→ ""（無タグ）。
    """
    if status == "4_done":
        return "done"
    if overdue:
        return "crit"
    if status == "2_doing":
        return "crit, active"
    if status == "3_pending":
        return "active"
    return ""


def _group_by_project(bar_tasks: list[dict], unscheduled_tasks: list[dict]) -> list[dict]:
    """barタスク・unscheduledタスクをプロジェクトごとのsectionへグルーピングする。

    呼び出し元は "cancelled"/"excluded" を除外し、"bar"/"unscheduled" に分類した
    タスクをそれぞれのリストで渡す想定（本関数自身はフィルタしない）。

    各タスクのproject値は vault_lib.extract_project_name で正規化してから
    section名として使う（"[[Name]]" 形式とプレーン表記 "Name" を同一sectionに
    統合するため）。正規化後の値が空文字列なら _UNSCOPED_SECTION_LABEL に集約する。
    project値が実在するプロジェクトフォルダを指しているかの検証は行わない。

    戻り値はプロジェクト名の文字列昇順（_UNSCOPED_SECTION_LABELは常に末尾固定）で
    並んだ次の形のリスト: [{"project": str, "bar_tasks": [...], "unscheduled_tasks": [...]}, ...]
    section内、bar_tasksはstart_date, due_date, titleの昇順、unscheduled_tasksは
    due_date（Noneは末尾）, titleの昇順でそれぞれソートする。
    """
    sections: dict[str, dict] = {}

    def _section_for(project_raw: str) -> dict:
        name = vault_lib.extract_project_name(project_raw)
        key = name if name else _UNSCOPED_SECTION_LABEL
        if key not in sections:
            sections[key] = {"project": key, "bar_tasks": [], "unscheduled_tasks": []}
        return sections[key]

    for task in bar_tasks:
        _section_for(task["project"])["bar_tasks"].append(task)

    for task in unscheduled_tasks:
        _section_for(task["project"])["unscheduled_tasks"].append(task)

    for section in sections.values():
        section["bar_tasks"].sort(
            key=lambda t: (
                _parse_date(t["start_date"]) or date.min,
                _parse_date(t["due_date"]) or date.min,
                t["title"],
            )
        )
        section["unscheduled_tasks"].sort(
            key=lambda t: (
                _parse_date(t["due_date"]) is None,
                _parse_date(t["due_date"]) or date.min,
                t["title"],
            )
        )

    ordered_names = sorted(name for name in sections if name != _UNSCOPED_SECTION_LABEL)
    result = [sections[name] for name in ordered_names]
    if _UNSCOPED_SECTION_LABEL in sections:
        result.append(sections[_UNSCOPED_SECTION_LABEL])
    return result


def _escape_mermaid_label(title: str) -> str:
    """半角コロン ':' を全角コロン '：' に置換する。

    Mermaid gantt構文はタスク行を最初の':'でラベルとメタデータに分割するため、
    半角コロンを含むタイトルは構文を壊す。コンマ・改行は特別なエスケープ不要
    （行頭〜最初の':'までがラベルなのでコンマは無害。タイトルはファイル名由来で
    OS制約上改行を含み得ない）。
    """
    return title.replace(":", "：")


def _is_final_task_title(title: str) -> bool:
    """タイトルが"★"で始まり"★"で終わるかどうかを判定する(最終タスク検出用)。

    プロジェクトの「最終タスク（イベント）」を表すタイトルの検出条件。
    タイトル全体が"★"1文字だけの場合は誤検出防止のため対象外(False)とする。
    """
    return len(title) >= 2 and title.startswith("★") and title.endswith("★")


def _build_mermaid_block(sections: list[dict]) -> str:
    """グルーピング済みsectionsからMermaid ganttのコードブロック文字列を組み立てる。

    bar_tasksが1件も無いsectionは見出しごと出力しない。全section合計で
    bar_tasksが0件でもエラーにせず、ヘッダのみのコードブロックを返す。
    タスクIDはコードブロック全体で重複しない出力順の連番("t1", "t2", ...)とする。
    親タスクのstatusが"4_done"の場合、バー行自体は"done"タグ付きで表示するが、
    todoのmilestone行は出力しない(完了タスクの未完了/完了todoを表示する意味が
    薄いため)。

    タイトルが"★"で始まり"★"で終わる(_is_final_task_titleがTrue)タスクは
    プロジェクトの「最終タスク（イベント）」を表すため、通常のバー行ではなく
    milestone行のみ(due_date基準、statusが"4_done"ならdoneタグ・それ以外は
    critタグ)を出力する。todoのmilestone行出力ループは分岐せず従来通り実行する。

    タスクに"display_due_date"キーがあり実際のdue_dateと異なる場合(start_date基準の
    新条件で90日枠を超えて含まれたタスク)、バーの終端日をdisplay_due_dateへ打ち切り、
    ラベルに実際の期限を注記する("(期限: YYYY-MM-DD)")。★最終タスクはこの打ち切り・
    注記の対象外で、常にdue_dateをそのまま使う。
    """
    lines = ["```mermaid", "gantt", "    dateFormat YYYY-MM-DD"]

    task_id = 1
    for section in sections:
        bar_tasks = section["bar_tasks"]
        if not bar_tasks:
            continue
        lines.append(f"    section {section['project']}")
        for task in bar_tasks:
            if _is_final_task_title(task["title"]):
                label = _escape_mermaid_label(task["title"])
                final_tag = "done" if task["status"] == "4_done" else "crit"
                lines.append(
                    f"    {label} :{final_tag}, milestone, t{task_id}, {task['due_date']}, 0d"
                )
            else:
                display_due = task.get("display_due_date") or task["due_date"]
                label_text = task["title"]
                if display_due != task["due_date"]:
                    label_text = f"{label_text} (期限: {task['due_date']})"
                label = _escape_mermaid_label(label_text)
                tag = _build_status_tag(task["status"], task.get("overdue", False))
                status_tag = f"{tag}, " if tag else ""
                lines.append(
                    f"    {label} :{status_tag}t{task_id}, {task['start_date']}, {display_due}"
                )
            task_id += 1

            if task["status"] == "4_done":
                continue

            for todo in task.get("todos", []):
                todo_label = _escape_mermaid_label(todo["label"])
                done_tag = "done, " if todo["done"] else ""
                lines.append(
                    f"    {todo_label} :{done_tag}milestone, t{task_id}, {task['start_date']}, 0d"
                )
                task_id += 1

    lines.append("```")
    return "\n".join(lines)


def _build_unscheduled_block(sections: list[dict]) -> str | None:
    """グルーピング済みsectionsから日程未確定タスクのMarkdown箇条書き文字列を組み立てる。

    全section横断でunscheduled_tasksが1件も無ければNoneを返す。
    """
    lines = []
    for section in sections:
        for task in section["unscheduled_tasks"]:
            due = task["due_date"] or "未設定"
            lines.append(f"- [[{task['title']}]]（project: {section['project']}, due: {due}）")

    if not lines:
        return None
    return "\n".join(lines)


def _quote_for_callout(text: str) -> str:
    """Obsidianのコールアウト内に収まるよう、全行の先頭に'> 'を付与する。

    空行は'>'のみとし、末尾に余分な空白を付けない。
    """
    lines = text.split("\n")
    quoted_lines = [f"> {line}" if line else ">" for line in lines]
    return "\n".join(quoted_lines)


def _build_marker_inner(mermaid_block: str, unscheduled_block: str | None) -> str:
    """マーカー区間全体に書き込む最終文字列を組み立てる。

    unscheduled_blockがNoneならmermaid_blockをそのまま返す。Noneでなければ、
    mermaid_blockの後に空行を1行挟み、見出し行とunscheduled_blockを続ける。
    最後に、Obsidianの折りたたみ可能なコールアウト内へ収めるため、
    全行に'> 'プレフィックスを付与する。
    """
    if unscheduled_block is None:
        inner = mermaid_block
    else:
        inner = f"{mermaid_block}\n\n## 日程未確定タスク\n{unscheduled_block}"
    return _quote_for_callout(inner)


def run(vault_root: Path, today: date | None = None) -> dict:
    """task-gantt スキル本体。当日デイリーノートのマーカー区間へガントチャートを書き込む。

    デイリーノートが存在しない、またはGANTT_START/GANTT_ENDマーカーが
    存在しない場合はファイルへ一切書き込まずエラーを返す(R16の対象外)。
    それ以外のI/Oエラー(書き込み権限不足等)は捕捉せず、未処理例外のまま
    呼び出し元に伝播させる(R16)。
    """
    today = today or date.today()
    window_end = today + timedelta(days=_WINDOW_DAYS)

    daily_note_path = vault_root / "10_Daily" / f"{today.isoformat()}.md"
    if not daily_note_path.exists():
        return {
            "status": "error",
            "reason": "daily_note_not_found",
            "daily_note": str(daily_note_path),
        }

    daily_text = daily_note_path.read_text(encoding="utf-8")
    if not vault_lib.has_marker_block(daily_text, _GANTT_START, _GANTT_END):
        return {
            "status": "error",
            "reason": "gantt_marker_not_found",
            "daily_note": str(daily_note_path),
        }

    bar_tasks: list[dict] = []
    unscheduled_tasks: list[dict] = []
    for path in _scan_task_paths(vault_root):
        fields = _read_task_fields(path)
        if fields is None:
            continue
        category = _classify_task(fields, today, window_end)
        if category == "bar":
            due_date = _parse_date(fields["due_date"])
            if due_date is not None and due_date > window_end:
                # start_date基準の新条件で含まれたタスク。実due_dateはoverdue判定用に
                # そのまま保持し、表示専用のdisplay_due_dateにwindow_endを別キーで持たせる。
                fields["display_due_date"] = window_end.isoformat()
            fields["overdue"] = (
                _is_overdue(fields, today)
                or _is_late_start(fields, today)
                or _is_due_today(fields, today)
            )
            bar_tasks.append(fields)
        elif category == "unscheduled":
            unscheduled_tasks.append(fields)

    sections = _group_by_project(bar_tasks, unscheduled_tasks)
    mermaid_block = _build_mermaid_block(sections)
    unscheduled_block = _build_unscheduled_block(sections)
    inner = _build_marker_inner(mermaid_block, unscheduled_block)

    new_text = vault_lib.set_marker_block(daily_text, _GANTT_START, _GANTT_END, inner)
    daily_note_path.write_text(new_text, encoding="utf-8")

    return {
        "status": "ok",
        "daily_note": str(daily_note_path),
        "sections": len(sections),
        "bar_tasks": sum(len(section["bar_tasks"]) for section in sections),
        "unscheduled_tasks": sum(len(section["unscheduled_tasks"]) for section in sections),
    }


def main(argv: list[str] | None = None) -> int:
    """task-gantt スキルのCLIエントリーポイント。

    --vault-root: VAULT_ROOTを上書きする(テスト容易性のため)。省略時はvault_lib.VAULT_ROOTを使う。
    --today: 基準日をYYYY-MM-DD形式で上書きする(テスト・動作確認用)。省略時はシステムのローカル日付を使う。

    --today が指定された場合、date.fromisoformat(args.today) でパースする。
    ValueError（不正な形式）が発生した場合は、run()を呼ばずに
    print(json.dumps({"status": "error", "reason": "invalid_today"}, ensure_ascii=False))
    を出力し、1 を返す。

    戻り値: result["status"] == "ok" なら 0、それ以外なら 1。
    """
    parser = argparse.ArgumentParser(description="task-gantt スキル: タスクガントチャート生成")
    parser.add_argument(
        "--vault-root",
        default=None,
        help="VAULT_ROOTを上書きする(テスト容易性のため)。省略時はvault_lib.VAULT_ROOTを使う。",
    )
    parser.add_argument(
        "--today",
        default=None,
        help="基準日をYYYY-MM-DD形式で上書きする(テスト・動作確認用)。省略時はシステムのローカル日付を使う。",
    )
    args = parser.parse_args(argv)

    vault_root = Path(args.vault_root) if args.vault_root else vault_lib.VAULT_ROOT

    today = None
    if args.today is not None:
        try:
            today = date.fromisoformat(args.today)
        except ValueError:
            print(json.dumps({"status": "error", "reason": "invalid_today"}, ensure_ascii=False))
            return 1

    result = run(vault_root, today=today)
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["status"] == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
