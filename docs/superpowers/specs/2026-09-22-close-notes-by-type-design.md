# close: 本日更新ノート一覧のtype別グルーピング 設計仕様

作成日: 2026-09-22
対象リポジトリ: `obsidian`（vaultプラグイン）

## 背景・目的

`close`スキル（`.claude/skills/vault/scripts/close_day.py`）は、1日の作業終了時に当日ブランチの変更をデイリーノートの`<!-- UPDATED_NOTES_START -->`〜`<!-- UPDATED_NOTES_END -->`マーカー間に反映する。

現状は`_collect_updated_paths`→`_filter_updated_notes`でgit diff/git statusから対象ファイルを収集し、ファイル名（拡張子抜き）だけをアルファベット順に並べたフラットな`[[note]]`箇条書きにしている（`_build_updated_notes_block`）。frontmatterの`type`は一切参照していない。

プロジェクト・会議・タスク・ナレッジ等の種別が混在した一覧では、デイリーノートを見返す際に一覧性が低い。本仕様は、更新ノートを`type`ごとにグルーピングして表示する変更を定義する。

## 要件（grillingで確定・ユーザー承認済み）

1. **検出ロジックは変更しない**: `_collect_updated_paths`・`_filter_updated_notes`のgit diff/git statusベースの対象ファイル収集はそのまま使う。
2. **type読み取り**: 対象ファイルごとにfrontmatterから`type`値を読み取る。`vault_lib.split_frontmatter`＋`vault_lib.get_fm_value(fm, "type")`を再利用する。
3. **meeting統合**: `meeting`と`meeting_series`は同一グループに統合し、ラベルは`meeting`で代表する。
4. **other丸め込み**: 以下は区別せず全て`other`グループに丸め込む。動的な新規グループ生成はしない。
   - frontmatter自体が無い、またはfrontmatterに`type`キーが無いノート
   - 既知7種（`daily`/`meeting`/`meeting_series`/`project`/`task`/`knowhow`/`webclip`）以外の未知のtype値を持つノート
5. **表示形式**: Markdownの`#`見出しは使わない。グループ先頭に太字ラベル行（例: `**project**`）を置き、その下に既存形式の`[[note]]`箇条書きを並べる。
6. **グループ順序**: 固定順 `project` → `meeting` → `task` → `knowhow` → `webclip` → `other`。
7. **空グループの省略**: 該当ノートが1件も無いグループはラベル行ごと省略する。
8. **ラベル文字列**: type値をそのまま使用（日本語変換なし）。`other`のみ固定の英語表記`other`。
9. **daily自身の扱い**: 現状通り、当日デイリーノート自身は`_filter_updated_notes`の除外対象のまま変更しない（他typeのnoteとは無関係にそもそも一覧に出てこない）。

### 非対象（Out of Scope）

- `_collect_updated_paths`のgit検出ロジック自体の変更。
- 既存の除外対象（`70_Templates/`配下・`.claude/`配下・当日デイリーノート自身）の見直し。
- `type`の値そのもの（テンプレート側の定義）の変更・新規type追加。
- コミットメッセージ（`"Close daily log for {date}"`固定）の変更。

## 設計

### 対象ファイル

- `.claude/skills/vault/scripts/close_day.py`（`_build_updated_notes_block`の改修、type読み取りヘルパーの追加）
- `.claude/skills/vault/scripts/tests/test_close_day.py`（新規テストケース追加、既存`UpdatedNotesBlockTest`の期待値見直し）

いずれもプロジェクトの`vault_lib.py`にある既存共通関数（`split_frontmatter`・`get_fm_value`）を再利用し、`vault_lib.py`自体への変更は不要（フロー全体の見込み: 1ファイルの実装差分＋1ファイルのテスト差分）。

### 処理フロー（`_build_updated_notes_block`改修後）

