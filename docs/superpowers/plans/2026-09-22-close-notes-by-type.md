# close: 更新ノート一覧のtype別グルーピング Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `close`スキル（`close_day.py`）が当日デイリーノートに書き出す「本日作成・更新したノート」一覧を、frontmatterの`type`ごとにグルーピングして表示するようにする。

**Architecture:** `_filter_updated_notes`を`(stem, フルパス)`のtupleリストを返すよう変更し、新設する`_read_note_type`/`_normalize_note_type`でtype判定・正規化を行い、`_build_updated_notes_block`が固定順でグルーピングしたMarkdownを組み立てる。JSON出力の`updated_notes`フィールド（stemのソート済みリスト）は現状のまま変更しない。

**Tech Stack:** Python 3（標準ライブラリのみ、外部パッケージ不可）。テストは`unittest`（`python -m unittest discover -s tests`）。

**Spec:** `docs/superpowers/specs/2026-09-22-close-notes-by-type-design.md`

## Global Constraints

- 検出ロジック（`_collect_updated_paths`のgit diff/git statusベースの収集）は変更しない。
- 既存の除外条件（当日デイリーノート自身・`70_Templates/`配下・`.claude/`配下・非`.md`）は変更しない。
- 公開インターフェース（CLI引数`--vault-root`・標準出力JSONのスキーマ）は不変。JSON出力の`updated_notes`はstemのソート済みリストのまま変更しない。
- 外部パッケージを使わず標準ライブラリのみで実装する（`requirements.txt`等は追加しない）。
- テスト実行コマンド: `cd .claude/skills/vault/scripts && PYTHONUTF8=1 python -m unittest discover -s tests`（全件）。単一テストは`PYTHONUTF8=1 python -m unittest tests.test_close_day.<Class>.<method> -v`。
- 各タスクの実装後、既存139件+追加分のテストスイート全体を壊さないことを確認してからコミットする（`obsidian`リポジトリCLAUDE.md「新スクリプト実装時のテスト方針」準拠）。

---

### Task 1: type正規化・読み取りヘルパー関数（`_normalize_note_type` / `_read_note_type`）

**Files:**
- Modify: `.claude/skills/vault/scripts/close_day.py`（モジュール定数と2関数の追加）
- Modify: `.claude/skills/vault/scripts/tests/test_close_day.py`（`close_day`モジュールを直接importする準備＋新規テストクラス追加）

**Interfaces:**
- Consumes: `vault_lib.split_frontmatter(text: str) -> tuple[str, str]`、`vault_lib.get_fm_value(fm_text: str, key: str) -> str | None`（既存関数、変更なし）。
- Produces: `_normalize_note_type(raw_type: str | None) -> str`、`_read_note_type(path: Path) -> str | None`。後続タスクがこの2関数を使う。

- [ ] **Step 1: テストファイルで`close_day`モジュールを直接importできるようにする**

`test_close_day.py`冒頭のimport群を以下のように変更する（`_SCRIPTS_DIR`定義の直後に追加）:

```python
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
_CLOSE_DAY = _SCRIPTS_DIR / "close_day.py"

sys.path.insert(0, str(_SCRIPTS_DIR))
import close_day  # noqa: E402
```

- [ ] **Step 2: 失敗するテストを書く**

`test_close_day.py`の末尾（`if __name__ == "__main__":`の直前）に以下のテストクラスを追加する。

