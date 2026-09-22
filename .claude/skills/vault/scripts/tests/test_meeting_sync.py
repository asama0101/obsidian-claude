"""meeting_sync.py のユニットテスト。

pytest（`.claude/skills/vault/scripts/.venv/`のvenv限定の開発依存）を使用する。
テンプレートファイルは実際の70_Templates配下のものをテスト用一時Vaultへコピーして使う
（内容を重複転記せず、実物とのズレを防ぐため）。
"""

import contextlib
import datetime
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# scripts/ ディレクトリを import パスに追加する
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import meeting_sync  # noqa: E402
import vault_lib  # noqa: E402

REAL_TEMPLATES_DIR = vault_lib.VAULT_ROOT / "70_Templates"


def make_vault(root: Path, project_names: list[str] | None = None) -> Path:
    """テスト用の一時Vaultディレクトリを組み立てる（実テンプレートをコピー）。"""
    templates_dir = root / "70_Templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        REAL_TEMPLATES_DIR / "Meeting_Template.md", templates_dir / "Meeting_Template.md"
    )
    shutil.copy(
        REAL_TEMPLATES_DIR / "Meeting_Series_Template.md",
        templates_dir / "Meeting_Series_Template.md",
    )

    projects_dir = root / "10_Projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    for name in project_names or []:
        (projects_dir / name).mkdir(parents=True, exist_ok=True)

    (root / "20_Areas" / "Meetings").mkdir(parents=True, exist_ok=True)
    return root


def make_event(**overrides) -> dict:
    event = {
        "id": "evt1",
        "summary": "テスト会議",
        "start": {"dateTime": "2026-09-21T13:00:00+09:00", "timeZone": "Asia/Tokyo"},
        "end": {"dateTime": "2026-09-21T14:00:00+09:00", "timeZone": "Asia/Tokyo"},
        "status": "confirmed",
        "attendees": [{"email": "a@example.com"}, {"email": "b@example.com"}],
    }
    event.update(overrides)
    return event


def test_attendeesキーが無いイベントはスキップされる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event()
        del event["attendees"]
        result = meeting_sync.sync_events([event], vault_root)
        assert result["skipped_single_attendee"] == ["evt1"]
        assert result["created"] == []


def test_出席者1人のイベントはスキップされる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(attendees=[{"email": "a@example.com", "self": True}])
        result = meeting_sync.sync_events([event], vault_root)
        assert result["skipped_single_attendee"] == ["evt1"]
        assert result["created"] == []


def test_定例イベントも出席者1人ならスキップされる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(
            attendees=[{"email": "a@example.com"}], recurringEventId="series1"
        )
        result = meeting_sync.sync_events([event], vault_root)
        assert result["skipped_single_attendee"] == ["evt1"]
        assert result["created"] == []


def test_新規作成でproject推定される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp), project_names=["VaultMigration"])
        event = make_event(
            id="evt1",
            summary="VaultMigration定例MTG",
            hangoutLink="https://meet.google.com/abc-defg-hij",
        )
        result = meeting_sync.sync_events([event], vault_root)

        assert len(result["created"]) == 1
        note_path = Path(result["created"][0])
        assert note_path.exists()
        assert (
            note_path.parent == vault_root / "10_Projects" / "VaultMigration" / "Meetings"
        )

        text = note_path.read_text(encoding="utf-8")
        fm, body = vault_lib.split_frontmatter(text)
        assert vault_lib.get_fm_value(fm, "calendar_event_id") == "evt1"
        assert vault_lib.get_fm_value(fm, "project") == "[[VaultMigration]]"
        assert vault_lib.get_fm_value(fm, "date") == "2026-09-21"
        assert (
            vault_lib.get_fm_value(fm, "url") == "https://meet.google.com/abc-defg-hij"
        )
        assert "# VaultMigration定例MTG" in body


def test_project推定できない場合はAreas配下に空欄で作成():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(id="evt2", summary="関係ない打ち合わせ")
        result = meeting_sync.sync_events([event], vault_root)

        note_path = Path(result["created"][0])
        assert note_path.parent == vault_root / "20_Areas" / "Meetings"
        text = note_path.read_text(encoding="utf-8")
        fm, _body = vault_lib.split_frontmatter(text)
        assert vault_lib.get_fm_value(fm, "project") == ""


def test_日時変更が反映されユーザー記入欄は変わらない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event1 = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([event1], vault_root)
        note_path = Path(result1["created"][0])

        # ユーザーが決定事項欄に手書きした想定
        text = note_path.read_text(encoding="utf-8")
        text = text.replace("## 📝 決定事項\n- ", "## 📝 決定事項\n- 予算を確定した")
        note_path.write_text(text, encoding="utf-8")

        event2 = make_event(
            id="evt1",
            summary="定例1on1",
            start={"dateTime": "2026-09-22T15:30:00+09:00"},
            end={"dateTime": "2026-09-22T16:30:00+09:00"},
        )
        result2 = meeting_sync.sync_events([event2], vault_root)

        assert result2["updated"] == [str(note_path)]
        updated_text = note_path.read_text(encoding="utf-8")
        fm, body = vault_lib.split_frontmatter(updated_text)
        assert vault_lib.get_fm_value(fm, "date") == "2026-09-22"
        assert "予算を確定した" in body


def test_開催場所のみの変化でもupdatedになり本文が書き換わる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event1 = make_event(id="evt1", summary="定例1on1", location="会議室A")
        result1 = meeting_sync.sync_events([event1], vault_root)
        note_path = Path(result1["created"][0])

        event2 = make_event(id="evt1", summary="定例1on1", location="会議室B")
        result2 = meeting_sync.sync_events([event2], vault_root)

        assert result2["updated"] == [str(note_path)]
        updated_text = note_path.read_text(encoding="utf-8")
        assert "- **開催場所:** 会議室B" in updated_text


def test_参加者のみの変化でもupdatedになり本文が書き換わる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event1 = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([event1], vault_root)
        note_path = Path(result1["created"][0])

        event2 = make_event(
            id="evt1",
            summary="定例1on1",
            attendees=[
                {"email": "a@example.com"},
                {"email": "b@example.com"},
                {"email": "c@example.com"},
            ],
        )
        result2 = meeting_sync.sync_events([event2], vault_root)

        assert result2["updated"] == [str(note_path)]
        updated_text = note_path.read_text(encoding="utf-8")
        assert (
            "- **参加者:** a@example.com, b@example.com, c@example.com"
            in updated_text
        )