1. 既存通り、`_filter_updated_notes`が返すファイル名（stem）のソート済みリストを受け取る……ではなく、**グルーピングにはファイルのフルパスとfrontmatterが必要**なため、`_filter_updated_notes`が返す値をフルパス集合のまま`_build_updated_notes_block`に渡すよう呼び出し側（`main`）のデータフローを見直す（stemへの変換はグルーピング後、表示直前に行う）。
2. 各パスについて、ファイルを読み込み`vault_lib.split_frontmatter`でfrontmatterを分離し、`get_fm_value(fm, "type")`で`type`値を取得する。
   - frontmatterが無い、または`type`キーが無い場合は`None`として扱う。
3. 取得した`type`値を正規化する:
   - `None` または既知7種以外の値 → `other`
   - `meeting_series` → `meeting`
   - それ以外（`project`/`meeting`/`task`/`knowhow`/`webclip`）はそのまま
   - （`daily`は`_filter_updated_notes`の既存除外により実質到達しないが、到達した場合も`other`扱いとする）
4. 正規化した type をキーに、ノートのファイル名（stem）をグルーピングする。各グループ内は既存と同じPython文字列比較によるソート順（`sorted()`）を踏襲する。
5. グループを固定順 `project, meeting, task, knowhow, webclip, other` で走査し、ノートが1件以上あるグループのみ、太字ラベル行＋箇条書きを出力に追加する。
6. 完成したMarkdown文字列を`vault_lib.set_marker_block`でマーカー間に書き戻す（既存の書き戻しロジックは変更なし）。

### 出力フォーマット例

```
<!-- UPDATED_NOTES_START -->
**project**
- [[Linux資格取得]]
- [[Python資格取得]]

**meeting**
- [[2026-09-21 Python試験対策会議]]
- [[2026-09-21 test会議]]

**other**
- [[CLAUDE]]
- [[README]]
<!-- UPDATED_NOTES_END -->
```

### エラーハンドリング

- 対象ファイルが既に削除済み（git statusで検出されたが実体が無い等の既存の想定外ケース）の扱いは、現行の`_filter_updated_notes`の挙動を変更しないため、本仕様では追加のハンドリングをしない。
- frontmatterのパース自体に失敗するケース（YAML構文エラー等）は既存の`vault_lib.split_frontmatter`/`get_fm_value`の挙動に委ね、本仕様では追加の例外処理を行わない（対症療法的なtry/exceptの追加はCLAUDE.mdの方針に反するため見送り、既存共通関数の契約に従う）。

## テスト方針

- テスト種別: unit一層のみ（`python-unittest`プロファイル）。
- 既存の`UpdatedNotesBlockTest.test_更新ノート一覧の反映と除外対象の除外`は、フラットリスト前提の期待値になっているため、type別グルーピング後の期待値に更新する（既存テストの削除ではなく仕様変更に伴う期待値更新）。
- 新規テストケース（RED→GREENで追加）:
  1. 複数typeのノートが正しくグループ分けされ、固定順で出力される。
  2. `meeting`と`meeting_series`が同一グループに統合される。
  3. type未定義ノート（frontmatterなし／typeキーなし）が`other`グループに入る。
  4. 既知7種以外の未知type値のノートが`other`グループに入る。
  5. 該当ノートが0件のtypeグループの太字ラベルが出力に現れない。
  6. 単一typeのみ更新があった場合、そのグループのみ出力される（既存の「変更なし」テストとの整合）。

## 実装差分の見込み規模

- `close_day.py`: `_build_updated_notes_block`の書き換え＋frontmatter読み取り・正規化・グルーピングの小関数追加。実装差分は概算50行前後。
- `test_close_day.py`: 新規テストケース6件程度の追加＋既存1件の期待値更新。
- 公開インターフェース（CLI引数・標準出力JSONのスキーマ）は不変。変わるのはデイリーノートのマーカーブロック内のMarkdown内容のみ。

この規模はCLAUDE.mdの「small」定義（差分≤2ファイル・実装差分≤50行・公開IF不変・既存テストが対象を被覆）に近いが、「既存テストが対象を被覆」の条件は満たさない（既存テストはフラットリスト前提であり、type別グルーピングという新しい振る舞いを事前には被覆していない）。最終的なsmall/substantial判定はCP-Bで`tdd-evaluator`が行う。