```python
class NoteTypeHelpersTest(unittest.TestCase):
    def test_normalize_meeting_seriesはmeetingに統合される(self):
        self.assertEqual(close_day._normalize_note_type("meeting_series"), "meeting")

    def test_normalize_既知typeはそのまま(self):
        for known in ("project", "meeting", "task", "knowhow", "webclip"):
            with self.subTest(known=known):
                self.assertEqual(close_day._normalize_note_type(known), known)

    def test_normalize_未知typeはotherになる(self):
        self.assertEqual(close_day._normalize_note_type("unknown_type"), "other")

    def test_normalize_Noneはotherになる(self):
        self.assertEqual(close_day._normalize_note_type(None), "other")

    def test_read_note_type_frontmatterのtype値を取得する(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.md"
            path.write_text("---\ntype: project\n---\nbody", encoding="utf-8")
            self.assertEqual(close_day._read_note_type(path), "project")

    def test_read_note_type_typeキーが無ければNone(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.md"
            path.write_text("---\ntags:\n  - x\n---\nbody", encoding="utf-8")
            self.assertIsNone(close_day._read_note_type(path))

    def test_read_note_type_frontmatterが無ければNone(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.md"
            path.write_text("plain body without frontmatter", encoding="utf-8")
            self.assertIsNone(close_day._read_note_type(path))

    def test_read_note_type_ファイルが存在しなければNone(self):
        missing_path = Path(tempfile.gettempdir()) / "does_not_exist_close_day_test.md"
        self.assertFalse(missing_path.exists())
        self.assertIsNone(close_day._read_note_type(missing_path))
```

- [ ] **Step 3: テストを実行し失敗を確認する**

Run: `cd .claude/skills/vault/scripts && PYTHONUTF8=1 python -m unittest tests.test_close_day.NoteTypeHelpersTest -v`
Expected: `AttributeError: module 'close_day' has no attribute '_normalize_note_type'`（または`_read_note_type`）でFAIL。

- [ ] **Step 4: 最小実装を書く**

`close_day.py`の`_EXCLUDED_PREFIXES = ("70_Templates/", ".claude/")`定義の直後に以下を追加する。

```python
# 更新ノート一覧から除外するパス接頭辞
_EXCLUDED_PREFIXES = ("70_Templates/", ".claude/")

# frontmatterのtype値のうちグループとして認識する既知の値
_KNOWN_TYPES = ("project", "meeting", "task", "knowhow", "webclip")

# 更新ノート一覧の表示グループ順(固定)。otherは既知7種以外・type未定義の受け皿。
_TYPE_GROUP_ORDER = ("project", "meeting", "task", "knowhow", "webclip", "other")


def _normalize_note_type(raw_type: str | None) -> str:
    """frontmatterのtype値をグルーピング用のtypeキーへ正規化する。

    meeting_seriesはmeetingへ統合し、既知7種以外・type未定義はotherへ丸め込む。
    """
    if raw_type == "meeting_series":
        return "meeting"
    if raw_type in _KNOWN_TYPES:
        return raw_type
    return "other"


def _read_note_type(path: Path) -> str | None:
    """ノートファイルを読み込みfrontmatterのtype値を返す。

    ファイル読み込みでI/Oエラー(FileNotFoundError等)が起きた場合はNoneを返す
    (呼び出し側の_normalize_note_typeによりotherへ丸め込まれる)。
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    fm_text, _ = vault_lib.split_frontmatter(text)
    return vault_lib.get_fm_value(fm_text, "type")
```

- [ ] **Step 5: テストを実行し成功を確認する**

Run: `cd .claude/skills/vault/scripts && PYTHONUTF8=1 python -m unittest tests.test_close_day.NoteTypeHelpersTest -v`
Expected: `OK`（8 tests）

- [ ] **Step 6: 全体回帰確認**

Run: `cd .claude/skills/vault/scripts && PYTHONUTF8=1 python -m unittest discover -s tests`
Expected: 既存の全テスト（本タスク追加分含む）が`OK`。

- [ ] **Step 7: コミット**

```bash
git add .claude/skills/vault/scripts/close_day.py .claude/skills/vault/scripts/tests/test_close_day.py
git commit -m "Add note-type normalization and frontmatter type reader for close skill"
```

---

### Task 2: `_filter_updated_notes`をtuple化しJSON出力契約を維持する

**Files:**
- Modify: `.claude/skills/vault/scripts/close_day.py`（`_filter_updated_notes`のシグネチャ変更・`main`の呼び出し側修正）
- Modify: `.claude/skills/vault/scripts/tests/test_close_day.py`（新規テストクラス追加）