def test_変化が無ければupdatedに追加されない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([event], vault_root)
        assert len(result1["created"]) == 1

        result2 = meeting_sync.sync_events([event], vault_root)
        assert result2["updated"] == []
        assert result2["created"] == []


def test_出席者が1人に減ったらcancelledになりファイルは残る():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event1 = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([event1], vault_root)
        note_path = Path(result1["created"][0])

        event2 = make_event(
            id="evt1", summary="定例1on1", attendees=[{"email": "a@example.com"}]
        )
        result2 = meeting_sync.sync_events([event2], vault_root)

        assert result2["cancelled"] == [str(note_path)]
        assert note_path.exists()
        fm, _body = vault_lib.split_frontmatter(
            note_path.read_text(encoding="utf-8")
        )
        assert vault_lib.get_fm_value(fm, "status") is None
        assert vault_lib.get_fm_value(fm, "attendance") == "3_skip"


def test_定例イベント新規作成でseries_idとoccurrence_idが設定される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(
            id="occA", summary="週次定例", recurringEventId="seriesX"
        )
        result = meeting_sync.sync_events([event], vault_root)

        assert len(result["created"]) == 1
        note_path = Path(result["created"][0])
        text = note_path.read_text(encoding="utf-8")
        fm, body = vault_lib.split_frontmatter(text)
        assert vault_lib.get_fm_value(fm, "calendar_series_id") == "seriesX"
        assert (
            vault_lib.get_fm_value(fm, "last_updated")
            == datetime.date.today().isoformat()
        )
        assert 'occurrence_id: "occA"' in body
        assert "<!-- NEW_MEETING_START -->" in body
        assert "<!-- NEW_MEETING_END -->" in body


def _create_series(vault_root):
    event = make_event(id="occA", summary="週次定例", recurringEventId="seriesX")
    result = meeting_sync.sync_events([event], vault_root)
    return Path(result["created"][0])


def test_同一occurrenceの再同期は部分更新のみでブロックが退避されない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        note_path = _create_series(vault_root)

        # ユーザーが決定事項欄に手書きした想定
        text = note_path.read_text(encoding="utf-8")
        text = text.replace("### 📝 決定事項\n- ", "### 📝 決定事項\n- 進捗確認完了")
        note_path.write_text(text, encoding="utf-8")

        event2 = make_event(
            id="occA",
            summary="週次定例",
            recurringEventId="seriesX",
            start={"dateTime": "2026-09-21T15:00:00+09:00"},
            end={"dateTime": "2026-09-21T16:30:00+09:00"},
            location="会議室B",
        )
        result2 = meeting_sync.sync_events([event2], vault_root)

        assert result2["updated"] == [str(note_path)]
        updated_text = note_path.read_text(encoding="utf-8")

        # occurrence_id は変わらず、丸ごと置き換えられていない(手書き内容が残る)
        assert 'occurrence_id: "occA"' in updated_text
        assert "進捗確認完了" in updated_text
        assert "会議室B" in updated_text
        assert "15:00" in updated_text
        assert "1時間30分" in updated_text


def test_出席者1人以下ならブロック内にキャンセル注記が付く():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        note_path = _create_series(vault_root)

        event2 = make_event(
            id="occA",
            summary="週次定例",
            recurringEventId="seriesX",
            attendees=[{"email": "a@example.com"}],
        )
        result2 = meeting_sync.sync_events([event2], vault_root)

        assert result2["updated"] == [str(note_path)]
        updated_text = note_path.read_text(encoding="utf-8")
        assert "(キャンセル)" in updated_text


def test_新しい回への遷移で旧ブロックが退避され新ブロックに差し替わる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))

        event1 = make_event(id="occA", summary="週次定例", recurringEventId="seriesX")
        result1 = meeting_sync.sync_events([event1], vault_root)
        note_path = Path(result1["created"][0])

        # occAの回にユーザーが決定事項を手書きした想定
        text = note_path.read_text(encoding="utf-8")
        text = text.replace("### 📝 決定事項\n- ", "### 📝 決定事項\n- occA回の決定事項")
        note_path.write_text(text, encoding="utf-8")

        event2 = make_event(
            id="occB",
            summary="週次定例",
            recurringEventId="seriesX",
            start={"dateTime": "2026-09-28T13:00:00+09:00"},
            end={"dateTime": "2026-09-28T14:00:00+09:00"},
        )
        result2 = meeting_sync.sync_events([event2], vault_root)

        assert result2["created"] == [str(note_path)]
        final_text = note_path.read_text(encoding="utf-8")

        # 現在のブロックは新しいoccurrence_idに差し替わっている
        start_idx = final_text.find("<!-- NEW_MEETING_START -->")
        end_idx = final_text.find("<!-- NEW_MEETING_END -->")
        current_block = final_text[start_idx:end_idx]
        assert 'occurrence_id: "occB"' in current_block
        assert "occA回の決定事項" not in current_block

        # 旧ブロックの内容(手書き含む)はEND直後の過去ログ領域に退避されている
        archive_area = final_text[end_idx:]
        assert 'occurrence_id: "occA"' in archive_area
        assert "occA回の決定事項" in archive_area

        fm, _body = vault_lib.split_frontmatter(final_text)
        assert (
            vault_lib.get_fm_value(fm, "last_updated")
            == datetime.date.today().isoformat()
        )


def test_単発ノートのファイル名に開催日プレフィックスが付く():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(id="evt1", summary="定例1on1")
        result = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result["created"][0])
        assert note_path.name == "2026-09-21 定例1on1.md"


def test_定例ノートのファイル名に日付プレフィックスは付かない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(
            id="occA", summary="週次定例", recurringEventId="seriesX"
        )
        result = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result["created"][0])
        assert note_path.name == "週次定例.md"


def test_project推定できなければno_projectに追加される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp), project_names=["VaultMigration"])
        event = make_event(id="evt1", summary="関係ない打ち合わせ")
        result = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result["created"][0])
        assert result["no_project"] == [
            {"note_path": str(note_path), "title": "関係ない打ち合わせ"}
        ]


def test_project推定できればno_projectに追加されない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp), project_names=["VaultMigration"])
        event = make_event(id="evt1", summary="VaultMigration定例MTG")
        result = meeting_sync.sync_events([event], vault_root)
        assert result["no_project"] == []


