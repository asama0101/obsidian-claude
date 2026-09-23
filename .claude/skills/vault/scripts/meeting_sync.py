"""Google Calendar（将来的にはMicrosoft 365も）の予定と議事録ノートを同期するスクリプト。

`--events-json <path>` で渡されたJSONファイル（`{"events": [...]}` または
イベント配列そのもの。呼び出し元は本日1日分のみを渡す想定）を読み込み、
各イベントについて:

- 出席者が1人以下（自分のみ）の予定は新規ノートを作らずスキップする
  （既存ノート対応済みの予定であれば `attendance` を `3_skip` にする。
  定例は本文へ `(キャンセル)` 注記も追加する）。
- 単発予定（`recurringEventId` キー無し）は `Meeting_Template.md` を
  ベースに新規作成（`attendance: "1_scheduled"` で初期化）、または
  既存ノートの `date`/`url` を更新する。
- 定例予定（`recurringEventId` キー有り）は `Meeting_Series_Template.md` の
  `NEW_MEETING_START`/`END` ブロックを `occurrence_id` で判定しながら
  再同期・新しい回への遷移・新規作成を行う。各occurrenceの
  `attendance`/`date` はブロック先頭のHTMLコメントに保持し、
  frontmatterの `attendance` は常に現在有効なoccurrenceの値をミラーする。

同じ呼び出しの中で、既存の全会議ノートも走査する:
- 単発予定（`type: meeting`）のうち、開催日が今日で、かつ今日のevents
  一覧に対応する`calendar_event_id`が無いものは、カレンダー側で
  キャンセルされたとみなし中身を確認せず物理削除する。
- `attendance` が `1_scheduled` のまま開催日を過ぎたノート（単発・定例
  とも）は `needs_attendance_check` として報告する。呼び出し元はこれを
  ユーザーに確認し、`--set-attendance` で結果を反映する。
- `attendance` が `2_done`/`3_skip`（確定済み）なのに未チェックの
  アクションアイテムが残っているノート（単発・定例とも、日付は問わず
  全件対象）は `needs_task_check` として報告する。`--set-attendance`
  を経由せずObsidian上で手動編集されたノート等、task化フローが
  一度も提示されないまま放置されるのを防ぐための検出。

結果は `{"created": [...], "updated": [...], "skipped_single_attendee": [...],
"cancelled": [...], "no_project": [...], "deleted": [...],
"needs_attendance_check": [...], "needs_task_check": [...]}` の形で
JSONとしてstdoutへ出力する。`no_project` は新規作成されたノートのうち
projectが自動推定できなかったものの `{"note_path": ..., "title": ...}`
一覧。`needs_attendance_check`/`needs_task_check` も同じ形。

以下は`--events-json`と排他の別モードとして動作する:
- `--set-project <note_path> --project <value>`: frontmatter `project`
  欄を書き換え、新しいproject値が指す`20_Projects/<Name>/Meetings/`
  または`30_Areas/Meetings/`へノートを移動する。
- `--set-attendance <note_path> --attendance <value>`: frontmatter
  `attendance`欄（定例は現在有効なoccurrenceブロックのコメントも）を
  書き換える。
- `--link-task <note_path> --item-text <text> --task-note <name>
  [--item-index <n>]`: アクションアイテムセクション内、`--item-text`に
  一致する行のうち`--item-index`番目（0始まり、省略時0）の出現を
  `- [ ] [[<name>]]`へ完全置換する（チェックボックスは未チェックのまま）。
  `--task-note`は必須。
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
from pathlib import Path

import vault_lib

# 定例予定ノートの occurrenceメタコメント（occurrence_id/attendance/date を
# 同じ行に持つ）を読み取る正規表現。NEW_MEETING_START マーカーを含む全文
# （_get_occurrence_meta呼び出し時）にも、マーカーを除去済みのブロック内容
# （_set_occurrence_meta呼び出し時。get_marker_blockはマーカー行自体を
# 結果に含めない）にも対応できるよう、マーカー行の有無に依存せず
# 「occurrence_id: "..." で始まるコメント」自体を直接探す。
_OCCURRENCE_COMMENT_RE = re.compile(r'<!-- (occurrence_id: "[^"]*"[^>]*?) -->')
_META_FIELD_RE = re.compile(r'(\w+): "([^"]*)"')

# 本文冒頭の `# タイトル` 見出し行を読み取る正規表現
_TITLE_RE = re.compile(r"^# (.+)$", re.MULTILINE)

# 定例予定ノート本文の「開催日時」行を組み立てるためのテンプレート断片
_MEETING_DATETIME_LINE_TEMPLATE = (
    "{{date:YYYY-MM-DD}} (<span>{{date:ddd}}</span>) {{time:HH:mm}} 〜"
)

_CANCEL_NOTE = "**(キャンセル)**"

# `## ⚡ アクションアイテム` または `### ⚡ アクションアイテム（今回）` の見出し行
# (task_extract.pyと同一パターン。スクリプト間でimportし合わない既存規約のため
# 個別定義とする)
_ACTION_ITEM_HEADING_PATTERN = re.compile(
    r"^#{2,3} ⚡ アクションアイテム(?:（今回）)?[ \t]*$", re.MULTILINE
)
# `- [ ] 本文` 形式のチェックボックス行(task_extract.pyと同一パターン)
_CHECKBOX_PATTERN = re.compile(r"^- \[ \] ?(.*)$", re.MULTILINE)
# --link-taskによる完全置換後の行（本文が[[タスクノート名]]のみ）を判定する。
_TASK_LINK_ONLY_PATTERN = re.compile(r"^\[\[.+\]\]$")


def _save_note(path: Path, fm_text: str, body_text: str) -> None:
    path.write_text(f"---\n{fm_text}\n---\n{body_text}", encoding="utf-8")


def _parse_dt(dt_str: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(dt_str)


def _format_duration(start_dt: datetime.datetime, end_dt: datetime.datetime) -> str:
    total_minutes = int((end_dt - start_dt).total_seconds() // 60)
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}時間{minutes}分"
    if hours:
        return f"{hours}時間"
    return f"{minutes}分"


def _format_attendees(attendees: list) -> str:
    """attendeesから自分自身(self: true)を除き、表示名(無ければメールアドレス)を
    カンマ区切りで結合する。"""
    names = []
    for attendee in attendees:
        if attendee.get("self"):
            continue
        names.append(attendee.get("displayName") or attendee.get("email", ""))
    return ", ".join(names)


def _resolve_dest_dir(vault_root: Path, project_match: str | None) -> Path:
    if project_match:
        name = vault_lib.extract_project_name(project_match)
        return vault_root / "20_Projects" / name / "Meetings"
    return vault_root / "30_Areas" / "Meetings"


def _iter_meeting_notes(vault_root: Path):
    """20_Projects配下、および30_Areas/Meetings配下の.mdファイルを走査する。"""
    bases = [vault_root / "20_Projects", vault_root / "30_Areas" / "Meetings"]
    for base in bases:
        if base.exists():
            yield from base.rglob("*.md")


def _find_note_by_fm(vault_root: Path, key: str, value: str):
    """frontmatterのkeyがvalueと一致する既存ノートを探す。

    見つかれば (path, text, fm_text, body_text) を、無ければ None を返す。
    """
    for path in _iter_meeting_notes(vault_root):
        text = path.read_text(encoding="utf-8")
        fm_text, body_text = vault_lib.split_frontmatter(text)
        if vault_lib.get_fm_value(fm_text, key) == value:
            return path, text, fm_text, body_text
    return None


# ---------------------------------------------------------------------------
# 単発予定
# ---------------------------------------------------------------------------
def _create_single_note(event: dict, vault_root: Path) -> tuple[Path, str | None]:
    start_dt = _parse_dt(event["start"]["dateTime"])
    summary = event.get("summary", "")
    description = event.get("description", "")

    template_path = vault_root / "80_Templates" / "Meeting_Template.md"
    template_text = template_path.read_text(encoding="utf-8")
    filled = vault_lib.fill_template(template_text, title=summary, dt=start_dt)
    fm_text, body_text = vault_lib.split_frontmatter(filled)
    body_text = _replace_body_line(body_text, "開催場所", event.get("location", ""))
    body_text = _replace_body_line(
        body_text, "参加者", _format_attendees(event.get("attendees", []))
    )

    project_match = vault_lib.fuzzy_project_match(
        summary + description, vault_root / "20_Projects"
    )
    fm_text = vault_lib.set_fm_value(fm_text, "project", project_match or "")
    fm_text = vault_lib.set_fm_value(fm_text, "calendar_event_id", event["id"])
    fm_text = vault_lib.set_fm_value(fm_text, "date", start_dt.strftime("%Y-%m-%d"))
    fm_text = vault_lib.set_fm_value(fm_text, "url", event.get("hangoutLink", ""))
    fm_text = vault_lib.set_fm_value(fm_text, "attendance", "1_scheduled")

    dest_dir = _resolve_dest_dir(vault_root, project_match)
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = (
        vault_lib.sanitize_filename(f"{start_dt.strftime('%Y-%m-%d')} {summary}") + ".md"
    )
    dest_path = vault_lib.unique_path(dest_dir, filename)
    _save_note(dest_path, fm_text, body_text)
    return dest_path, project_match


def _process_single_event(
    event: dict, vault_root: Path, low_attendance: bool, result: dict
) -> None:
    existing = _find_note_by_fm(vault_root, "calendar_event_id", event["id"])

    if existing is None:
        if low_attendance:
            result["skipped_single_attendee"].append(event["id"])
            return
        dest_path, project_match = _create_single_note(event, vault_root)
        result["created"].append(str(dest_path))
        if not project_match:
            result["no_project"].append(
                {"note_path": str(dest_path), "title": event.get("summary", "")}
            )
        return

    path, _text, fm_text, body_text = existing

    if low_attendance:
        fm_text = vault_lib.set_fm_value(fm_text, "attendance", "3_skip")
        _save_note(path, fm_text, body_text)
        result["cancelled"].append(str(path))
        return

    start_dt = _parse_dt(event["start"]["dateTime"])
    new_date = start_dt.strftime("%Y-%m-%d")
    new_url = event.get("hangoutLink", "")
    new_location = event.get("location", "")
    new_attendees_text = _format_attendees(event.get("attendees", []))
    old_date = vault_lib.get_fm_value(fm_text, "date")
    old_url = vault_lib.get_fm_value(fm_text, "url") or ""
    old_location = _get_body_line(body_text, "開催場所")
    old_attendees_text = _get_body_line(body_text, "参加者")

    if (
        new_date != old_date
        or new_url != old_url
        or new_location != old_location
        or new_attendees_text != old_attendees_text
    ):
        fm_text = vault_lib.set_fm_value(fm_text, "date", new_date)
        fm_text = vault_lib.set_fm_value(fm_text, "url", new_url)
        body_text = _replace_body_line(body_text, "開催場所", new_location)
        body_text = _replace_body_line(body_text, "参加者", new_attendees_text)
        _save_note(path, fm_text, body_text)
        result["updated"].append(str(path))


# ---------------------------------------------------------------------------
# 定例予定
# ---------------------------------------------------------------------------
def _get_occurrence_meta(text: str) -> dict[str, str]:
    """NEW_MEETING_START直後のコメント行からoccurrence_id/attendance/dateを辞書で返す。"""
    m = _OCCURRENCE_COMMENT_RE.search(text)
    if not m:
        return {}
    return dict(_META_FIELD_RE.findall(m.group(1)))


# _set_occurrence_metaが再構築時に補うフィールド既定値。
# occurrence_id/dateは情報が無ければ空欄のままでよいが、attendanceは
# 移行前フォーマット(occurrence_idコメントのみ、属性なし)の既存ノートを
# 書き換えた際に空文字へ壊れると、attendance=="1_scheduled"判定に
# 一致しなくなりneeds_attendance_checkが永久に検出不能になるため、
# 未設定時は「未確認」を意味する1_scheduledへ補う。
_OCCURRENCE_META_DEFAULTS = {"occurrence_id": "", "attendance": "1_scheduled", "date": ""}


def _set_occurrence_meta(text: str, **fields: str) -> str:
    """occurrenceメタコメントのfieldsを更新し、occurrence_id/attendance/dateの順で再構築する。"""
    m = _OCCURRENCE_COMMENT_RE.search(text)
    if not m:
        return text
    current = dict(_META_FIELD_RE.findall(m.group(1)))
    current.update(fields)
    new_inner = " ".join(
        f'{key}: "{current.get(key) or _OCCURRENCE_META_DEFAULTS[key]}"'
        for key in ("occurrence_id", "attendance", "date")
    )
    return text[: m.start(1)] + new_inner + text[m.end(1) :]


def _get_occurrence_id(text: str) -> str | None:
    return _get_occurrence_meta(text).get("occurrence_id") or None


def _get_note_title(body_text: str) -> str:
    m = _TITLE_RE.search(body_text)
    return m.group(1) if m else ""


def _replace_body_line(inner: str, label: str, new_value: str) -> str:
    """`- **{label}:** ...` 行の値部分を new_value に置換する。

    テンプレート側の元の行にラベル直後のスペースが有る/無いにかかわらず、
    new_value が空でなければ常にラベルと値の間を1スペースで揃える。
    """
    pattern = re.compile(rf"(^- \*\*{re.escape(label)}:\*\*) ?.*$", re.MULTILINE)
    suffix = f" {new_value}" if new_value else ""
    return pattern.sub(lambda m: m.group(1) + suffix, inner, count=1)


def _get_body_line(text: str, label: str) -> str:
    """`- **{label}:** ...` 行の現在値を取得する（_replace_body_lineの読み取り版）。

    該当行が無ければ空文字列を返す。
    """
    pattern = re.compile(rf"^- \*\*{re.escape(label)}:\*\* ?(.*)$", re.MULTILINE)
    m = pattern.search(text)
    return m.group(1) if m else ""


def _check_action_item(
    scope_text: str, item_text: str, item_index: int, task_note: str
) -> str | None:
    """アクションアイテムセクション内、item_text に一致する行のうち item_index
    番目（0始まり、出現順）を `- [ ] [[task_note]]` へ完全置換する
    （チェックボックスは未チェックのまま、元の本文は残さない）。
    該当する出現が無ければNoneを返す。
    """
    span = vault_lib.find_heading_section(scope_text, _ACTION_ITEM_HEADING_PATTERN)
    if span is None:
        return None
    section_text = scope_text[span[0] : span[1]]

    pattern = re.compile(rf"^- \[ \] ?{re.escape(item_text)}$", re.MULTILINE)
    matches = list(pattern.finditer(section_text))
    if item_index >= len(matches):
        return None
    target = matches[item_index]

    new_line = f"- [ ] [[{task_note}]]"
    new_section_text = (
        section_text[: target.start()] + new_line + section_text[target.end() :]
    )

    return scope_text[: span[0]] + new_section_text + scope_text[span[1] :]


def _has_unchecked_action_items(scope_text: str) -> bool:
    """scope_text内のアクションアイテムセクションに、本文入りの未チェック行が
    1件以上あるか判定する。テンプレートのデフォルト状態である本文なしの
    空プレースホルダー行(`- [ ] `)は、実際のアクションアイテムではないため
    対象外とする。また、--link-taskで完全置換済みの行（本文が[[タスクノート名]]
    のみで構成される）は、既にタスク化され追跡されている＝消化済みとみなし
    対象外とする。
    """
    span = vault_lib.find_heading_section(scope_text, _ACTION_ITEM_HEADING_PATTERN)
    if span is None:
        return False
    section_text = scope_text[span[0] : span[1]]
    return any(
        m.group(1).strip() and not _TASK_LINK_ONLY_PATTERN.match(m.group(1).strip())
        for m in _CHECKBOX_PATTERN.finditer(section_text)
    )


def _annotate_cancelled(inner: str) -> str:
    if _CANCEL_NOTE in inner:
        return inner
    lines = inner.split("\n", 1)
    if len(lines) == 2:
        return f"{lines[0]}\n{_CANCEL_NOTE}\n{lines[1]}"
    return f"{lines[0]}\n{_CANCEL_NOTE}"


def _resync_occurrence_block(
    text: str, event: dict, start_dt: datetime.datetime, end_dt: datetime.datetime
) -> str:
    """同じoccurrence_idの再同期: 日時・場所・所要時間の行だけを置換する。"""
    inner = vault_lib.get_marker_block(text, "NEW_MEETING_START", "NEW_MEETING_END")
    dt_value = vault_lib.fill_template(
        _MEETING_DATETIME_LINE_TEMPLATE, title="", dt=start_dt
    )
    inner = _replace_body_line(inner, "開催日時", dt_value)
    inner = _replace_body_line(inner, "開催場所", event.get("location", ""))
    inner = _replace_body_line(inner, "所要時間", _format_duration(start_dt, end_dt))
    inner = _set_occurrence_meta(inner, date=start_dt.strftime("%Y-%m-%d"))
    return inner


def _fresh_occurrence_block(
    vault_root: Path, event: dict, start_dt: datetime.datetime
) -> str:
    """新しい回への遷移用に、テンプレートから空の状態のブロックを組み立てる。"""
    template_path = vault_root / "80_Templates" / "Meeting_Series_Template.md"
    template_text = template_path.read_text(encoding="utf-8")
    inner = vault_lib.get_marker_block(
        template_text, "NEW_MEETING_START", "NEW_MEETING_END"
    )
    inner = inner.replace('occurrence_id: ""', f'occurrence_id: "{event["id"]}"')
    inner = vault_lib.fill_template(inner, title="", dt=start_dt)
    inner = _replace_body_line(inner, "開催場所", event.get("location", ""))
    inner = _replace_body_line(
        inner, "参加者", _format_attendees(event.get("attendees", []))
    )
    inner = _set_occurrence_meta(inner, date=start_dt.strftime("%Y-%m-%d"))
    return inner


def _archive_block(text: str, old_inner: str) -> str:
    """現在のNEW_MEETING_START〜ENDの中身を、NEW_MEETING_END直後に退避する。"""
    end_marker_line = "<!-- NEW_MEETING_END -->"
    idx = text.find(end_marker_line)
    if idx == -1:
        return text
    insert_pos = idx + len(end_marker_line)
    return f"{text[:insert_pos]}\n\n{old_inner}\n{text[insert_pos:]}"


def _create_series_note(event: dict, vault_root: Path, today: str) -> tuple[Path, str | None]:
    start_dt = _parse_dt(event["start"]["dateTime"])
    summary = event.get("summary", "")
    description = event.get("description", "")

    template_path = vault_root / "80_Templates" / "Meeting_Series_Template.md"
    template_text = template_path.read_text(encoding="utf-8")
    filled = vault_lib.fill_template(template_text, title=summary, dt=start_dt)
    filled = filled.replace('occurrence_id: ""', f'occurrence_id: "{event["id"]}"')
    fm_text, body_text = vault_lib.split_frontmatter(filled)
    body_text = _replace_body_line(body_text, "開催場所", event.get("location", ""))
    body_text = _replace_body_line(
        body_text, "参加者", _format_attendees(event.get("attendees", []))
    )
    body_text = _set_occurrence_meta(body_text, date=start_dt.strftime("%Y-%m-%d"))

    project_match = vault_lib.fuzzy_project_match(
        summary + description, vault_root / "20_Projects"
    )
    fm_text = vault_lib.set_fm_value(fm_text, "project", project_match or "")
    fm_text = vault_lib.set_fm_value(
        fm_text, "calendar_series_id", event["recurringEventId"]
    )
    fm_text = vault_lib.set_fm_value(fm_text, "last_updated", today)
    fm_text = vault_lib.set_fm_value(fm_text, "url", event.get("hangoutLink", ""))

    dest_dir = _resolve_dest_dir(vault_root, project_match)
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = vault_lib.sanitize_filename(summary) + ".md"
    dest_path = vault_lib.unique_path(dest_dir, filename)
    _save_note(dest_path, fm_text, body_text)
    return dest_path, project_match


def _process_series_event(
    event: dict, vault_root: Path, low_attendance: bool, today: str, result: dict
) -> None:
    series_id = event["recurringEventId"]
    existing = _find_note_by_fm(vault_root, "calendar_series_id", series_id)

    if existing is None:
        if low_attendance:
            result["skipped_single_attendee"].append(event["id"])
            return
        dest_path, project_match = _create_series_note(event, vault_root, today)
        result["created"].append(str(dest_path))
        if not project_match:
            result["no_project"].append(
                {"note_path": str(dest_path), "title": event.get("summary", "")}
            )
        return

    path, text, fm_text, _body_text = existing
    current_occ = _get_occurrence_id(text)
    start_dt = _parse_dt(event["start"]["dateTime"])
    end_dt = _parse_dt(event["end"]["dateTime"])

    if current_occ == event["id"]:
        new_inner = _resync_occurrence_block(text, event, start_dt, end_dt)
        if low_attendance:
            new_inner = _annotate_cancelled(new_inner)
            new_inner = _set_occurrence_meta(new_inner, attendance="3_skip")
        new_text = vault_lib.set_marker_block(
            text, "NEW_MEETING_START", "NEW_MEETING_END", new_inner
        )
        result_bucket = "updated"
    else:
        old_inner = vault_lib.get_marker_block(
            text, "NEW_MEETING_START", "NEW_MEETING_END"
        )
        archived_text = _archive_block(text, old_inner)
        new_inner = _fresh_occurrence_block(vault_root, event, start_dt)
        if low_attendance:
            new_inner = _annotate_cancelled(new_inner)
            new_inner = _set_occurrence_meta(new_inner, attendance="3_skip")
        new_text = vault_lib.set_marker_block(
            archived_text, "NEW_MEETING_START", "NEW_MEETING_END", new_inner
        )
        result_bucket = "created"

    fm_text, body_text = vault_lib.split_frontmatter(new_text)
    fm_text = vault_lib.set_fm_value(fm_text, "last_updated", today)
    fm_text = vault_lib.set_fm_value(fm_text, "url", event.get("hangoutLink", ""))
    current_meta = _get_occurrence_meta(body_text)
    fm_text = vault_lib.set_fm_value(
        fm_text, "attendance", current_meta.get("attendance", "1_scheduled")
    )
    _save_note(path, fm_text, body_text)
    result[result_bucket].append(str(path))


# ---------------------------------------------------------------------------
# 削除・開催確認スキャン
# ---------------------------------------------------------------------------
def _scan_stale_and_pending(
    vault_root: Path, seen_event_ids: set[str], today: str
) -> tuple[list[str], list[dict], list[dict]]:
    """全会議ノートを1回走査し、
    (削除対象パス一覧, needs_attendance_check一覧, needs_task_check一覧) を返す。

    削除は単発予定(type: meeting)のみ対象。開催日(date)が今日で、かつ今日の
    events一覧に対応するcalendar_event_idが無いノートに限定する(先読み廃止に
    より、開催日が過去のノートは二度と今日のevents一覧に現れないため、そちら
    を削除条件に含めると開催確認前に消えてしまう)。

    needs_attendance_check と needs_task_check は同一ノートに同時計上されない
    (if/elifで相互排他)。attendanceが"1_scheduled"のノートは定義上まだ未確定
    なのでneeds_task_check対象になり得ず、両者の判定条件はそもそも重ならない
    が、意図を明示するためif/elifにしている。
    """
    to_delete: list[str] = []
    needs_attendance: list[dict] = []
    needs_task: list[dict] = []

    for path in _iter_meeting_notes(vault_root):
        text = path.read_text(encoding="utf-8")
        fm_text, body_text = vault_lib.split_frontmatter(text)
        note_type = vault_lib.get_fm_value(fm_text, "type")

        if note_type == "meeting":
            event_id = vault_lib.get_fm_value(fm_text, "calendar_event_id")
            attendance = vault_lib.get_fm_value(fm_text, "attendance")
            date = vault_lib.get_fm_value(fm_text, "date")

            if date == today and event_id and event_id not in seen_event_ids:
                to_delete.append(str(path))
                continue

            if attendance == "1_scheduled" and date and date < today:
                needs_attendance.append(
                    {"note_path": str(path), "title": _get_note_title(body_text)}
                )
            elif attendance in ("2_done", "3_skip") and _has_unchecked_action_items(
                body_text
            ):
                needs_task.append(
                    {"note_path": str(path), "title": _get_note_title(body_text)}
                )

        elif note_type == "meeting_series":
            meta = _get_occurrence_meta(body_text)
            # attendanceキー自体が欠損している場合(一度も_set_occurrence_meta
            # を通っていない極めて古いノート)は"1_scheduled"相当として扱う。
            # _set_occurrence_meta(書き込み時)は既にこの既定値を補うが、
            # この読み取り専用スキャンでも同じ既定値を適用しないと、そうした
            # ノートがneeds_attendance_check/needs_task_checkどちらにも
            # 該当しなくなってしまう。
            occ_attendance = meta.get("attendance") or "1_scheduled"
            occ_date = meta.get("date")

            if occ_attendance == "1_scheduled" and occ_date and occ_date < today:
                needs_attendance.append(
                    {"note_path": str(path), "title": _get_note_title(body_text)}
                )
            elif occ_attendance in ("2_done", "3_skip"):
                current_block = vault_lib.get_marker_block(
                    body_text, "NEW_MEETING_START", "NEW_MEETING_END"
                )
                if _has_unchecked_action_items(current_block):
                    needs_task.append(
                        {"note_path": str(path), "title": _get_note_title(body_text)}
                    )

    return to_delete, needs_attendance, needs_task


# ---------------------------------------------------------------------------
# 全体制御
# ---------------------------------------------------------------------------
def sync_events(events: list[dict], vault_root: Path) -> dict:
    """イベント一覧をVaultへ同期し、結果集計を返す。"""
    today = datetime.date.today().isoformat()
    result: dict = {
        "created": [],
        "updated": [],
        "skipped_single_attendee": [],
        "cancelled": [],
        "no_project": [],
        "deleted": [],
        "needs_attendance_check": [],
        "needs_task_check": [],
    }

    seen_event_ids: set[str] = set()
    for event in events:
        seen_event_ids.add(event["id"])
        attendees = event.get("attendees", [])
        low_attendance = len(attendees) <= 1

        if "recurringEventId" not in event:
            _process_single_event(event, vault_root, low_attendance, result)
        else:
            _process_series_event(event, vault_root, low_attendance, today, result)

    to_delete, needs_attendance, needs_task = _scan_stale_and_pending(
        vault_root, seen_event_ids, today
    )
    deleted: list[str] = []
    for path_str in to_delete:
        try:
            Path(path_str).unlink()
        except OSError:
            # ファイルがロックされている等で削除できない場合はスキップし、
            # 他の正常な同期結果を道連れにしない。次回同期時に再試行される。
            continue
        deleted.append(path_str)
    result["deleted"] = deleted
    result["needs_attendance_check"] = needs_attendance
    result["needs_task_check"] = needs_task

    return result


def _load_events(path: Path) -> list[dict]:
    """`{"events": [...]}` またはイベント配列そのもののJSONを寛容に読み込む。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return data.get("events", [])