**Interfaces:**
- Consumes: Task 1の成果物は未使用（本タスクは`_filter_updated_notes`単体の改修）。
- Produces: `_filter_updated_notes(paths: set[str], date_str: str, vault_root: Path) -> list[tuple[str, Path]]`（stemでソート済み）。Task 3がこの戻り値を`_build_updated_notes_block`に渡す。

**注意（既存動作を壊さないための境界線）**: 本タスクでは`_build_updated_notes_block`自体は変更しない（引数は従来通り`list[str]`のまま）。`main`側で`entries`からstemのみを取り出して渡すことで、既存の全テストが無改修で緑のまま維持される。

- [ ] **Step 1: 失敗するテストを書く**

`test_close_day.py`の`NoteTypeHelpersTest`の後に追加する。

```python
class FilterUpdatedNotesTupleTest(unittest.TestCase):
    def test_stemとフルパスのtupleリストをソート済みで返す(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = Path(tmp)
            paths = {
                "20_Notes/Beta.md",
                "20_Notes/Alpha.md",
                "70_Templates/x.md",
                "images/a.png",
                "00_Daily/2026-09-22.md",
            }
            entries = close_day._filter_updated_notes(paths, "2026-09-22", vault_root)
            self.assertEqual(
                entries,
                [
                    ("Alpha", vault_root / "20_Notes/Alpha.md"),
                    ("Beta", vault_root / "20_Notes/Beta.md"),
                ],
            )
```

- [ ] **Step 2: テストを実行し失敗を確認する**

Run: `cd .claude/skills/vault/scripts && PYTHONUTF8=1 python -m unittest tests.test_close_day.FilterUpdatedNotesTupleTest -v`
Expected: `TypeError: _filter_updated_notes() takes 2 positional arguments but 3 were given`でFAIL。

- [ ] **Step 3: 実装を変更する**

`close_day.py`の`_filter_updated_notes`関数を以下に置き換える。

```python
def _filter_updated_notes(
    paths: set[str], date_str: str, vault_root: Path
) -> list[tuple[str, Path]]:
    """close対象外(当日ノート自身/テンプレート/.claude配下/非.md)を除外し、
    (ファイル名(拡張子除く), フルパス) のstemソート済みリストを返す。
    """
    daily_note_path = f"00_Daily/{date_str}.md"
    entries: list[tuple[str, Path]] = []
    for path in paths:
        normalized = path.replace("\\", "/")
        if not normalized.endswith(".md"):
            continue
        if normalized == daily_note_path:
            continue
        if any(normalized.startswith(prefix) for prefix in _EXCLUDED_PREFIXES):
            continue
        entries.append((Path(normalized).stem, vault_root / normalized))
    return sorted(entries, key=lambda entry: entry[0])
```

`main`関数内の呼び出し箇所（`# 2-4. 更新ノート一覧を作成する`コメントの直後）を以下に置き換える。

```python
    # 2-4. 更新ノート一覧を作成する
    updated_paths = _collect_updated_paths(vault_root)
    entries = _filter_updated_notes(updated_paths, date_str, vault_root)
    note_names = [stem for stem, _ in entries]
    block_text = _build_updated_notes_block(note_names)
```

- [ ] **Step 4: テストを実行し成功を確認する**

Run: `cd .claude/skills/vault/scripts && PYTHONUTF8=1 python -m unittest tests.test_close_day.FilterUpdatedNotesTupleTest -v`
Expected: `OK`

- [ ] **Step 5: 全体回帰確認（JSON出力契約が壊れていないことの確認）**

Run: `cd .claude/skills/vault/scripts && PYTHONUTF8=1 python -m unittest discover -s tests`
Expected: 既存の全テスト（`QuotedPathTest`・`NewProjectDirectoryTest`・`UpdatedNotesBlockTest`含む）が無改修のまま`OK`。

- [ ] **Step 6: コミット**

```bash
git add .claude/skills/vault/scripts/close_day.py .claude/skills/vault/scripts/tests/test_close_day.py
git commit -m "Change _filter_updated_notes to return stem/path tuples"
```