def test_定例ノートもproject推定できなければno_projectに追加される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp), project_names=["VaultMigration"])
        event = make_event(
            id="occA", summary="週次定例", recurringEventId="seriesX"
        )
        result = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result["created"][0])
        assert result["no_project"] == [
            {"note_path": str(note_path), "title": "週次定例"}
        ]


def test_自分自身は除外される():
    attendees = [
        {"email": "me@example.com", "self": True},
        {"email": "a@example.com"},
    ]
    assert meeting_sync._format_attendees(attendees) == "a@example.com"


def test_displayNameが優先される():
    attendees = [{"email": "a@example.com", "displayName": "山田太郎"}]
    assert meeting_sync._format_attendees(attendees) == "山田太郎"


def test_displayNameが無ければemailにフォールバックする():
    attendees = [{"email": "a@example.com"}]
    assert meeting_sync._format_attendees(attendees) == "a@example.com"


def test_複数人はカンマ区切りで結合される():
    attendees = [
        {"email": "a@example.com"},
        {"displayName": "山田太郎", "email": "b@example.com"},
    ]
    assert meeting_sync._format_attendees(attendees) == "a@example.com, 山田太郎"


def test_空リストは空文字になる():
    assert meeting_sync._format_attendees([]) == ""


def test_自分だけの場合も空文字になる():
    attendees = [{"self": True, "email": "me@example.com"}]
    assert meeting_sync._format_attendees(attendees) == ""


def test_単発ノート作成時に参加者と開催場所が埋まる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(
            id="evt1",
            summary="定例1on1",
            location="会議室A",
            attendees=[
                {"email": "me@example.com", "self": True},
                {"displayName": "山田太郎", "email": "b@example.com"},
            ],
        )
        result = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result["created"][0])
        text = note_path.read_text(encoding="utf-8")
        assert "**開催場所:** 会議室A" in text
        assert "**参加者:** 山田太郎" in text


def test_定例ノート新規作成時に参加者と開催場所が埋まる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(
            id="occA",
            summary="週次定例",
            recurringEventId="seriesX",
            location="会議室B",
            attendees=[
                {"email": "me@example.com", "self": True},
                {"displayName": "鈴木花子", "email": "c@example.com"},
            ],
        )
        result = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result["created"][0])
        text = note_path.read_text(encoding="utf-8")
        assert "**開催場所:** 会議室B" in text
        assert "**参加者:** 鈴木花子" in text


def test_新しい回への遷移時に新ブロックへ参加者と開催場所が埋まり旧ブロックは変わらない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event1 = make_event(id="occA", summary="週次定例", recurringEventId="seriesX")
        result1 = meeting_sync.sync_events([event1], vault_root)
        note_path = Path(result1["created"][0])

        event2 = make_event(
            id="occB",
            summary="週次定例",
            recurringEventId="seriesX",
            start={"dateTime": "2026-09-28T13:00:00+09:00"},
            end={"dateTime": "2026-09-28T14:00:00+09:00"},
            location="会議室C",
            attendees=[{"displayName": "佐藤次郎", "email": "d@example.com"}],
        )
        meeting_sync.sync_events([event2], vault_root)

        final_text = note_path.read_text(encoding="utf-8")
        start_idx = final_text.find("<!-- NEW_MEETING_START -->")
        end_idx = final_text.find("<!-- NEW_MEETING_END -->")
        current_block = final_text[start_idx:end_idx]
        archive_area = final_text[end_idx:]

        assert "**開催場所:** 会議室C" in current_block
        assert "**参加者:** 佐藤次郎" in current_block
        # 旧ブロックは元々開催場所・参加者未設定で作成されたため変わらない
        assert "会議室C" not in archive_area
        assert "佐藤次郎" not in archive_area


def test_set_projectで指定ノートのproject欄が書き換わりプロジェクト配下へ移動する():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp), project_names=["VaultMigration"])
        event = make_event(id="evt1", summary="関係ない打ち合わせ")
        result = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result["created"][0])
        before_text = note_path.read_text(encoding="utf-8")
        before_fm, before_body = vault_lib.split_frontmatter(before_text)

        exit_code = meeting_sync.main(
            [
                "--set-project",
                str(note_path),
                "--project",
                "[[VaultMigration]]",
                "--vault-root",
                str(vault_root),
            ]
        )

        assert exit_code == 0
        assert not note_path.exists()
        dest_path = (
            vault_root / "10_Projects" / "VaultMigration" / "Meetings" / note_path.name
        )
        assert dest_path.exists()
        after_text = dest_path.read_text(encoding="utf-8")
        after_fm, after_body = vault_lib.split_frontmatter(after_text)

        assert vault_lib.get_fm_value(after_fm, "project") == "[[VaultMigration]]"
        assert vault_lib.get_fm_value(
            after_fm, "calendar_event_id"
        ) == vault_lib.get_fm_value(before_fm, "calendar_event_id")
        assert vault_lib.get_fm_value(after_fm, "date") == vault_lib.get_fm_value(
            before_fm, "date"
        )
        assert vault_lib.get_fm_value(after_fm, "url") == vault_lib.get_fm_value(
            before_fm, "url"
        )
        assert after_body == before_body


def test_set_projectのみでprojectが無ければエラー終了する():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        note_path = vault_root / "dummy.md"
        note_path.write_text('---\nproject: ""\n---\nbody', encoding="utf-8")

        with pytest.raises(SystemExit):
            meeting_sync.main(
                [
                    "--set-project",
                    str(note_path),
                    "--vault-root",
                    str(vault_root),
                ]
            )


def test_set_projectでプロジェクト解除するとAreas配下へ戻る():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp), project_names=["VaultMigration"])
        dest_dir = vault_root / "10_Projects" / "VaultMigration" / "Meetings"
        dest_dir.mkdir(parents=True, exist_ok=True)
        note_path = dest_dir / "会議.md"
        note_path.write_text(
            '---\nproject: "[[VaultMigration]]"\n---\nbody', encoding="utf-8"
        )

        exit_code = meeting_sync.main(
            [
                "--set-project",
                str(note_path),
                "--project",
                "",
                "--vault-root",
                str(vault_root),
            ]
        )

        assert exit_code == 0
        assert not note_path.exists()
        new_path = vault_root / "20_Areas" / "Meetings" / "会議.md"
        assert new_path.exists()
        new_fm, _ = vault_lib.split_frontmatter(
            new_path.read_text(encoding="utf-8")
        )
        assert vault_lib.get_fm_value(new_fm, "project") == ""


