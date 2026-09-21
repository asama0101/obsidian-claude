"""meeting_sync.py のユニットテスト。

標準ライブラリの unittest のみを使用する。テンプレートファイルは
実際の70_Templates配下のものをテスト用一時Vaultへコピーして使う
（内容を重複転記せず、実物とのズレを防ぐため）。
"""

import datetime
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

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


class TestSkipSingleAttendee(unittest.TestCase):
    def test_attendeesキーが無いイベントはスキップされる(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp))
            event = make_event()
            del event["attendees"]
            result = meeting_sync.sync_events([event], vault_root)
            self.assertEqual(result["skipped_single_attendee"], ["evt1"])
            self.assertEqual(result["created"], [])

    def test_出席者1人のイベントはスキップされる(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp))
            event = make_event(attendees=[{"email": "a@example.com", "self": True}])
            result = meeting_sync.sync_events([event], vault_root)
            self.assertEqual(result["skipped_single_attendee"], ["evt1"])
            self.assertEqual(result["created"], [])

    def test_定例イベントも出席者1人ならスキップされる(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp))
            event = make_event(
                attendees=[{"email": "a@example.com"}], recurringEventId="series1"
            )
            result = meeting_sync.sync_events([event], vault_root)
            self.assertEqual(result["skipped_single_attendee"], ["evt1"])
            self.assertEqual(result["created"], [])


class TestSingleMeetingCreate(unittest.TestCase):
    def test_新規作成でproject推定される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp), project_names=["VaultMigration"])
            event = make_event(
                id="evt1",
                summary="VaultMigration定例MTG",
                hangoutLink="https://meet.google.com/abc-defg-hij",
            )
            result = meeting_sync.sync_events([event], vault_root)

            self.assertEqual(len(result["created"]), 1)
            note_path = Path(result["created"][0])
            self.assertTrue(note_path.exists())
            self.assertEqual(
                note_path.parent, vault_root / "10_Projects" / "VaultMigration" / "Meetings"
            )

            text = note_path.read_text(encoding="utf-8")
            fm, body = vault_lib.split_frontmatter(text)
            self.assertEqual(vault_lib.get_fm_value(fm, "calendar_event_id"), "evt1")
            self.assertEqual(vault_lib.get_fm_value(fm, "project"), "[[VaultMigration]]")
            self.assertEqual(vault_lib.get_fm_value(fm, "date"), "2026-09-21")
            self.assertEqual(
                vault_lib.get_fm_value(fm, "url"), "https://meet.google.com/abc-defg-hij"
            )
            self.assertIn("# VaultMigration定例MTG", body)

    def test_project推定できない場合はAreas配下に空欄で作成(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp))
            event = make_event(id="evt2", summary="関係ない打ち合わせ")
            result = meeting_sync.sync_events([event], vault_root)

            note_path = Path(result["created"][0])
            self.assertEqual(note_path.parent, vault_root / "20_Areas" / "Meetings")
            text = note_path.read_text(encoding="utf-8")
            fm, _body = vault_lib.split_frontmatter(text)
            self.assertEqual(vault_lib.get_fm_value(fm, "project"), "")


class TestSingleMeetingUpdate(unittest.TestCase):
    def test_日時変更が反映されユーザー記入欄は変わらない(self):
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

            self.assertEqual(result2["updated"], [str(note_path)])
            updated_text = note_path.read_text(encoding="utf-8")
            fm, body = vault_lib.split_frontmatter(updated_text)
            self.assertEqual(vault_lib.get_fm_value(fm, "date"), "2026-09-22")
            self.assertIn("予算を確定した", body)

    def test_変化が無ければupdatedに追加されない(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp))
            event = make_event(id="evt1", summary="定例1on1")
            result1 = meeting_sync.sync_events([event], vault_root)
            self.assertEqual(len(result1["created"]), 1)

            result2 = meeting_sync.sync_events([event], vault_root)
            self.assertEqual(result2["updated"], [])
            self.assertEqual(result2["created"], [])


class TestSingleMeetingCancel(unittest.TestCase):
    def test_出席者が1人に減ったらcancelledになりファイルは残る(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp))
            event1 = make_event(id="evt1", summary="定例1on1")
            result1 = meeting_sync.sync_events([event1], vault_root)
            note_path = Path(result1["created"][0])

            event2 = make_event(
                id="evt1", summary="定例1on1", attendees=[{"email": "a@example.com"}]
            )
            result2 = meeting_sync.sync_events([event2], vault_root)

            self.assertEqual(result2["cancelled"], [str(note_path)])
            self.assertTrue(note_path.exists())
            fm, _body = vault_lib.split_frontmatter(
                note_path.read_text(encoding="utf-8")
            )
            self.assertEqual(vault_lib.get_fm_value(fm, "status"), "cancelled")