---

### Task 3: `_build_updated_notes_block`のtype別グルーピング実装

**Files:**
- Modify: `.claude/skills/vault/scripts/close_day.py`（`_build_updated_notes_block`の書き換え・`main`の呼び出し変更）
- Modify: `.claude/skills/vault/scripts/tests/test_close_day.py`（既存`UpdatedNotesBlockTest`の期待値更新＋新規テストクラス追加）

**Interfaces:**
- Consumes: Task 1の`_normalize_note_type`・`_read_note_type`、Task 2の`_filter_updated_notes`の戻り値`list[tuple[str, Path]]`。
- Produces: `_build_updated_notes_block(entries: list[tuple[str, Path]]) -> str`（`main`から`entries`をそのまま渡す形に変更）。

- [ ] **Step 1: 既存テストの期待値を更新する（type未定義ノートは`other`グループに入るため）**

`test_close_day.py`の`UpdatedNotesBlockTest.test_更新ノート一覧の反映と除外対象の除外`内、次の3行を:

```python
            self.assertIn("- [[Alpha]]", merged_note_text)
            self.assertIn("- [[Beta]]", merged_note_text)
            self.assertNotIn("scratch", merged_note_text)
```

以下に置き換える（`Alpha.md`・`Beta.md`はfrontmatterが無くtype未定義のため、正規化ルールにより`other`グループに入る）。

```python
            self.assertIn("**other**", merged_note_text)
            self.assertIn("- [[Alpha]]", merged_note_text)
            self.assertIn("- [[Beta]]", merged_note_text)
            self.assertNotIn("scratch", merged_note_text)
```

- [ ] **Step 2: 失敗する新規テストを書く**

`test_close_day.py`の`FilterUpdatedNotesTupleTest`の後に追加する。

```python
class TypeGroupingTest(unittest.TestCase):
    def test_type別に固定順でグルーピングされmeeting_seriesはmeetingへ統合される(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            _write(root / "00_Daily" / ".gitkeep", "")
            _write(root / "70_Templates" / "Daily_Template.md", "template")
            _commit_all(root, "initial commit")

            branch = "2026-09-28"
            _run_git(["checkout", "-b", branch], cwd=root)
            daily_note = root / "00_Daily" / f"{branch}.md"
            _write(daily_note, _DAILY_NOTE_TEMPLATE.format(date=branch))

            _write(root / "10_Projects" / "Zeta.md", "---\ntype: project\n---\nbody")
            _write(
                root / "10_Projects" / "Meetings" / "Alpha.md",
                "---\ntype: meeting\n---\nbody",
            )
            _write(
                root / "10_Projects" / "Meetings" / "Weekly.md",
                "---\ntype: meeting_series\n---\nbody",
            )
            _write(root / "40_Tasks" / "DoThing.md", "---\ntype: task\n---\nbody")

            result = _run_close_day(root)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                sorted(payload["updated_notes"]),
                ["Alpha", "DoThing", "Weekly", "Zeta"],
            )

            _run_git(["checkout", "main"], cwd=root)
            merged = (root / "00_Daily" / f"{branch}.md").read_text(encoding="utf-8")

            project_idx = merged.index("**project**")
            meeting_idx = merged.index("**meeting**")
            task_idx = merged.index("**task**")
            self.assertLess(project_idx, meeting_idx)
            self.assertLess(meeting_idx, task_idx)
            self.assertIn("- [[Zeta]]", merged)
            self.assertIn("- [[Alpha]]", merged)
            self.assertIn("- [[Weekly]]", merged)
            self.assertIn("- [[DoThing]]", merged)
            self.assertEqual(merged.count("**meeting**"), 1)
            self.assertNotIn("**meeting_series**", merged)
            self.assertNotIn("**knowhow**", merged)
            self.assertNotIn("**webclip**", merged)
            self.assertNotIn("**other**", merged)

    def test_単一typeのみ更新時はそのグループのみ表示される(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            _write(root / "00_Daily" / ".gitkeep", "")
            _write(root / "70_Templates" / "Daily_Template.md", "template")
            _commit_all(root, "initial commit")

            branch = "2026-09-29"
            _run_git(["checkout", "-b", branch], cwd=root)
            daily_note = root / "00_Daily" / f"{branch}.md"
            _write(daily_note, _DAILY_NOTE_TEMPLATE.format(date=branch))
            _write(root / "30_Knowhow" / "Tip.md", "---\ntype: knowhow\n---\nbody")

            result = _run_close_day(root)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            _run_git(["checkout", "main"], cwd=root)
            merged = (root / "00_Daily" / f"{branch}.md").read_text(encoding="utf-8")
            self.assertIn("**knowhow**", merged)
            self.assertIn("- [[Tip]]", merged)
            for absent in ("**project**", "**meeting**", "**task**", "**webclip**", "**other**"):
                self.assertNotIn(absent, merged)
```

