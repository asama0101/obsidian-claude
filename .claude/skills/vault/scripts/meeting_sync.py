"""Google Calendar（将来的にはMicrosoft 365も）の予定と議事録ノートを同期するスクリプト。

`--events-json <path>` で渡されたJSONファイル（`{"events": [...]}` または
イベント配列そのもの）を読み込み、各イベントについて:

- 出席者が1人以下（自分のみ）の予定は新規ノートを作らずスキップする
  （既存ノート対応済みの予定であれば `status: cancelled` を付ける）。
- 単発予定（`recurringEventId` キー無し）は `Meeting_Template.md` を
  ベースに新規作成、または既存ノートの `date`/`url` を更新する。
- 定例予定（`recurringEventId` キー有り）は `Meeting_Series_Template.md` の
  `NEW_MEETING_START`/`END` ブロックを `occurrence_id` で判定しながら
  再同期・新しい回への遷移・新規作成を行う。

結果は `{"created": [...], "updated": [...], "skipped_single_attendee": [...],
"cancelled": [...], "no_project": [...]}` の形でJSONとしてstdoutへ出力する。
`no_project` は新規作成されたノートのうちprojectが自動推定できなかった
ものの `{"note_path": ..., "title": ...}` 一覧。

`--set-project <note_path> --project <value>` を渡すと、指定ノートの
frontmatter `project` 欄を書き換え、新しいproject値が指す
`10_Projects/<Name>/Meetings/` または `20_Areas/Meetings/` へ
ノートを移動する別モードで動作する（`--events-json` とは排他）。
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
from pathlib import Path

import vault_lib

# 定例予定ノートの occurrence_id コメント（NEW_MEETING_START 直後）を読み取る正規表現
_OCCURRENCE_ID_RE = re.compile(
    r'<!-- NEW_MEETING_START -->\s*<!-- occurrence_id: "([^"]*)" -->'
)

# 定例予定ノート本文の「開催日時」行を組み立てるためのテンプレート断片
_MEETING_DATETIME_LINE_TEMPLATE = (
    "{{date:YYYY-MM-DD}} (<span>{{date:ddd}}</span>) {{time:HH:mm}} 〜"
)

_CANCEL_NOTE = "**(キャンセル)**"


# ---------------------------------------------------------------------------
# frontmatter補助（vault_lib.set_fm_valueは値を自動でダブルクォートするため、
# fuzzy_project_match が返す '"[[Name]]"' 形式（クォート込み）や、既存の値を
# そのまま使いたいproject欄にはvault_lib.set_fm_valueを使わず、
# クォートを付与しないこのローカル版を使う）
# ---------------------------------------------------------------------------
def _set_fm_raw(fm_text: str, key: str, raw_value: str) -> str:
    """frontmatterテキスト内の key: 行を、クォートせず raw_value でそのまま置換する。"""
    prefix = f"{key}:"
    new_line = f"{key}: {raw_value}"
    lines = fm_text.split("\n") if fm_text else []

    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = new_line
            return "\n".join(lines)

    lines.append(new_line)
    return "\n".join(lines)


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


def _extract_project_name(project_match: str) -> str:
    """fuzzy_project_match の返す '"[[Name]]"' からディレクトリ名 Name を取り出す。"""
    m = re.match(r'"\[\[(.+)\]\]"', project_match)
    return m.group(1) if m else project_match


def _resolve_dest_dir(vault_root: Path, project_match: str | None) -> Path:
    if project_match:
        name = _extract_project_name(project_match)
        return vault_root / "10_Projects" / name / "Meetings"
    return vault_root / "20_Areas" / "Meetings"


def _iter_meeting_notes(vault_root: Path):
    """10_Projects配下、および20_Areas/Meetings配下の.mdファイルを走査する。"""
    bases = [vault_root / "10_Projects", vault_root / "20_Areas" / "Meetings"]
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

    template_path = vault_root / "70_Templates" / "Meeting_Template.md"
    template_text = template_path.read_text(encoding="utf-8")
    filled = vault_lib.fill_template(template_text, title=summary, dt=start_dt)
    fm_text, body_text = vault_lib.split_frontmatter(filled)
    body_text = _replace_body_line(body_text, "開催場所", event.get("location", ""))
    body_text = _replace_body_line(
        body_text, "参加者", _format_attendees(event.get("attendees", []))
    )

    project_match = vault_lib.fuzzy_project_match(
        summary + description, vault_root / "10_Projects"
    )
    fm_text = _set_fm_raw(fm_text, "project", project_match if project_match else '""')
    fm_text = vault_lib.set_fm_value(fm_text, "calendar_event_id", event["id"])
    fm_text = vault_lib.set_fm_value(fm_text, "date", start_dt.strftime("%Y-%m-%d"))
    fm_text = vault_lib.set_fm_value(fm_text, "url", event.get("hangoutLink", ""))

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
        fm_text = vault_lib.set_fm_value(fm_text, "status", "cancelled")
        _save_note(path, fm_text, body_text)
        result["cancelled"].append(str(path))
        return

    start_dt = _parse_dt(event["start"]["dateTime"])
    new_date = start_dt.strftime("%Y-%m-%d")
    new_url = event.get("hangoutLink", "")
    old_date = vault_lib.get_fm_value(fm_text, "date")
    old_url = vault_lib.get_fm_value(fm_text, "url") or ""

    if new_date != old_date or new_url != old_url:
        fm_text = vault_lib.set_fm_value(fm_text, "date", new_date)
        fm_text = vault_lib.set_fm_value(fm_text, "url", new_url)
        _save_note(path, fm_text, body_text)
        result["updated"].append(str(path))


# ---------------------------------------------------------------------------
# 定例予定
# ---------------------------------------------------------------------------
def _get_occurrence_id(text: str) -> str | None:
    m = _OCCURRENCE_ID_RE.search(text)
    return m.group(1) if m else None


def _replace_body_line(inner: str, label: str, new_value: str) -> str:
    """`- **{label}:** ...` 行の値部分を new_value に置換する。

    テンプレート側の元の行にラベル直後のスペースが有る/無いにかかわらず、
    new_value が空でなければ常にラベルと値の間を1スペースで揃える。
    """
    pattern = re.compile(rf"(^- \*\*{re.escape(label)}:\*\*) ?.*$", re.MULTILINE)
    suffix = f" {new_value}" if new_value else ""
    return pattern.sub(lambda m: m.group(1) + suffix, inner, count=1)


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
    return inner


def _fresh_occurrence_block(
    vault_root: Path, event: dict, start_dt: datetime.datetime
) -> str:
    """新しい回への遷移用に、テンプレートから空の状態のブロックを組み立てる。"""
    template_path = vault_root / "70_Templates" / "Meeting_Series_Template.md"
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

    template_path = vault_root / "70_Templates" / "Meeting_Series_Template.md"
    template_text = template_path.read_text(encoding="utf-8")
    filled = vault_lib.fill_template(template_text, title=summary, dt=start_dt)
    filled = filled.replace('occurrence_id: ""', f'occurrence_id: "{event["id"]}"')
    fm_text, body_text = vault_lib.split_frontmatter(filled)
    body_text = _replace_body_line(body_text, "開催場所", event.get("location", ""))
    body_text = _replace_body_line(
        body_text, "参加者", _format_attendees(event.get("attendees", []))
    )

    project_match = vault_lib.fuzzy_project_match(
        summary + description, vault_root / "10_Projects"
    )
    fm_text = _set_fm_raw(fm_text, "project", project_match if project_match else '""')
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
        new_text = vault_lib.set_marker_block(
            archived_text, "NEW_MEETING_START", "NEW_MEETING_END", new_inner
        )
        result_bucket = "created"

    fm_text, body_text = vault_lib.split_frontmatter(new_text)
    fm_text = vault_lib.set_fm_value(fm_text, "last_updated", today)
    fm_text = vault_lib.set_fm_value(fm_text, "url", event.get("hangoutLink", ""))
    _save_note(path, fm_text, body_text)
    result[result_bucket].append(str(path))


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
    }

    for event in events:
        attendees = event.get("attendees", [])
        low_attendance = len(attendees) <= 1

        if "recurringEventId" not in event:
            _process_single_event(event, vault_root, low_attendance, result)
        else:
            _process_series_event(event, vault_root, low_attendance, today, result)

    return result


def _load_events(path: Path) -> list[dict]:
    """`{"events": [...]}` またはイベント配列そのもののJSONを寛容に読み込む。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return data.get("events", [])


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
    parser.add_argument(
        "--project",
        default=None,
        help="--set-project使用時に設定するproject欄の値（例: '\"[[Name]]\"' や '\"\"'）",
    )
    parser.add_argument(
        "--vault-root", default=None, help="Vaultルート（省略時はvault_lib.VAULT_ROOT）"
    )
    args = parser.parse_args(argv)

    if args.set_project:
        if args.project is None:
            parser.error("--set-project には --project の指定が必要です")
        vault_root = Path(args.vault_root) if args.vault_root else vault_lib.VAULT_ROOT
        note_path = Path(args.set_project)
        text = note_path.read_text(encoding="utf-8")
        fm_text, body_text = vault_lib.split_frontmatter(text)
        fm_text = _set_fm_raw(fm_text, "project", args.project)

        project_match = args.project if args.project not in (None, "", '""') else None
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

    vault_root = Path(args.vault_root) if args.vault_root else vault_lib.VAULT_ROOT
    events = _load_events(Path(args.events_json))
    result = sync_events(events, vault_root)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
