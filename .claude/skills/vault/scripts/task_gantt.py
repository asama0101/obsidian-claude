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

    fm_text, _ = vault_lib.split_frontmatter(text)
    if vault_lib.get_fm_value(fm_text, "type") != "task":
        return None

    return {
        "path": path,
        "title": path.stem,
        "project": vault_lib.get_fm_value(fm_text, "project") or "",
        "status": vault_lib.get_fm_value(fm_text, "status") or "",
        "start_date": vault_lib.get_fm_value(fm_text, "start_date") or "",
        "due_date": vault_lib.get_fm_value(fm_text, "due_date") or "",
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
    """タスク1件を "cancelled"/"bar"/"unscheduled"/"excluded" のいずれかに分類する。"""
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

    if due_date < today and fields["status"] not in ("4_done", "5_cancel"):
        return "bar"

    return "excluded"


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


def _build_mermaid_block(sections: list[dict]) -> str:
    """グルーピング済みsectionsからMermaid ganttのコードブロック文字列を組み立てる。

    bar_tasksが1件も無いsectionは見出しごと出力しない。全section合計で
    bar_tasksが0件でもエラーにせず、ヘッダのみのコードブロックを返す。
    タスクIDはコードブロック全体で重複しない出力順の連番("t1", "t2", ...)とする。
    """
    lines = ["```mermaid", "gantt", "    dateFormat YYYY-MM-DD"]

    task_id = 1
    for section in sections:
        bar_tasks = section["bar_tasks"]
        if not bar_tasks:
            continue
        lines.append(f"    section {section['project']}")
        for task in bar_tasks:
            label = _escape_mermaid_label(task["title"])
            done_tag = "done, " if task["status"] == "4_done" else ""
            lines.append(
                f"    {label} :{done_tag}t{task_id}, {task['start_date']}, {task['due_date']}"
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


def _build_marker_inner(mermaid_block: str, unscheduled_block: str | None) -> str:
    """マーカー区間全体に書き込む最終文字列を組み立てる。

    unscheduled_blockがNoneならmermaid_blockをそのまま返す。Noneでなければ、
    mermaid_blockの後に空行を1行挟み、見出し行とunscheduled_blockを続ける。
    """
    if unscheduled_block is None:
        return mermaid_block
    return f"{mermaid_block}\n\n## 日程未確定タスク\n{unscheduled_block}"


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