- [ ] **Step 3: テストを実行し失敗を確認する**

Run: `cd .claude/skills/vault/scripts && PYTHONUTF8=1 python -m unittest tests.test_close_day.UpdatedNotesBlockTest tests.test_close_day.TypeGroupingTest -v`
Expected: `UpdatedNotesBlockTest`は`**other**`が出力に無く`AssertionError`でFAIL。`TypeGroupingTest`も`**project**`等が無く`AssertionError`でFAIL（現状はフラットな`- [[name]]`形式のため）。

- [ ] **Step 4: 実装を変更する**

`close_day.py`の`_build_updated_notes_block`関数を以下に置き換える。

```python
def _build_updated_notes_block(entries: list[tuple[str, Path]]) -> str:
    """更新ノート一覧からtype別にグルーピングしたマーカーブロック内テキストを組み立てる。

    entriesは_filter_updated_notesが返すstemソート済みの(stem, フルパス)リスト。
    グループ内の順序はentriesの並び(=stemソート順)をそのまま引き継ぐ。
    """
    if not entries:
        return "- （本日の更新ノートなし）"

    groups: dict[str, list[str]] = {key: [] for key in _TYPE_GROUP_ORDER}
    for stem, path in entries:
        raw_type = _read_note_type(path)
        groups[_normalize_note_type(raw_type)].append(stem)

    lines: list[str] = []
    for group_key in _TYPE_GROUP_ORDER:
        stems = groups[group_key]
        if not stems:
            continue
        if lines:
            lines.append("")
        lines.append(f"**{group_key}**")
        lines.extend(f"- [[{stem}]]" for stem in stems)
    return "\n".join(lines)
```

`main`関数内の呼び出し箇所を以下に置き換える（`_build_updated_notes_block`への引数を`note_names`から`entries`に変更）。

```python
    # 2-4. 更新ノート一覧を作成する
    updated_paths = _collect_updated_paths(vault_root)
    entries = _filter_updated_notes(updated_paths, date_str, vault_root)
    note_names = [stem for stem, _ in entries]
    block_text = _build_updated_notes_block(entries)
```

- [ ] **Step 5: テストを実行し成功を確認する**

Run: `cd .claude/skills/vault/scripts && PYTHONUTF8=1 python -m unittest tests.test_close_day.UpdatedNotesBlockTest tests.test_close_day.TypeGroupingTest -v`
Expected: `OK`

- [ ] **Step 6: 全体回帰確認**

Run: `cd .claude/skills/vault/scripts && PYTHONUTF8=1 python -m unittest discover -s tests`
Expected: 全テストが`OK`（`NoChangesTest`・`AlreadyClosedTest`・`MergeFailedTest`は`entries`が空の分岐に入り、既存の固定文言`- （本日の更新ノートなし）`のまま無改修で緑）。

- [ ] **Step 7: コミット**

```bash
git add .claude/skills/vault/scripts/close_day.py .claude/skills/vault/scripts/tests/test_close_day.py
git commit -m "Group updated notes by type in close daily note block"
```

---

