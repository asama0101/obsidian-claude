"""meeting_sync.py のユニットテスト。

標準ライブラリの unittest のみを使用する。テンプレートファイルは
実際の70_Templates配下のものをテスト用一時Vaultへコピーして使う
（内容を重複転記せず、実物とのズレを防ぐため）。
"""

import contextlib
import datetime
import io
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
            self.assertIsNone(vault_lib.get_fm_value(fm, "status"))
            self.assertEqual(vault_lib.get_fm_value(fm, "attendance"), "3_skip")


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
            self.assertIn('occurrence_id: "occA"', body)
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
            self.assertIn('occurrence_id: "occA"', updated_text)
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

            fm, _body = vault_lib.split_frontmatter(final_text)
            self.assertEqual(
                vault_lib.get_fm_value(fm, "last_updated"),
                datetime.date.today().isoformat(),
            )


class TestFilenameDatePrefix(unittest.TestCase):
    def test_単発ノートのファイル名に開催日プレフィックスが付く(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp))
            event = make_event(id="evt1", summary="定例1on1")
            result = meeting_sync.sync_events([event], vault_root)
            note_path = Path(result["created"][0])
            self.assertEqual(note_path.name, "2026-09-21 定例1on1.md")

    def test_定例ノートのファイル名に日付プレフィックスは付かない(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp))
            event = make_event(
                id="occA", summary="週次定例", recurringEventId="seriesX"
            )
            result = meeting_sync.sync_events([event], vault_root)
            note_path = Path(result["created"][0])
            self.assertEqual(note_path.name, "週次定例.md")


class TestNoProject(unittest.TestCase):
    def test_project推定できなければno_projectに追加される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp), project_names=["VaultMigration"])
            event = make_event(id="evt1", summary="関係ない打ち合わせ")
            result = meeting_sync.sync_events([event], vault_root)
            note_path = Path(result["created"][0])
            self.assertEqual(
                result["no_project"],
                [{"note_path": str(note_path), "title": "関係ない打ち合わせ"}],
            )

    def test_project推定できればno_projectに追加されない(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp), project_names=["VaultMigration"])
            event = make_event(id="evt1", summary="VaultMigration定例MTG")
            result = meeting_sync.sync_events([event], vault_root)
            self.assertEqual(result["no_project"], [])

    def test_定例ノートもproject推定できなければno_projectに追加される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp), project_names=["VaultMigration"])
            event = make_event(
                id="occA", summary="週次定例", recurringEventId="seriesX"
            )
            result = meeting_sync.sync_events([event], vault_root)
            note_path = Path(result["created"][0])
            self.assertEqual(
                result["no_project"],
                [{"note_path": str(note_path), "title": "週次定例"}],
            )


class TestFormatAttendees(unittest.TestCase):
    def test_自分自身は除外される(self):
        attendees = [
            {"email": "me@example.com", "self": True},
            {"email": "a@example.com"},
        ]
        self.assertEqual(meeting_sync._format_attendees(attendees), "a@example.com")

    def test_displayNameが優先される(self):
        attendees = [{"email": "a@example.com", "displayName": "山田太郎"}]
        self.assertEqual(meeting_sync._format_attendees(attendees), "山田太郎")

    def test_displayNameが無ければemailにフォールバックする(self):
        attendees = [{"email": "a@example.com"}]
        self.assertEqual(meeting_sync._format_attendees(attendees), "a@example.com")

    def test_複数人はカンマ区切りで結合される(self):
        attendees = [
            {"email": "a@example.com"},
            {"displayName": "山田太郎", "email": "b@example.com"},
        ]
        self.assertEqual(
            meeting_sync._format_attendees(attendees), "a@example.com, 山田太郎"
        )

    def test_空リストは空文字になる(self):
        self.assertEqual(meeting_sync._format_attendees([]), "")

    def test_自分だけの場合も空文字になる(self):
        attendees = [{"self": True, "email": "me@example.com"}]
        self.assertEqual(meeting_sync._format_attendees(attendees), "")


class TestAttendeesLocationAtCreation(unittest.TestCase):
    def test_単発ノート作成時に参加者と開催場所が埋まる(self):
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
            self.assertIn("**開催場所:** 会議室A", text)
            self.assertIn("**参加者:** 山田太郎", text)

    def test_定例ノート新規作成時に参加者と開催場所が埋まる(self):
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
            self.assertIn("**開催場所:** 会議室B", text)
            self.assertIn("**参加者:** 鈴木花子", text)

    def test_新しい回への遷移時に新ブロックへ参加者と開催場所が埋まり旧ブロックは変わらない(
        self,
    ):
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

            self.assertIn("**開催場所:** 会議室C", current_block)
            self.assertIn("**参加者:** 佐藤次郎", current_block)
            # 旧ブロックは元々開催場所・参加者未設定で作成されたため変わらない
            self.assertNotIn("会議室C", archive_area)
            self.assertNotIn("佐藤次郎", archive_area)