def _cmd_set_project(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.project is None:
        parser.error("--set-project には --project の指定が必要です")
    vault_root = Path(args.vault_root) if args.vault_root else vault_lib.VAULT_ROOT
    note_path = Path(args.set_project)

    project_match = args.project if args.project not in (None, "") else None
    if project_match:
        project_name = vault_lib.extract_project_name(project_match)
        if not (vault_root / "20_Projects" / project_name).is_dir():
            print(
                json.dumps(
                    {"status": "error", "reason": "project_not_found"}, ensure_ascii=False
                )
            )
            return 1

    text = note_path.read_text(encoding="utf-8")
    fm_text, body_text = vault_lib.split_frontmatter(text)
    fm_text = vault_lib.set_fm_value(fm_text, "project", args.project)

    dest_dir = _resolve_dest_dir(vault_root, project_match)
    dest_dir.mkdir(parents=True, exist_ok=True)

    if note_path.resolve().parent == dest_dir.resolve():
        dest_path = note_path
    else:
        dest_path = vault_lib.unique_path(dest_dir, note_path.name)

    if dest_path != note_path:
        _save_note(dest_path, fm_text, body_text)
        note_path.unlink()
    else:
        _save_note(note_path, fm_text, body_text)

    print(json.dumps({"status": "ok", "note_path": str(dest_path)}, ensure_ascii=False))
    return 0


def _cmd_set_attendance(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.attendance is None:
        parser.error("--set-attendance には --attendance の指定が必要です")
    note_path = Path(args.set_attendance)
    if not note_path.is_file():
        print(json.dumps({"status": "error", "reason": "note_not_found"}, ensure_ascii=False))
        return 1

    text = note_path.read_text(encoding="utf-8")
    fm_text, body_text = vault_lib.split_frontmatter(text)
    note_type = vault_lib.get_fm_value(fm_text, "type")

    fm_text = vault_lib.set_fm_value(fm_text, "attendance", args.attendance)
    if note_type == "meeting_series":
        body_text = _set_occurrence_meta(body_text, attendance=args.attendance)

    _save_note(note_path, fm_text, body_text)
    print(json.dumps({"status": "ok", "note_path": str(note_path)}, ensure_ascii=False))
    return 0


def _cmd_link_task(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.item_text is None:
        parser.error("--link-task には --item-text の指定が必要です")
    if not args.task_note:
        parser.error("--link-task には --task-note の指定が必要です")
    if "]]" in args.task_note or "\n" in args.task_note:
        parser.error("--task-note に ']]' や改行を含めることはできません")
    note_path = Path(args.link_task)
    if not note_path.is_file():
        print(json.dumps({"status": "error", "reason": "note_not_found"}, ensure_ascii=False))
        return 1

    text = note_path.read_text(encoding="utf-8")
    fm_text, body_text = vault_lib.split_frontmatter(text)
    note_type = vault_lib.get_fm_value(fm_text, "type")

    if note_type == "meeting_series":
        scope_text = vault_lib.get_marker_block(
            body_text, "NEW_MEETING_START", "NEW_MEETING_END"
        )
    else:
        scope_text = body_text

    new_scope_text = _check_action_item(
        scope_text, args.item_text, args.item_index, args.task_note
    )
    if new_scope_text is None:
        print(json.dumps({"status": "error", "reason": "item_not_found"}, ensure_ascii=False))
        return 1

    if note_type == "meeting_series":
        body_text = vault_lib.set_marker_block(
            body_text, "NEW_MEETING_START", "NEW_MEETING_END", new_scope_text
        )
    else:
        body_text = new_scope_text

    _save_note(note_path, fm_text, body_text)
    print(json.dumps({"status": "ok", "note_path": str(note_path)}, ensure_ascii=False))
    return 0


def _cmd_sync(args: argparse.Namespace) -> int:
    vault_root = Path(args.vault_root) if args.vault_root else vault_lib.VAULT_ROOT
    events = _load_events(Path(args.events_json))
    result = sync_events(events, vault_root)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Google Calendarの予定と議事録ノートを同期する。"
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--events-json", help="イベント一覧を含むJSONファイルのパス"
    )
    mode_group.add_argument(
        "--set-project", help="project欄のみを書き換える対象ノートのパス"
    )
    mode_group.add_argument(
        "--set-attendance", help="attendance欄のみを書き換える対象ノートのパス"
    )
    mode_group.add_argument(
        "--link-task",
        help="アクションアイテムの該当行をタスクノートへの[[リンク]]へ置換する対象ノートのパス",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="--set-project使用時に設定するproject欄の値（例: '[[Name]]'。解除時は空文字列 ''）",
    )
    parser.add_argument(
        "--attendance",
        default=None,
        choices=["1_scheduled", "2_done", "3_skip"],
        help="--set-attendance使用時に設定するattendanceの値",
    )
    parser.add_argument(
        "--item-text",
        default=None,
        help="--link-task使用時、チェックする元のアクションアイテム本文（完全一致）",
    )
    parser.add_argument(
        "--task-note",
        default=None,
        help="--link-task使用時、リンクするタスクノート名（必須。該当行を[[task-note]]へ完全置換する）",
    )
    parser.add_argument(
        "--item-index",
        type=int,
        default=0,
        help=(
            "--link-task使用時、同一テキストが複数ある場合の出現順インデックス"
            "（0始まり、省略時は0=最初の一致）"
        ),
    )
    parser.add_argument(
        "--vault-root", default=None, help="Vaultルート（省略時はvault_lib.VAULT_ROOT）"
    )
    args = parser.parse_args(argv)

    if args.set_project:
        return _cmd_set_project(args, parser)
    if args.set_attendance:
        return _cmd_set_attendance(args, parser)
    if args.link_task:
        return _cmd_link_task(args, parser)
    return _cmd_sync(args)


if __name__ == "__main__":
    raise SystemExit(main())
