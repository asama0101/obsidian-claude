# close: 本日更新ノート一覧のtype別グルーピング 設計仕様

作成日: 2026-09-22
対象リポジトリ: `obsidian`（vaultプラグイン）

## 背景・目的

`close`スキル（`.claude/skills/vault/scripts/close_day.py`）は、1日の作業終了時に当日ブランチの変更をデイリーノートの`<!-- UPDATED_NOTES_START -->`〜`<!-- UPDATED_NOTES_END -->`マーカー間に反映する。

現状は`_collect_updated_paths`→`_filter_updated_notes`でgit diff/git statusから対象ファイルを収集し、ファイル名（拡張子抜き）だけをアルファベット順に並べたフラットな`[[note]]`箇条書きにしている（`_build_updated_notes_block`）。frontmatterの`type`は一切参照していない。

プロジェクト・会議・タスク・ナレッジ等の種別が混在した一覧では、デイリーノートを見返す際に一覧性が低い。本仕様は、更新ノートを`type`ごとにグルーピングして表示する変更を定義する。

## 要件（grillingで確定・ユーザー承認済み）

1. **検出ロジックは変更しない**: `_collect_updated_paths`・`_filter_updated_notes`のgit diff/git statusベースの対象ファイル収集・除外条件はそのまま使う。
2. **type読み取り**: 対象ファイルごとにfrontmatterから`type`値を読み取る。`vault_lib.split_frontmatter`＋`vault_lib.get_fm_value(fm, "type")`を再利用する。
3. **meeting統合**: `meeting`と`meeting_series`は同一グループに統合し、ラベルは`meeting`で代表する。
4. **other丸め込み**: 以下は区別せず全て`other`グループに丸め込む。動的な新規グループ生成はしない。
   - frontmatter自体が無い、またはfrontmatterに`type`キーが無いノート
   - 既知7種（`daily`/`meeting`/`meeting_series`/`project`/`task`/`knowhow`/`webclip`）以外の未知のtype値を持つノート
   - frontmatter読み取り時にI/Oエラー（対象ファイルがgit status検出後に削除済み等）が起きたノート（要件11参照）
5. **表示形式**: Markdownの`#`見出しは使わない。グループ先頭に太字ラベル行（例: `**project**`）を置き、その下に既存形式の`[[note]]`箇条書きを並べる。
6. **グループ順序**: 固定順 `project` → `meeting` → `task` → `knowhow` → `webclip` → `other`。
7. **空グループの省略**: 該当ノートが1件も無いグループはラベル行ごと省略する。
8. **ラベル文字列**: type値をそのまま使用（日本語変換なし）。`other`のみ固定の英語表記`other`。
9. **daily自身の扱い**: 現状通り、当日デイリーノート自身は`_filter_updated_notes`の除外対象のまま変更しない（他typeのnoteとは無関係にそもそも一覧に出てこない）。
10. **JSON出力契約の維持（CP-A指摘により追加）**: `_filter_updated_notes`は現在、戻り値`note_names`がマーカーブロック生成とJSON標準出力の`updated_notes`フィールドの両方に使われている（`close_day.py:157,221`）。この既存契約は変更しない。具体的には、`_filter_updated_notes`の戻り値を`list[tuple[str, Path]]`（stem, フルパス）に変更し、`main`側でJSON出力用には各tupleの`stem`要素のみを取り出したリストを`updated_notes`に渡す。既存テスト（`QuotedPathTest`・`NewProjectDirectoryTest`）が検証するJSON出力の内容・形（stemのソート済みリスト）は変更しない。
11. **frontmatter読み取り失敗時のフォールバック（CP-A指摘により追加）**: frontmatter読み取り時にファイル読み込みが失敗した場合（`FileNotFoundError`等のI/Oエラー）、closeの処理全体は継続し、該当ノートは`other`グループに含める（要件4参照）。
12. **全体0件時の表示継続性（CP-A指摘により追加）**: 本日の更新ノートが全体で0件（`_filter_updated_notes`の戻り値が空）の場合、現行の固定文言`- （本日の更新ノートなし）`をそのまま出力する。太字ラベル行は一切出さない。

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

0. `_filter_updated_notes`のシグネチャを`_filter_updated_notes(paths: set[str], date_str: str, vault_root: Path) -> list[tuple[str, Path]]`に変更する。既存の除外条件・stemベースのソート順は変更せず、戻り値の各要素を`(stem, vault_root / normalized_path)`のtupleにする（要件10）。
1. `main`は、この戻り値から`[stem for stem, _ in entries]`を取り出してJSON出力の`updated_notes`に渡す（既存契約を維持）。`_build_updated_notes_block`には`entries`（tupleのリスト）をそのまま渡す。
2. `_build_updated_notes_block(entries)`は、`entries`が空なら**既存の固定文言`- （本日の更新ノートなし）`を返して終了する**（要件12。以降のステップは実行しない）。
3. 各`(stem, path)`について、`path`のファイルを読み込み`vault_lib.split_frontmatter`でfrontmatterを分離し、`get_fm_value(fm, "type")`で`type`値を取得する。
   - frontmatterが無い、または`type`キーが無い場合は`None`として扱う。
   - ファイル読み込みでI/Oエラー（`FileNotFoundError`等）が発生した場合は`None`として扱う（要件11。例外はここで捕捉し、以降の正規化ステップで`other`に丸め込む。他の予期しない例外は握りつぶさず伝播させる）。