class TestSeriesCreate(unittest.TestCase):
    def test_定例イベント新規作成でseries_idとoccurrence_idが設定される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp))
            event = make_event(
                id="occA", summary="週次定例", recurringEventId="seriesX"
            )
            result = meeting_sync.sync_events([event], vault_root)

            self.assertEqual(len(result["created"]), 1)
            note_path = Path(result["created"][0])
            text = note_path.read_text(encoding="utf-8")
            fm, body = vault_lib.split_frontmatter(text)
            self.assertEqual(vault_lib.get_fm_value(fm, "calendar_series_id"), "seriesX")
            self.assertEqual(
                vault_lib.get_fm_value(fm, "last_updated"),
                datetime.date.today().isoformat(),
            )
            self.assertIn('<!-- occurrence_id: "occA" -->', body)
            self.assertIn("<!-- NEW_MEETING_START -->", body)
            self.assertIn("<!-- NEW_MEETING_END -->", body)


class TestSeriesResync(unittest.TestCase):
    def _create_series(self, vault_root):
        event = make_event(id="occA", summary="週次定例", recurringEventId="seriesX")
        result = meeting_sync.sync_events([event], vault_root)
        return Path(result["created"][0])

    def test_同一occurrenceの再同期は部分更新のみでブロックが退避されない(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp))
            note_path = self._create_series(vault_root)

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

            self.assertEqual(result2["updated"], [str(note_path)])
            updated_text = note_path.read_text(encoding="utf-8")

            # occurrence_id は変わらず、丸ごと置き換えられていない(手書き内容が残る)
            self.assertIn('<!-- occurrence_id: "occA" -->', updated_text)
            self.assertIn("進捗確認完了", updated_text)
            self.assertIn("会議室B", updated_text)
            self.assertIn("15:00", updated_text)
            self.assertIn("1時間30分", updated_text)

    def test_出席者1人以下ならブロック内にキャンセル注記が付く(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp))
            note_path = self._create_series(vault_root)

            event2 = make_event(
                id="occA",
                summary="週次定例",
                recurringEventId="seriesX",
                attendees=[{"email": "a@example.com"}],
            )
            result2 = meeting_sync.sync_events([event2], vault_root)

            self.assertEqual(result2["updated"], [str(note_path)])
            updated_text = note_path.read_text(encoding="utf-8")
            self.assertIn("(キャンセル)", updated_text)


class TestSeriesTransition(unittest.TestCase):
    def test_新しい回への遷移で旧ブロックが退避され新ブロックに差し替わる(self):
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

            self.assertEqual(result2["created"], [str(note_path)])
            final_text = note_path.read_text(encoding="utf-8")

            # 現在のブロックは新しいoccurrence_idに差し替わっている
            start_idx = final_text.find("<!-- NEW_MEETING_START -->")
            end_idx = final_text.find("<!-- NEW_MEETING_END -->")
            current_block = final_text[start_idx:end_idx]
            self.assertIn('occurrence_id: "occB"', current_block)
            self.assertNotIn("occA回の決定事項", current_block)

            # 旧ブロックの内容(手書き含む)はEND直後の過去ログ領域に退避されている
            archive_area = final_text[end_idx:]
            self.assertIn('occurrence_id: "occA"', archive_area)
            self.assertIn("occA回の決定事項", archive_area)

            # 元々あった「過去の議事録」コメントも失われていない
            self.assertIn("過去の議事録", archive_area)

            fm, _body = vault_lib.split_frontmatter(final_text)
            self.assertEqual(
                vault_lib.get_fm_value(fm, "last_updated"),
                datetime.date.today().isoformat(),
            )


class TestLoadEvents(unittest.TestCase):
    def test_eventsキー付きJSONを読み込める(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.json"
            path.write_text(
                json.dumps({"events": [make_event()]}), encoding="utf-8"
            )
            events = meeting_sync._load_events(path)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["id"], "evt1")

    def test_配列そのもののJSONも読み込める(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.json"
            path.write_text(json.dumps([make_event()]), encoding="utf-8")
            events = meeting_sync._load_events(path)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["id"], "evt1")


if __name__ == "__main__":
    unittest.main()