def test_set_projectで既に正しいフォルダにあれば移動しない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp), project_names=["VaultMigration"])
        dest_dir = vault_root / "10_Projects" / "VaultMigration" / "Meetings"
        dest_dir.mkdir(parents=True, exist_ok=True)
        note_path = dest_dir / "会議.md"
        note_path.write_text(
            '---\nproject: "[[VaultMigration]]"\n---\nbody', encoding="utf-8"
        )

        exit_code = meeting_sync.main(
            [
                "--set-project",
                str(note_path),
                "--project",
                "[[VaultMigration]]",
                "--vault-root",
                str(vault_root),
            ]
        )

        assert exit_code == 0
        assert note_path.exists()
        entries = list(dest_dir.iterdir())
        assert entries == [note_path]


def test_set_projectで存在しないプロジェクト名を指定するとエラーになりノートは変更されない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp), project_names=["VaultMigration"])
        src_dir = vault_root / "20_Areas" / "Meetings"
        note_path = src_dir / "会議.md"
        before_text = '---\nproject: ""\n---\nbody'
        note_path.write_text(before_text, encoding="utf-8")

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = meeting_sync.main(
                [
                    "--set-project",
                    str(note_path),
                    "--project",
                    "[[NonExistent]]",
                    "--vault-root",
                    str(vault_root),
                ]
            )

        assert exit_code == 1
        assert json.loads(stdout.getvalue()) == {
            "status": "error",
            "reason": "project_not_found",
        }
        assert note_path.exists()
        assert note_path.read_text(encoding="utf-8") == before_text
        assert not (vault_root / "10_Projects" / "NonExistent").exists()


def test_set_projectで移動先に同名ファイルがあれば連番付与される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp), project_names=["VaultMigration"])
        src_dir = vault_root / "20_Areas" / "Meetings"
        note_path = src_dir / "会議.md"
        note_path.write_text('---\nproject: ""\n---\nbody-A', encoding="utf-8")

        dest_dir = vault_root / "10_Projects" / "VaultMigration" / "Meetings"
        dest_dir.mkdir(parents=True, exist_ok=True)
        existing_path = dest_dir / "会議.md"
        existing_path.write_text(
            '---\nproject: "[[VaultMigration]]"\n---\nbody-B', encoding="utf-8"
        )

        exit_code = meeting_sync.main(
            [
                "--set-project",
                str(note_path),
                "--project",
                "[[VaultMigration]]",
                "--vault-root",
                str(vault_root),
            ]
        )

        assert exit_code == 0
        assert not note_path.exists()
        moved_path = dest_dir / "会議-2.md"
        assert moved_path.exists()
        assert existing_path.exists()
        assert "body-B" in existing_path.read_text(encoding="utf-8")
        assert "body-A" in moved_path.read_text(encoding="utf-8")


def test_単発新規作成でattendanceがscheduledになる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(id="evt1", summary="定例1on1")
        result = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result["created"][0])
        fm, _body = vault_lib.split_frontmatter(
            note_path.read_text(encoding="utf-8")
        )
        assert vault_lib.get_fm_value(fm, "attendance") == "1_scheduled"


def test_定例新規作成でfrontmatterとコメント両方にattendanceとdateが入る():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(
            id="occA", summary="週次定例", recurringEventId="seriesX"
        )
        result = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result["created"][0])
        text = note_path.read_text(encoding="utf-8")
        fm, body = vault_lib.split_frontmatter(text)

        assert vault_lib.get_fm_value(fm, "attendance") == "1_scheduled"
        assert 'attendance: "1_scheduled"' in body
        assert 'date: "2026-09-21"' in body


def test_同一occurrenceの日付またぎリスケジュールでコメント内dateが更新される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event1 = make_event(id="occA", summary="週次定例", recurringEventId="seriesX")
        result1 = meeting_sync.sync_events([event1], vault_root)
        note_path = Path(result1["created"][0])

        event2 = make_event(
            id="occA",
            summary="週次定例",
            recurringEventId="seriesX",
            start={"dateTime": "2026-09-22T13:00:00+09:00"},
            end={"dateTime": "2026-09-22T14:00:00+09:00"},
        )
        meeting_sync.sync_events([event2], vault_root)

        updated_text = note_path.read_text(encoding="utf-8")
        assert 'date: "2026-09-22"' in updated_text
        assert 'date: "2026-09-21"' not in updated_text


def test_定例で出席者1人以下ならattendanceがskipになる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event1 = make_event(id="occA", summary="週次定例", recurringEventId="seriesX")
        result1 = meeting_sync.sync_events([event1], vault_root)
        note_path = Path(result1["created"][0])

        event2 = make_event(
            id="occA",
            summary="週次定例",
            recurringEventId="seriesX",
            attendees=[{"email": "a@example.com"}],
        )
        meeting_sync.sync_events([event2], vault_root)

        text = note_path.read_text(encoding="utf-8")
        fm, body = vault_lib.split_frontmatter(text)
        assert "(キャンセル)" in body
        assert 'attendance: "3_skip"' in body
        assert vault_lib.get_fm_value(fm, "attendance") == "3_skip"


def test_次回遷移で新ブロックはscheduledにリセットされ旧ブロックの値は退避される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event1 = make_event(id="occA", summary="週次定例", recurringEventId="seriesX")
        result1 = meeting_sync.sync_events([event1], vault_root)
        note_path = Path(result1["created"][0])

        # occAの回を「実施済み」に確定した想定
        meeting_sync.main(
            [
                "--set-attendance",
                str(note_path),
                "--attendance",
                "2_done",
                "--vault-root",
                str(vault_root),
            ]
        )

        event2 = make_event(
            id="occB",
            summary="週次定例",
            recurringEventId="seriesX",
            start={"dateTime": "2026-09-28T13:00:00+09:00"},
            end={"dateTime": "2026-09-28T14:00:00+09:00"},
        )
        meeting_sync.sync_events([event2], vault_root)

        final_text = note_path.read_text(encoding="utf-8")
        start_idx = final_text.find("<!-- NEW_MEETING_START -->")
        end_idx = final_text.find("<!-- NEW_MEETING_END -->")
        current_block = final_text[start_idx:end_idx]
        archive_area = final_text[end_idx:]

        assert 'attendance: "1_scheduled"' in current_block
        assert 'date: "2026-09-28"' in current_block
        assert 'attendance: "2_done"' in archive_area

        fm, _body = vault_lib.split_frontmatter(final_text)
        assert vault_lib.get_fm_value(fm, "attendance") == "1_scheduled"