class TestSetProjectMode(unittest.TestCase):
    def test_set_projectで指定ノートのproject欄が書き換わりプロジェクト配下へ移動する(self):
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
                    '"[[VaultMigration]]"',
                    "--vault-root",
                    str(vault_root),
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertFalse(note_path.exists())
            dest_path = (
                vault_root / "10_Projects" / "VaultMigration" / "Meetings" / note_path.name
            )
            self.assertTrue(dest_path.exists())
            after_text = dest_path.read_text(encoding="utf-8")
            after_fm, after_body = vault_lib.split_frontmatter(after_text)

            self.assertEqual(
                vault_lib.get_fm_value(after_fm, "project"), "[[VaultMigration]]"
            )
            self.assertEqual(
                vault_lib.get_fm_value(after_fm, "calendar_event_id"),
                vault_lib.get_fm_value(before_fm, "calendar_event_id"),
            )
            self.assertEqual(
                vault_lib.get_fm_value(after_fm, "date"),
                vault_lib.get_fm_value(before_fm, "date"),
            )
            self.assertEqual(
                vault_lib.get_fm_value(after_fm, "url"),
                vault_lib.get_fm_value(before_fm, "url"),
            )
            self.assertEqual(after_body, before_body)

    def test_set_projectのみでprojectが無ければエラー終了する(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp))
            note_path = vault_root / "dummy.md"
            note_path.write_text('---\nproject: ""\n---\nbody', encoding="utf-8")

            with self.assertRaises(SystemExit):
                meeting_sync.main(
                    [
                        "--set-project",
                        str(note_path),
                        "--vault-root",
                        str(vault_root),
                    ]
                )

    def test_set_projectでプロジェクト解除するとAreas配下へ戻る(self):
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
                    '""',
                    "--vault-root",
                    str(vault_root),
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertFalse(note_path.exists())
            new_path = vault_root / "20_Areas" / "Meetings" / "会議.md"
            self.assertTrue(new_path.exists())
            new_fm, _ = vault_lib.split_frontmatter(
                new_path.read_text(encoding="utf-8")
            )
            self.assertEqual(vault_lib.get_fm_value(new_fm, "project"), "")

    def test_set_projectで既に正しいフォルダにあれば移動しない(self):
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
                    '"[[VaultMigration]]"',
                    "--vault-root",
                    str(vault_root),
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(note_path.exists())
            entries = list(dest_dir.iterdir())
            self.assertEqual(entries, [note_path])

    def test_set_projectで存在しないプロジェクト名を指定するとエラーになりノートは変更されない(
        self,
    ):
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
                        '"[[NonExistent]]"',
                        "--vault-root",
                        str(vault_root),
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertEqual(
                json.loads(stdout.getvalue()),
                {"status": "error", "reason": "project_not_found"},
            )
            self.assertTrue(note_path.exists())
            self.assertEqual(note_path.read_text(encoding="utf-8"), before_text)
            self.assertFalse(
                (vault_root / "10_Projects" / "NonExistent").exists()
            )

    def test_set_projectで移動先に同名ファイルがあれば連番付与される(self):
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
                    '"[[VaultMigration]]"',
                    "--vault-root",
                    str(vault_root),
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertFalse(note_path.exists())
            moved_path = dest_dir / "会議-2.md"
            self.assertTrue(moved_path.exists())
            self.assertTrue(existing_path.exists())
            self.assertIn("body-B", existing_path.read_text(encoding="utf-8"))
            self.assertIn("body-A", moved_path.read_text(encoding="utf-8"))


class TestAttendanceInit(unittest.TestCase):
    def test_単発新規作成でattendanceがscheduledになる(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp))
            event = make_event(id="evt1", summary="定例1on1")
            result = meeting_sync.sync_events([event], vault_root)
            note_path = Path(result["created"][0])
            fm, _body = vault_lib.split_frontmatter(
                note_path.read_text(encoding="utf-8")
            )
            self.assertEqual(vault_lib.get_fm_value(fm, "attendance"), "1_scheduled")

    def test_定例新規作成でfrontmatterとコメント両方にattendanceとdateが入る(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp))
            event = make_event(
                id="occA", summary="週次定例", recurringEventId="seriesX"
            )
            result = meeting_sync.sync_events([event], vault_root)
            note_path = Path(result["created"][0])
            text = note_path.read_text(encoding="utf-8")
            fm, body = vault_lib.split_frontmatter(text)

            self.assertEqual(vault_lib.get_fm_value(fm, "attendance"), "1_scheduled")
            self.assertIn('attendance: "1_scheduled"', body)
            self.assertIn('date: "2026-09-21"', body)