### Task 4: 境界ケース（未知type・削除済みファイルのotherフォールバック）

**Files:**
- Modify: `.claude/skills/vault/scripts/tests/test_close_day.py`（新規テストクラス追加のみ。実装は Task 1〜3 で完了済み）

**Interfaces:**
- Consumes: Task 1〜3の全成果物（`_normalize_note_type`・`_read_note_type`・`_filter_updated_notes`・`_build_updated_notes_block`）。新規実装コードは無い（既存実装で境界ケースが正しく処理されることの確認テストのみ）。

- [ ] **Step 1: 失敗する可能性のあるテストを書く**

`test_close_day.py`の`TypeGroupingTest`の後に追加する。

```python
class UnknownAndDeletedTypeFallbackTest(unittest.TestCase):
    def test_未知typeと削除済みファイルはotherグループに入る(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            _write(root / "00_Daily" / ".gitkeep", "")
            _write(root / "70_Templates" / "Daily_Template.md", "template")
            _commit_all(root, "initial commit")

            branch = "2026-09-27"
            _run_git(["checkout", "-b", branch], cwd=root)
            daily_note = root / "00_Daily" / f"{branch}.md"
            _write(daily_note, _DAILY_NOTE_TEMPLATE.format(date=branch))

            # 未知のtype値を持つノート
            _write(root / "20_Notes" / "Mystery.md", "---\ntype: mystery\n---\nbody")

            # 追跡済みファイルを削除する
            # (git statusでは'D'として検出されるが実体はもう無い)
            deleted_note = root / "20_Notes" / "Ghost.md"
            _write(deleted_note, "---\ntype: project\n---\nbody")
            _commit_all(root, "add ghost note")
            deleted_note.unlink()

            result = _run_close_day(root)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(sorted(payload["updated_notes"]), ["Ghost", "Mystery"])

            _run_git(["checkout", "main"], cwd=root)
            merged = (root / "00_Daily" / f"{branch}.md").read_text(encoding="utf-8")
            self.assertIn("**other**", merged)
            self.assertIn("- [[Mystery]]", merged)
            self.assertIn("- [[Ghost]]", merged)
            self.assertNotIn("**project**", merged)
```

- [ ] **Step 2: テストを実行する**

Run: `cd .claude/skills/vault/scripts && PYTHONUTF8=1 python -m unittest tests.test_close_day.UnknownAndDeletedTypeFallbackTest -v`
Expected: Task 1〜3の実装が正しければ`OK`（既に実装済みの`_read_note_type`のI/Oエラーフォールバックと`_normalize_note_type`の未知typeフォールバックにより、追加実装なしで通る想定）。**もし`FileNotFoundError`が捕捉されず例外で落ちる、または`Mystery`/`Ghost`が`other`グループに入らない場合は、Task 1で実装した`_read_note_type`/`_normalize_note_type`にバグがあるため、該当関数を修正してから再実行する。**

- [ ] **Step 3: 全体回帰確認**

Run: `cd .claude/skills/vault/scripts && PYTHONUTF8=1 python -m unittest discover -s tests`
Expected: 全テストが`OK`。

- [ ] **Step 4: コミット**

```bash
git add .claude/skills/vault/scripts/tests/test_close_day.py
git commit -m "Add regression test for unknown type and deleted file fallback to other group"
```

---

## CP-E / CP-F の適用状況

- **CP-E（CI品質ゲート整備）**: スキップ。本リポジトリはCI（GitHub Actions等）を運用していない。
- **CP-F（ドキュメント同期）**: スキップ。`.claude/skills/vault/skills/close/SKILL.md`はJSON出力フィールドの説明のみでマーカーブロック内のMarkdown表示形式（フラット/グルーピング）には言及しておらず、`.claude/skills/vault/references/conventions.md`もマーカー機構の一般的な説明のみで表示形式には触れていない。本変更で記載事実が古くなるドキュメントカテゴリ（README・ガイド・API仕様・セキュリティ設計書・リリースノート）は存在しない（該当箇所`file:line`の根拠なし）。