def test_旧書式コメントのノートを再同期してもattendanceが空文字に壊れない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event1 = make_event(id="occA", summary="週次定例", recurringEventId="seriesX")
        result1 = meeting_sync.sync_events([event1], vault_root)
        note_path = Path(result1["created"][0])

        # 移行前フォーマット(occurrence_idのみ、attendance/date無し)を再現する
        text = note_path.read_text(encoding="utf-8")
        text = text.replace(
            '<!-- occurrence_id: "occA" attendance: "1_scheduled" date: "2026-09-21" -->',
            '<!-- occurrence_id: "occA" -->',
        )
        note_path.write_text(text, encoding="utf-8")

        event2 = make_event(
            id="occA",
            summary="週次定例",
            recurringEventId="seriesX",
            start={"dateTime": "2026-09-22T13:00:00+09:00"},
            end={"dateTime": "2026-09-22T14:00:00+09:00"},
        )
        meeting_sync.sync_events([event2], vault_root)

        updated_text = note_path.read_text(encoding="utf-8")
        fm, _body = vault_lib.split_frontmatter(updated_text)
        assert 'attendance: "1_scheduled"' in updated_text
        assert 'attendance: ""' not in updated_text
        assert vault_lib.get_fm_value(fm, "attendance") == "1_scheduled"


def _deletion_set_date(note_path: Path, date: str) -> None:
    text = note_path.read_text(encoding="utf-8")
    fm, body = vault_lib.split_frontmatter(text)
    fm = vault_lib.set_fm_value(fm, "date", date)
    note_path.write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8")


def test_今日開催予定でイベントが消えたら物理削除される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])
        assert note_path.exists()
        # make_eventの開催日は固定値のため、テスト実行日に合わせる
        # (実行日をまたぐとdate==today判定がずれてテストが偽装的に
        # 失敗/成功するのを防ぐ)
        _deletion_set_date(note_path, datetime.date.today().isoformat())

        result2 = meeting_sync.sync_events([], vault_root)

        assert not note_path.exists()
        assert result2["deleted"] == [str(note_path)]


def test_開催日が過去のノートはイベントが消えていても削除されない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])

        # 開催日を過去日付に書き換える(先読み廃止後は当日ノートしか作られないため
        # 過去日ノートを人工的に作って検証する)
        text = note_path.read_text(encoding="utf-8")
        fm, body = vault_lib.split_frontmatter(text)
        fm = vault_lib.set_fm_value(fm, "date", "2020-01-01")
        note_path.write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8")

        result2 = meeting_sync.sync_events([], vault_root)

        assert note_path.exists()
        assert result2["deleted"] == []


def test_定例ノートはイベントが消えても削除されない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(
            id="occA", summary="週次定例", recurringEventId="seriesX"
        )
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])

        result2 = meeting_sync.sync_events([], vault_root)

        assert note_path.exists()
        assert result2["deleted"] == []


def test_今日のevents一覧に対応するイベントがあれば削除されない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])

        result2 = meeting_sync.sync_events([event], vault_root)

        assert note_path.exists()
        assert result2["deleted"] == []


def _attendance_check_set_date(note_path: Path, date: str) -> None:
    text = note_path.read_text(encoding="utf-8")
    fm, body = vault_lib.split_frontmatter(text)
    fm = vault_lib.set_fm_value(fm, "date", date)
    note_path.write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8")


def test_単発で開催日が過去かつscheduledのままなら検出される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])
        _attendance_check_set_date(note_path, "2020-01-01")

        result2 = meeting_sync.sync_events([], vault_root)

        assert result2["needs_attendance_check"] == [
            {"note_path": str(note_path), "title": "定例1on1"}
        ]


def test_単発で開催日が今日なら検出されない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        # make_eventの開催日は固定値のため、開催日が実行日(今日)になる
        # よう明示的に指定する。
        today = datetime.date.today()
        start_dt = datetime.datetime.combine(today, datetime.time(13, 0))
        end_dt = datetime.datetime.combine(today, datetime.time(14, 0))
        event = make_event(
            id="evt1",
            summary="定例1on1",
            start={"dateTime": start_dt.isoformat()},
            end={"dateTime": end_dt.isoformat()},
        )
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])

        result2 = meeting_sync.sync_events([event], vault_root)

        assert result2["needs_attendance_check"] == []


def test_単発でattendanceが確定済みなら開催日が過去でも検出されない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])
        _attendance_check_set_date(note_path, "2020-01-01")
        meeting_sync.main(
            [
                "--set-attendance",
                str(note_path),
                "--attendance",
                "2_done",
                "--vault-root",
                str(vault_root),
            ]
        )

        result2 = meeting_sync.sync_events([], vault_root)

        assert result2["needs_attendance_check"] == []


def test_定例で現在occurrenceの開催日が過去かつscheduledのままなら検出される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(
            id="occA", summary="週次定例", recurringEventId="seriesX"
        )
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])
        text = note_path.read_text(encoding="utf-8")
        text = text.replace('date: "2026-09-21"', 'date: "2020-01-01"')
        note_path.write_text(text, encoding="utf-8")

        result2 = meeting_sync.sync_events([], vault_root)

        assert result2["needs_attendance_check"] == [
            {"note_path": str(note_path), "title": "週次定例"}
        ]


def test_定例でattendanceが確定済みなら開催日が過去でも検出されない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(
            id="occA", summary="週次定例", recurringEventId="seriesX"
        )
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])
        meeting_sync.main(
            [
                "--set-attendance",
                str(note_path),
                "--attendance",
                "2_done",
                "--vault-root",
                str(vault_root),
            ]
        )
        text = note_path.read_text(encoding="utf-8")
        text = text.replace('date: "2026-09-21"', 'date: "2020-01-01"')
        note_path.write_text(text, encoding="utf-8")

        result2 = meeting_sync.sync_events([], vault_root)

        assert result2["needs_attendance_check"] == []


