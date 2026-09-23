# 定例予定ノートの更新ロジック（occurrence_idによる区別）

`meeting_sync.py`が定例予定（Google Calendarの`recurringEventId`を持つ
イベント）を`Meeting_Series_Template.md`ベースのノートへ同期する際の
判定ロジックを説明する。実装は`_process_series_event`とその補助関数
（`meeting_sync.py`内）。

## なぜoccurrence_idで区別するのか

定例予定は「同じ回のリスケジュール（時刻変更・場所変更など）」と
「次回への遷移（第n回→第n+1回）」を区別する必要がある。どちらも
カレンダー側の`start.dateTime`が変わるという点では見分けがつかない
（リスケジュールも日時が変わる）。

そこで、各回のイベント固有ID（Google Calendarイベントの`id`。
`recurringEventId`は「シリーズ全体のID」で全回共通、`id`は「その回
固有のID」）をノート側の`NEW_MEETING_START`直後に
`<!-- occurrence_id: "<event id>" attendance: "<value>" date: "<value>" -->`
として保持し、以下のように比較する。`attendance`は
`1_scheduled`/`2_done`/`3_skip`のいずれか、`date`はそのoccurrenceの
開催日。frontmatterの`attendance`は常に、現在有効なoccurrenceブロック
のコメント値をミラーする。

- **今回のevent["id"] == ノートに記録されたoccurrence_id**
  → 同じ回の再同期（リスケジュール等）。ブロックを丸ごと作り直さず、
  日時・場所・所要時間・（frontmatterの）URLの該当行だけを文字列
  置換する。決定事項・アクションアイテムなどのユーザー手書き欄は
  一切触らない。
- **今回のevent["id"] != ノートに記録されたoccurrence_id**
  → 次の回への遷移。現在の`NEW_MEETING_START`〜`END`ブロックの中身
  （手書き内容を含む）を丸ごと`NEW_MEETING_END`マーカー直後（過去ログ
  領域の先頭）に退避してから、`START`〜`END`を新しい回の空の状態
  （新しいoccurrence_id・新しい日時）で差し替える。退避される旧ブロック
  は、そのoccurrenceの最終的な`attendance`値ごとアーカイブされる。
  新しいブロックは`attendance: "1_scheduled"`・新しい`date`で初期化
  される。

いずれの場合も`last_updated`を今日の日付に更新する。

## ファイル検索

既存ノートは`20_Projects/`配下と`30_Areas/Meetings/`配下を
`Path.rglob("*.md")`で走査し、frontmatterの`calendar_series_id`が
イベントの`recurringEventId`と一致するものを探す
（`vault_lib.get_fm_value`を使用）。見つからなければ新規作成する。

## 出席者が1人以下になった場合（実質キャンセル）

シリーズ全体を`cancelled`にはしない（次回以降は開催される可能性が
あるため）。対象occurrenceのブロック内に`(キャンセル)`という注記を
追加し、同ブロックの`attendance`を`3_skip`にする
（frontmatterの`attendance`もミラーされる）。

## 新規作成時

`Meeting_Series_Template.md`をベースに、`calendar_series_id`
（`recurringEventId`）、`project`（`vault_lib.fuzzy_project_match`
による推定）、`last_updated`（今日の日付）、`url`
（`hangoutLink`があれば設定）をfrontmatterに設定し、テンプレートの
`<!-- occurrence_id: "" -->`を実際のイベントIDに置換して保存する。
保存先はprojectが確定していれば`20_Projects/<Name>/Meetings/`、
それ以外は`30_Areas/Meetings/`。