class TestSeriesResyncDate(unittest.TestCase):
    def test_同一occurrenceの日付またぎリスケジュールでコメント内dateが更新される(self):
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
            self.assertIn('date: "2026-09-22"', updated_text)
            self.assertNotIn('date: "2026-09-21"', updated_text)


class TestSeriesCancelAttendance(unittest.TestCase):
    def test_定例で出席者1人以下ならattendanceがskipになる(self):
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
            self.assertIn("(キャンセル)", body)
            self.assertIn('attendance: "3_skip"', body)
            self.assertEqual(vault_lib.get_fm_value(fm, "attendance"), "3_skip")


class TestSeriesTransitionAttendance(unittest.TestCase):
    def test_次回遷移で新ブロックはscheduledにリセットされ旧ブロックの値は退避される(self):
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

            self.assertIn('attendance: "1_scheduled"', current_block)
            self.assertIn('date: "2026-09-28"', current_block)
            self.assertIn('attendance: "2_done"', archive_area)

            fm, _body = vault_lib.split_frontmatter(final_text)
            self.assertEqual(vault_lib.get_fm_value(fm, "attendance"), "1_scheduled")


class TestLegacyOccurrenceFormatMigration(unittest.TestCase):
    def test_旧書式コメントのノートを再同期してもattendanceが空文字に壊れない(self):
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
            self.assertIn('attendance: "1_scheduled"', updated_text)
            self.assertNotIn('attendance: ""', updated_text)
            self.assertEqual(vault_lib.get_fm_value(fm, "attendance"), "1_scheduled")


class TestDeletion(unittest.TestCase):
    def _set_date(self, note_path: Path, date: str) -> None:
        text = note_path.read_text(encoding="utf-8")
        fm, body = vault_lib.split_frontmatter(text)
        fm = vault_lib.set_fm_value(fm, "date", date)
        note_path.write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8")

    def test_今日開催予定でイベントが消えたら物理削除される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp))
            event = make_event(id="evt1", summary="定例1on1")
            result1 = meeting_sync.sync_events([event], vault_root)
            note_path = Path(result1["created"][0])
            self.assertTrue(note_path.exists())
            # make_eventの開催日は固定値のため、テスト実行日に合わせる
            # (実行日をまたぐとdate==today判定がずれてテストが偽装的に
            # 失敗/成功するのを防ぐ)
            self._set_date(note_path, datetime.date.today().isoformat())

            result2 = meeting_sync.sync_events([], vault_root)

            self.assertFalse(note_path.exists())
            self.assertEqual(result2["deleted"], [str(note_path)])

    def test_開催日が過去のノートはイベントが消えていても削除されない(self):
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

            self.assertTrue(note_path.exists())
            self.assertEqual(result2["deleted"], [])

    def test_定例ノートはイベントが消えても削除されない(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp))
            event = make_event(
                id="occA", summary="週次定例", recurringEventId="seriesX"
            )
            result1 = meeting_sync.sync_events([event], vault_root)
            note_path = Path(result1["created"][0])

            result2 = meeting_sync.sync_events([], vault_root)

            self.assertTrue(note_path.exists())
            self.assertEqual(result2["deleted"], [])

    def test_今日のevents一覧に対応するイベントがあれば削除されない(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp))
            event = make_event(id="evt1", summary="定例1on1")
            result1 = meeting_sync.sync_events([event], vault_root)
            note_path = Path(result1["created"][0])

            result2 = meeting_sync.sync_events([event], vault_root)

            self.assertTrue(note_path.exists())
            self.assertEqual(result2["deleted"], [])