def _set_attendance(note_path: Path, vault_root: Path, value: str) -> None:
    meeting_sync.main(
        [
            "--set-attendance",
            str(note_path),
            "--attendance",
            value,
            "--vault-root",
            str(vault_root),
        ]
    )


def _inject_unchecked_item(note_path: Path, heading: str, text: str) -> None:
    note_text = note_path.read_text(encoding="utf-8")
    note_text = note_text.replace(f"{heading}\n- [ ] ", f"{heading}\n- [ ] {text}")
    note_path.write_text(note_text, encoding="utf-8")


def _check_item(note_path: Path, heading: str, text: str) -> None:
    note_text = note_path.read_text(encoding="utf-8")
    note_text = note_text.replace(
        f"{heading}\n- [ ] {text}", f"{heading}\n- [x] {text}"
    )
    note_path.write_text(note_text, encoding="utf-8")


def test_単発で2_doneかつ未チェックアイテムがあれば検出される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])
        _set_attendance(note_path, vault_root, "2_done")
        _inject_unchecked_item(note_path, "## ⚡ アクションアイテム", "資料を送る")

        result2 = meeting_sync.sync_events([], vault_root)

        assert result2["needs_task_check"] == [
            {"note_path": str(note_path), "title": "定例1on1"}
        ]


def test_単発で3_skipでも検出される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])
        _set_attendance(note_path, vault_root, "3_skip")
        _inject_unchecked_item(note_path, "## ⚡ アクションアイテム", "資料を送る")

        result2 = meeting_sync.sync_events([], vault_root)

        assert result2["needs_task_check"] == [
            {"note_path": str(note_path), "title": "定例1on1"}
        ]


def test_単発で全項目チェック済みなら検出されない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])
        _set_attendance(note_path, vault_root, "2_done")
        _inject_unchecked_item(note_path, "## ⚡ アクションアイテム", "資料を送る")
        _check_item(note_path, "## ⚡ アクションアイテム", "資料を送る")

        result2 = meeting_sync.sync_events([], vault_root)

        assert result2["needs_task_check"] == []


def test_単発でアクションアイテム未記入の空プレースホルダーのみなら検出されない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])
        # アクションアイテム欄を一切編集せず(テンプレートの
        # 空プレースホルダー行"- [ ] "のみが残る状態)attendanceだけ確定する
        _set_attendance(note_path, vault_root, "2_done")

        result2 = meeting_sync.sync_events([], vault_root)

        assert result2["needs_task_check"] == []


def test_単発でアクションアイテムセクション自体が無ければ検出されない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        dest_dir = vault_root / "20_Areas" / "Meetings"
        dest_dir.mkdir(parents=True, exist_ok=True)
        note_path = dest_dir / "会議.md"
        note_path.write_text(
            '---\ntype: meeting\ncalendar_event_id: "evt1"\n'
            'project: ""\ndate: "2020-01-01"\nurl: ""\n'
            'attendance: "2_done"\n---\n'
            "# 会議\n\n## 📝 決定事項\n- \n",
            encoding="utf-8",
        )

        result = meeting_sync.sync_events([], vault_root)

        assert result["needs_task_check"] == []


def test_単発でattendanceが1_scheduledのままならneeds_task_checkに出ない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])
        _inject_unchecked_item(note_path, "## ⚡ アクションアイテム", "資料を送る")
        # 開催日を過去にしてneeds_attendance_check側の対象にする
        text = note_path.read_text(encoding="utf-8")
        fm, body = vault_lib.split_frontmatter(text)
        fm = vault_lib.set_fm_value(fm, "date", "2020-01-01")
        note_path.write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8")

        result2 = meeting_sync.sync_events([], vault_root)

        assert result2["needs_task_check"] == []
        assert result2["needs_attendance_check"] == [
            {"note_path": str(note_path), "title": "定例1on1"}
        ]


def test_単発で開催日が今日でも過去でも検出される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        today = datetime.date.today()
        start_dt = datetime.datetime.combine(today, datetime.time(13, 0))
        end_dt = datetime.datetime.combine(today, datetime.time(14, 0))
        event = make_event(
            id="evt1",
            summary="定例1on1",
            start={"dateTime": start_dt.isoformat()},
            end={"dateTime": end_dt.isoformat()},
        )
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])
        _set_attendance(note_path, vault_root, "2_done")
        _inject_unchecked_item(note_path, "## ⚡ アクションアイテム", "資料を送る")

        result2 = meeting_sync.sync_events([event], vault_root)

        assert result2["needs_task_check"] == [
            {"note_path": str(note_path), "title": "定例1on1"}
        ]


def test_定例で現在occurrenceが2_doneかつ未チェックなら検出される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(
            id="occA", summary="週次定例", recurringEventId="seriesX"
        )
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])
        _set_attendance(note_path, vault_root, "2_done")
        _inject_unchecked_item(
            note_path, "### ⚡ アクションアイテム（今回）", "議事録を送付する"
        )

        result2 = meeting_sync.sync_events([], vault_root)

        assert result2["needs_task_check"] == [
            {"note_path": str(note_path), "title": "週次定例"}
        ]


def test_定例でアーカイブ領域の未チェックアイテムは対象外():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event1 = make_event(id="occA", summary="週次定例", recurringEventId="seriesX")
        result1 = meeting_sync.sync_events([event1], vault_root)
        note_path = Path(result1["created"][0])
        _set_attendance(note_path, vault_root, "2_done")
        _inject_unchecked_item(
            note_path, "### ⚡ アクションアイテム（今回）", "occA回のタスク"
        )

        # 次回へ遷移させ、occAのブロックをアーカイブへ退避する
        event2 = make_event(
            id="occB",
            summary="週次定例",
            recurringEventId="seriesX",
            start={"dateTime": "2026-09-28T13:00:00+09:00"},
            end={"dateTime": "2026-09-28T14:00:00+09:00"},
        )
        meeting_sync.sync_events([event2], vault_root)

        result3 = meeting_sync.sync_events([], vault_root)

        # 新occurrence(occB)は1_scheduledなので対象外、
        # アーカイブされたoccAの未チェックアイテムも対象外
        assert result3["needs_task_check"] == []


def test_定例で現在occurrenceが1_scheduledなら検出されない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(
            id="occA", summary="週次定例", recurringEventId="seriesX"
        )
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])
        _inject_unchecked_item(
            note_path, "### ⚡ アクションアイテム（今回）", "議事録を送付する"
        )

        result2 = meeting_sync.sync_events([], vault_root)

        assert result2["needs_task_check"] == []