4. 取得した`type`値を正規化する:
   - `None` または既知7種以外の値 → `other`
   - `meeting_series` → `meeting`
   - それ以外（`project`/`meeting`/`task`/`knowhow`/`webclip`）はそのまま
   - （`daily`は`_filter_updated_notes`の既存除外により実質到達しないが、到達した場合も`other`扱いとする）
5. 正規化した type をキーに、ノートのstemをグルーピングする。各グループ内は既存と同じPython文字列比較によるソート順（`sorted()`）を踏襲する。
6. グループを固定順 `project, meeting, task, knowhow, webclip, other` で走査し、ノートが1件以上あるグループのみ、太字ラベル行＋箇条書きを出力に追加する。
7. 完成したMarkdown文字列を`vault_lib.set_marker_block`でマーカー間に書き戻す（既存の書き戻しロジックは変更なし）。

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

- 対象ファイルが既にI/Oエラー（git status検出後にファイルが削除済み等）でfrontmatter読み込みに失敗した場合、該当ノートを`other`グループへフォールバックし、close処理全体は継続する（要件11。`_build_updated_notes_block`内でこの1箇所のみ`FileNotFoundError`等のI/Oエラーを捕捉する。他の想定外例外は伝播させ、広いtry/exceptは設けない）。
- frontmatterのパース自体に失敗するケース（YAML構文エラー等）は既存の`vault_lib.split_frontmatter`/`get_fm_value`の挙動に委ね、本仕様では追加の例外処理を行わない（既存共通関数の契約に従う）。

## テスト方針

- テスト種別: unit一層のみ（`python-unittest`プロファイル）。
- 既存の`UpdatedNotesBlockTest.test_更新ノート一覧の反映と除外対象の除外`は、フラットリスト前提の期待値になっているため、type別グルーピング後の期待値に更新する（既存テストの削除ではなく仕様変更に伴う期待値更新）。呼び出しシグネチャの変更（`vault_root`引数追加）に合わせてテストの呼び出しコードも更新する。
- `QuotedPathTest`・`NewProjectDirectoryTest`など、JSON出力の`updated_notes`フィールド（stemリスト）を直接検証する既存テストは、期待値を変更せずそのまま緑を維持することを確認する（要件10の回帰確認）。
- 新規テストケース（RED→GREENで追加）:
  1. 複数typeのノートが正しくグループ分けされ、固定順で出力される。
  2. `meeting`と`meeting_series`が同一グループに統合される。
  3. type未定義ノート（frontmatterなし／typeキーなし）が`other`グループに入る。
  4. 既知7種以外の未知type値のノートが`other`グループに入る。
  5. 該当ノートが0件のtypeグループの太字ラベルが出力に現れない。
  6. 単一typeのみ更新があった場合、そのグループのみ出力される（既存の「変更なし」テストとの整合）。
  7. frontmatter読み込みでI/Oエラーが発生したノートが`other`グループに入る（要件11）。
  8. 更新ノートが全体で0件の場合、既存の固定文言`- （本日の更新ノートなし）`がそのまま出力される（要件12）。

## 実装差分の見込み規模

- `close_day.py`: `_filter_updated_notes`のシグネチャ変更（`vault_root`引数追加、戻り値のtuple化）＋`main`の呼び出し箇所修正（JSON出力用にstemを取り出す）＋`_build_updated_notes_block`の書き換え＋frontmatter読み取り・正規化・グルーピングの小関数追加。実装差分は概算60〜70行前後（CP-A指摘対応で当初見積もりの50行から増加）。
- `test_close_day.py`: 新規テストケース8件程度の追加＋既存1件（`UpdatedNotesBlockTest`）の期待値・呼び出しコード更新。`QuotedPathTest`・`NewProjectDirectoryTest`は無改修で回帰確認のみ。
- 公開インターフェース（CLI引数・標準出力JSONのスキーマ）は不変。変わるのはデイリーノートのマーカーブロック内のMarkdown内容のみ。`_filter_updated_notes`はモジュール内部関数（`_`プレフィックス）でありモジュール外への公開IFではないため、シグネチャ変更は「公開IF不変」の判定に抵触しない。

この規模はCLAUDE.mdの「small」定義（差分≤2ファイル・実装差分≤50行・公開IF不変・既存テストが対象を被覆）の行数上限を超え、「既存テストが対象を被覆」の条件も満たさない（既存テストはフラットリスト前提であり、type別グルーピングという新しい振る舞いを事前には被覆していない）。最終的なsmall/substantial判定はCP-Bで`tdd-evaluator`が行うが、上記よりsubstantial判定が濃厚である。