class TestNeedsAttendanceCheck(unittest.TestCase):
    def _set_date(self, note_path: Path, date: str) -> None:
        text = note_path.read_text(encoding="utf-8")
        fm, body = vault_lib.split_frontmatter(text)
        fm = vault_lib.set_fm_value(fm, "date", date)
        note_path.write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8")

    def test_単発で開催日が過去かつscheduledのままなら検出される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp))
            event = make_event(id="evt1", summary="定例1on1")
            result1 = meeting_sync.sync_events([event], vault_root)
            note_path = Path(result1["created"][0])
            self._set_date(note_path, "2020-01-01")

            result2 = meeting_sync.sync_events([], vault_root)

            self.assertEqual(
                result2["needs_attendance_check"],
                [{"note_path": str(note_path), "title": "定例1on1"}],
            )

    def test_単発で開催日が今日なら検出されない(self):
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

            self.assertEqual(result2["needs_attendance_check"], [])

    def test_単発でattendanceが確定済みなら開催日が過去でも検出されない(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp))
            event = make_event(id="evt1", summary="定例1on1")
            result1 = meeting_sync.sync_events([event], vault_root)
            note_path = Path(result1["created"][0])
            self._set_date(note_path, "2020-01-01")
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

            self.assertEqual(result2["needs_attendance_check"], [])

    def test_定例で現在occurrenceの開催日が過去かつscheduledのままなら検出される(self):
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

            self.assertEqual(
                result2["needs_attendance_check"],
                [{"note_path": str(note_path), "title": "週次定例"}],
            )

    def test_定例でattendanceが確定済みなら開催日が過去でも検出されない(self):
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

            self.assertEqual(result2["needs_attendance_check"], [])


class TestSetAttendanceMode(unittest.TestCase):
    def test_単発ノートのattendanceが書き換わる(self):
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

            self.assertEqual(exit_code, 0)
            fm, _body = vault_lib.split_frontmatter(
                note_path.read_text(encoding="utf-8")
            )
            self.assertEqual(vault_lib.get_fm_value(fm, "attendance"), "3_skip")

    def test_定例ノートはfrontmatterと現在ブロック両方が書き換わりアーカイブは変わらない(self):
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

            self.assertEqual(exit_code, 0)
            final_text = note_path.read_text(encoding="utf-8")
            fm, _body = vault_lib.split_frontmatter(final_text)
            self.assertEqual(vault_lib.get_fm_value(fm, "attendance"), "2_done")

            start_idx = final_text.find("<!-- NEW_MEETING_START -->")
            end_idx = final_text.find("<!-- NEW_MEETING_END -->")
            current_block = final_text[start_idx:end_idx]
            archive_area = final_text[end_idx:]
            self.assertIn('attendance: "2_done"', current_block)
            # アーカイブされた旧occurrence(occA)のattendanceは
            # 1_scheduledのまま上書きされていない
            self.assertIn('occurrence_id: "occA" attendance: "1_scheduled"', archive_area)
            self.assertNotIn('occurrence_id: "occA" attendance: "2_done"', archive_area)

    def test_存在しないノートを指定するとエラーになる(self):
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

            self.assertEqual(exit_code, 1)
            self.assertEqual(
                json.loads(stdout.getvalue()),
                {"status": "error", "reason": "note_not_found"},
            )

    def test_不正なattendance値はargparseレベルで拒否される(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = make_vault(Path(tmp))
            note_path = vault_root / "dummy.md"
            note_path.write_text("---\ntype: meeting\n---\nbody", encoding="utf-8")

            with self.assertRaises(SystemExit):
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


class TestLinkTaskMode(unittest.TestCase):
    def test_単発ノートでチェックしリンクを追記する(self):
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

            self.assertEqual(exit_code, 0)
            updated = note_path.read_text(encoding="utf-8")
            self.assertIn("- [x] 資料を送る [[資料を送る]]", updated)

    def test_task_note省略時はチェックのみでリンクは付かない(self):
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

            updated = note_path.read_text(encoding="utf-8")
            self.assertIn("- [x] 不要な項目\n", updated)
            self.assertNotIn("[[", updated)

    def test_該当行が無ければエラーでファイルは変更されない(self):
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
                        "--vault-root",
                        str(vault_root),
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertEqual(
                json.loads(stdout.getvalue()),
                {"status": "error", "reason": "item_not_found"},
            )
            self.assertEqual(note_path.read_text(encoding="utf-8"), before_text)

    def test_アクションアイテムセクション外の同一文言は誤爆しない(self):
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
                    "--vault-root",
                    str(vault_root),
                ]
            )

            updated = note_path.read_text(encoding="utf-8")
            self.assertIn("## ⚡ アクションアイテム\n- [x] 資料を送る", updated)
            # 決定事項セクション側の同一文言はチェックされない
            self.assertIn("## 📝 決定事項\n- [ ] 資料を送る", updated)

    def test_定例ノートは現在ブロックのみ置換されアーカイブ領域は変わらない(self):
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

            self.assertIn("- [x] 共通の文言 [[共通タスク]]", current_block)
            self.assertIn("- [ ] 共通の文言", archive_area)
            self.assertNotIn("[[共通タスク]]", archive_area)


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