def test_定例でoccurrenceコメントのattendanceキーが欠損していればneeds_attendance_check側に出る():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(
            id="occA", summary="週次定例", recurringEventId="seriesX"
        )
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])

        # 移行前フォーマット相当: attendanceキー自体を欠損させる
        # (dateは有効な過去日を残す)
        text = note_path.read_text(encoding="utf-8")
        text = text.replace(
            '<!-- occurrence_id: "occA" attendance: "1_scheduled" date: "2026-09-21" -->',
            '<!-- occurrence_id: "occA" date: "2020-01-01" -->',
        )
        note_path.write_text(text, encoding="utf-8")

        result2 = meeting_sync.sync_events([], vault_root)

        assert result2["needs_attendance_check"] == [
            {"note_path": str(note_path), "title": "週次定例"}
        ]
        assert result2["needs_task_check"] == []


def test_link_task後はneeds_task_check対象から除外される():
    """新仕様のlink-taskはチェック状態を変えず本文を[[task_note]]へ完全置換
    するだけだが、本文全体が[[...]]形式（タスクノートへのリンクのみ）に
    なった行は既にタスク化済みとみなし、needs_task_check対象から除外する。
    """
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])
        _set_attendance(note_path, vault_root, "2_done")
        _inject_unchecked_item(note_path, "## ⚡ アクションアイテム", "資料を送る")

        result_before = meeting_sync.sync_events([], vault_root)
        assert len(result_before["needs_task_check"]) == 1

        meeting_sync.main(
            [
                "--link-task",
                str(note_path),
                "--item-text",
                "資料を送る",
                "--task-note",
                "資料を送る",
                "--vault-root",
                str(vault_root),
            ]
        )

        result_after = meeting_sync.sync_events([], vault_root)
        assert len(result_after["needs_task_check"]) == 0


def test_link_task後も文言とリンクが両方残る行は引き続き未消化扱いになる():
    """本文全体が[[...]]のみで完全一致する場合だけ除外対象とする設計のため、
    元の文言とリンクが両方残るような行（旧仕様の名残や手動編集）は
    従来通りneeds_task_check対象のままになる。
    """
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])
        _set_attendance(note_path, vault_root, "2_done")
        _inject_unchecked_item(note_path, "## ⚡ アクションアイテム", "資料を送る [[資料を送る]]")

        result = meeting_sync.sync_events([], vault_root)
        assert len(result["needs_task_check"]) == 1


def test_新規イベント同期と同じ呼び出し内でneeds_task_checkも返る():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        existing_event = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([existing_event], vault_root)
        existing_note_path = Path(result1["created"][0])
        _set_attendance(existing_note_path, vault_root, "2_done")
        _inject_unchecked_item(
            existing_note_path, "## ⚡ アクションアイテム", "資料を送る"
        )

        new_event = make_event(id="evt2", summary="新規会議")
        result2 = meeting_sync.sync_events([existing_event, new_event], vault_root)

        assert len(result2["created"]) == 1
        assert result2["needs_task_check"] == [
            {"note_path": str(existing_note_path), "title": "定例1on1"}
        ]


def test_単発ノートのattendanceが書き換わる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])

        exit_code = meeting_sync.main(
            [
                "--set-attendance",
                str(note_path),
                "--attendance",
                "3_skip",
                "--vault-root",
                str(vault_root),
            ]
        )

        assert exit_code == 0
        fm, _body = vault_lib.split_frontmatter(
            note_path.read_text(encoding="utf-8")
        )
        assert vault_lib.get_fm_value(fm, "attendance") == "3_skip"


def test_定例ノートはfrontmatterと現在ブロック両方が書き換わりアーカイブは変わらない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event1 = make_event(id="occA", summary="週次定例", recurringEventId="seriesX")
        result1 = meeting_sync.sync_events([event1], vault_root)
        note_path = Path(result1["created"][0])

        event2 = make_event(
            id="occB",
            summary="週次定例",
            recurringEventId="seriesX",
            start={"dateTime": "2026-09-28T13:00:00+09:00"},
            end={"dateTime": "2026-09-28T14:00:00+09:00"},
        )
        meeting_sync.sync_events([event2], vault_root)

        exit_code = meeting_sync.main(
            [
                "--set-attendance",
                str(note_path),
                "--attendance",
                "2_done",
                "--vault-root",
                str(vault_root),
            ]
        )

        assert exit_code == 0
        final_text = note_path.read_text(encoding="utf-8")
        fm, _body = vault_lib.split_frontmatter(final_text)
        assert vault_lib.get_fm_value(fm, "attendance") == "2_done"

        start_idx = final_text.find("<!-- NEW_MEETING_START -->")
        end_idx = final_text.find("<!-- NEW_MEETING_END -->")
        current_block = final_text[start_idx:end_idx]
        archive_area = final_text[end_idx:]
        assert 'attendance: "2_done"' in current_block
        # アーカイブされた旧occurrence(occA)のattendanceは
        # 1_scheduledのまま上書きされていない
        assert 'occurrence_id: "occA" attendance: "1_scheduled"' in archive_area
        assert 'occurrence_id: "occA" attendance: "2_done"' not in archive_area


def test_存在しないノートを指定するとエラーになる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        missing_path = vault_root / "20_Areas" / "Meetings" / "no-such.md"

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = meeting_sync.main(
                [
                    "--set-attendance",
                    str(missing_path),
                    "--attendance",
                    "2_done",
                    "--vault-root",
                    str(vault_root),
                ]
            )

        assert exit_code == 1
        assert json.loads(stdout.getvalue()) == {
            "status": "error",
            "reason": "note_not_found",
        }


def test_不正なattendance値はargparseレベルで拒否される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        note_path = vault_root / "dummy.md"
        note_path.write_text("---\ntype: meeting\n---\nbody", encoding="utf-8")

        with pytest.raises(SystemExit):
            meeting_sync.main(
                [
                    "--set-attendance",
                    str(note_path),
                    "--attendance",
                    "invalid_value",
                    "--vault-root",
                    str(vault_root),
                ]
            )


def test_単発ノートでアクションアイテムがタスクノートへ完全置換される():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])
        text = note_path.read_text(encoding="utf-8")
        text = text.replace(
            "## ⚡ アクションアイテム\n- [ ] ",
            "## ⚡ アクションアイテム\n- [ ] 資料を送る",
        )
        note_path.write_text(text, encoding="utf-8")

        exit_code = meeting_sync.main(
            [
                "--link-task",
                str(note_path),
                "--item-text",
                "資料を送る",
                "--task-note",
                "資料を送る",
                "--vault-root",
                str(vault_root),
            ]
        )

        assert exit_code == 0
        updated = note_path.read_text(encoding="utf-8")
        assert "- [ ] [[資料を送る]]" in updated
        assert "資料を送る]]" in updated
        assert "[x]" not in updated


def test_task_note省略時はエラー終了する():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])
        text = note_path.read_text(encoding="utf-8")
        text = text.replace(
            "## ⚡ アクションアイテム\n- [ ] ",
            "## ⚡ アクションアイテム\n- [ ] 不要な項目",
        )
        note_path.write_text(text, encoding="utf-8")
        before_text = note_path.read_text(encoding="utf-8")

        with pytest.raises(SystemExit):
            meeting_sync.main(
                [
                    "--link-task",
                    str(note_path),
                    "--item-text",
                    "不要な項目",
                    "--vault-root",
                    str(vault_root),
                ]
            )

        assert note_path.read_text(encoding="utf-8") == before_text


def test_該当行が無ければエラーでファイルは変更されない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])
        before_text = note_path.read_text(encoding="utf-8")

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = meeting_sync.main(
                [
                    "--link-task",
                    str(note_path),
                    "--item-text",
                    "存在しない項目",
                    "--task-note",
                    "存在しない項目",
                    "--vault-root",
                    str(vault_root),
                ]
            )

        assert exit_code == 1
        assert json.loads(stdout.getvalue()) == {
            "status": "error",
            "reason": "item_not_found",
        }
        assert note_path.read_text(encoding="utf-8") == before_text


def test_アクションアイテムセクション外の同一文言は誤爆しない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])
        text = note_path.read_text(encoding="utf-8")
        # 決定事項セクションにアクションアイテムと同一文言の行を仕込む
        text = text.replace(
            "## 📝 決定事項\n- ", "## 📝 決定事項\n- [ ] 資料を送る"
        )
        text = text.replace(
            "## ⚡ アクションアイテム\n- [ ] ",
            "## ⚡ アクションアイテム\n- [ ] 資料を送る",
        )
        note_path.write_text(text, encoding="utf-8")

        meeting_sync.main(
            [
                "--link-task",
                str(note_path),
                "--item-text",
                "資料を送る",
                "--task-note",
                "資料を送る",
                "--vault-root",
                str(vault_root),
            ]
        )

        updated = note_path.read_text(encoding="utf-8")
        assert "## ⚡ アクションアイテム\n- [ ] [[資料を送る]]" in updated
        # 決定事項セクション側の同一文言は完全置換されない
        assert "## 📝 決定事項\n- [ ] 資料を送る" in updated


def test_定例ノートは現在ブロックのみ置換されアーカイブ領域は変わらない():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event1 = make_event(id="occA", summary="週次定例", recurringEventId="seriesX")
        result1 = meeting_sync.sync_events([event1], vault_root)
        note_path = Path(result1["created"][0])
        text = note_path.read_text(encoding="utf-8")
        text = text.replace(
            "### ⚡ アクションアイテム（今回）\n- [ ] ",
            "### ⚡ アクションアイテム（今回）\n- [ ] 共通の文言",
        )
        note_path.write_text(text, encoding="utf-8")

        event2 = make_event(
            id="occB",
            summary="週次定例",
            recurringEventId="seriesX",
            start={"dateTime": "2026-09-28T13:00:00+09:00"},
            end={"dateTime": "2026-09-28T14:00:00+09:00"},
        )
        meeting_sync.sync_events([event2], vault_root)
        text2 = note_path.read_text(encoding="utf-8")
        text2 = text2.replace(
            "### ⚡ アクションアイテム（今回）\n- [ ] ",
            "### ⚡ アクションアイテム（今回）\n- [ ] 共通の文言",
            1,
        )
        note_path.write_text(text2, encoding="utf-8")

        meeting_sync.main(
            [
                "--link-task",
                str(note_path),
                "--item-text",
                "共通の文言",
                "--task-note",
                "共通タスク",
                "--vault-root",
                str(vault_root),
            ]
        )

        final_text = note_path.read_text(encoding="utf-8")
        start_idx = final_text.find("<!-- NEW_MEETING_START -->")
        end_idx = final_text.find("<!-- NEW_MEETING_END -->")
        current_block = final_text[start_idx:end_idx]
        archive_area = final_text[end_idx:]

        assert "- [ ] [[共通タスク]]" in current_block
        assert "- [ ] 共通の文言" in archive_area
        assert "[[共通タスク]]" not in archive_area


def test_item_indexで複数出現時に指定した出現箇所を置換できる():
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = make_vault(Path(tmp))
        event = make_event(id="evt1", summary="定例1on1")
        result1 = meeting_sync.sync_events([event], vault_root)
        note_path = Path(result1["created"][0])
        text = note_path.read_text(encoding="utf-8")
        text = text.replace(
            "## ⚡ アクションアイテム\n- [ ] ",
            "## ⚡ アクションアイテム\n- [ ] 共通の文言\n- [ ] 共通の文言",
        )
        note_path.write_text(text, encoding="utf-8")

        exit_code = meeting_sync.main(
            [
                "--link-task",
                str(note_path),
                "--item-text",
                "共通の文言",
                "--item-index",
                "1",
                "--task-note",
                "2番目のタスク",
                "--vault-root",
                str(vault_root),
            ]
        )

        assert exit_code == 0
        updated = note_path.read_text(encoding="utf-8")
        assert "- [ ] 共通の文言\n- [ ] [[2番目のタスク]]" in updated


def test_eventsキー付きJSONを読み込める():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.json"
        path.write_text(
            json.dumps({"events": [make_event()]}), encoding="utf-8"
        )
        events = meeting_sync._load_events(path)
        assert len(events) == 1
        assert events[0]["id"] == "evt1"


def test_配列そのもののJSONも読み込める():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.json"
        path.write_text(json.dumps([make_event()]), encoding="utf-8")
        events = meeting_sync._load_events(path)
        assert len(events) == 1
        assert events[0]["id"] == "evt1"
