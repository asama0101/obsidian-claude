---
name: meeting
description: |
  Google Calendar（将来的にはMicrosoft 365も）の予定から議事録ノートを
  作成・更新する。「議事録を作って」「今日の会議のノート作って」
  「/meeting」等のトリガーで起動する。
---

# meeting

## 目的
カレンダー上の予定と議事録ノートを同期する。

## 実行フロー

1. Claudeが接続済みGoogle Calendar MCP（`list_events`）で本日分の予定を
   取得し（先読み廃止、本日1日分のみ）、その結果（`{"events": [...]}`
   または配列そのもの）を一時JSONファイルへ書き出す。
2. `python .claude/skills/vault/scripts/meeting_sync.py --events-json <path>`
   を実行する（`--vault-root`は省略可。省略時はVaultルート自動検出）。
3. 標準出力のJSONを見て、結果をユーザーへ要約報告する。各フィールドの内容は次の通り。

   | フィールド | 内容 |
   |------------|------|
   | `created` | 新規作成したノートのパス一覧 |
   | `updated` | 日時・URLなどを更新した既存ノートのパス一覧 |
   | `skipped_single_attendee` | 出席者1人以下かつ既存ノートも無く、無視したイベントID一覧 |
   | `cancelled` | 既存ノート対応の予定が出席者1人以下になり、`attendance`を`3_skip`にしたノートのパス一覧 |
   | `no_project` | 新規作成したがprojectを自動推定できなかったノートの`{"note_path", "title"}`一覧 |
   | `deleted` | カレンダー側でキャンセルされ物理削除された単発ノートのパス一覧 |
   | `needs_attendance_check` | 開催確認が必要なノートの`{"note_path", "title"}`一覧 |
   | `needs_task_check` | `attendance`確定済み（`2_done`/`3_skip`）なのに未チェックのアクションアイテムが残っているノートの`{"note_path", "title"}`一覧 |
4. `no_project`が空でなければ、`python .claude/skills/vault/scripts/list_projects.py`
   を実行して候補一覧（`{"projects": [...]}`）を取得し、その一覧
   （＋「プロジェクトなし」の選択肢）を提示して、`no_project`内の各ノート
   （`title`で識別）についてどれに割り当てるかを1回の確認でまとめて
   ユーザーに尋ねる。
5. ユーザーが割り当てを決めたら、ノートごとに
   `python .claude/skills/vault/scripts/meeting_sync.py --set-project <note_path> --project <value>`
   を実行してproject欄へ反映する。`<value>`はシェル上でリテラルの二重引用符を含めて渡す必要がある
   （`task`スキルの`task_save.py`がクォートなし形式を要求するため異なる規約）。
   プロジェクト割り当て時は`'"[[ディレクトリ名]]"'`、「プロジェクトなし」時は`'""'`を渡す。例えば：
   ```
   python .claude/skills/vault/scripts/meeting_sync.py --set-project <note_path> --project '"[[九州旅行]]"'
   python .claude/skills/vault/scripts/meeting_sync.py --set-project <note_path> --project '""'
   ```
   このときノートは新しいproject値に応じて`10_Projects/<Name>/Meetings/`
   または`20_Areas/Meetings/`へ自動的に移動される。`--project`が
   `10_Projects/<Name>/`として実在しない値だった場合は
   `{"status": "error", "reason": "project_not_found"}`が返るので、
   候補一覧を出し直してユーザーに再選択してもらう。
6. `needs_attendance_check`が空でなければ、各ノート（`note_path`で識別）について「実施済み/不参加」をユーザーにまとめて確認する。
   カレンダー情報だけでは予定が存在したことは分かっても実際に開催されたかは判定できないため、この手動確認が必要である。
   確認結果は`python .claude/skills/vault/scripts/meeting_sync.py --set-attendance <note_path> --attendance <1_scheduled|2_done|3_skip>`で反映する。
   `--attendance`には実施済みなら`2_done`、不参加なら`3_skip`を渡す。
   「実施済み」と確認されたノートは、続けて下記「task化フロー」へ進む。
7. `needs_task_check`が空でなければ、対象ノートは直接下記「task化フロー」へ進む。`attendance`（`2_done`/`3_skip`）は既に確定済みのため、「実施済み/不参加」の確認は不要である。

`meeting_sync.py`自体が全ての判定（新規作成/更新/キャンセル反映/
定例の回判定）を行うため、Claude側でノートを直接編集する必要はない。

## task化フロー

`needs_attendance_check`の確認で「実施済み」と判定されたノート、
および`needs_task_check`で検出されたノートのいずれについても、
ノートごとに以下を実行する共通フローである。

1. `python .claude/skills/vault/scripts/task_extract.py --note <note_path>`
   を実行し、標準出力のJSON（`{"items": [...], "project": ...}`）から
   未チェックのアクションアイテム一覧（`items`）を取得する。
2. `items`が空でなければ、各itemについてタスク化するかどうかを
   ユーザーに確認する。
3. タスク化する場合は、`task`スキルのパターン(a)フロー通り
   `python .claude/skills/vault/scripts/task_save.py`を呼ぶ。このとき
   `--source "[[議事録ノート名]]"`を追加で渡す。
4. タスク化の有無にかかわらず、
   `python .claude/skills/vault/scripts/meeting_sync.py --link-task <note_path> --item-text <元のアクションアイテム本文> [--task-note <タスクノート名>]`
   を実行し、議事録側の該当チェックボックスをチェック済みにする
   （タスク化した場合は`--task-note`にタスクノート名を渡すと
   `[[リンク]]`も追記される）。

## 出力

- 単発予定: `Meeting_Template.md` ベースのノート
  （`20_Areas/Meetings/` またはプロジェクト判明時は
  `10_Projects/<Name>/Meetings/`）
- 定例予定: `Meeting_Series_Template.md` の
  `NEW_MEETING_START`/`END`差し替えロジックで追記、または新規作成
  （詳細は`references/meeting-series-update.md`）

## 処理ルール概要

1. 出席者が1人以下（自分のみ）の予定は、対応する既存ノートが無ければ
   無視する（`skipped_single_attendee`）。既存ノートがある場合は
   実質キャンセルとして扱う。
2. 単発予定はノート新規作成（プロジェクト自動推定は
   `references/project-matching.md`のルールに従う）。
3. 定例予定（`recurringEventId`あり）は`calendar_series_id`が一致する
   既存ファイルがあれば、occurrence_idで「同じ回の再同期」か
   「次の回への遷移」かを判定して処理する
   （`references/meeting-series-update.md`）。無ければ新規作成する。
4. カレンダー側で日時・URLが変更されていれば既存ノートに反映する。
   議事・決定事項などユーザー手書き欄は変更しない。
5. 既存ノート対応の予定が後から出席者1人以下に変わった場合（実質キャンセル）の扱いは、単発予定と定例予定で異なる。
   - 単発予定: ノートを削除せず`attendance`を`3_skip`にする（`status`欄は廃止）。
   - 定例予定: シリーズ全体をキャンセルにせず、対象occurrenceのブロック内に`(キャンセル)`と注記した上で、同ブロックの`attendance`も`3_skip`にする。
6. 削除対象の判定は単発予定と定例予定で異なる。
   - 単発予定（`type: meeting`）: 開催日（`date`）が今日であり、かつ今日取得したevents一覧に対応する`calendar_event_id`が無いこと、の2条件を満たすノートが対象である。該当ノートはカレンダー側でキャンセルされたとみなし、中身を確認せず物理削除する（`deleted`）。
   - 定例予定: 削除対象外。

## Microsoft 365 / Outlook / Teams連携について

本環境ではMicrosoft 365 MCPは未接続。接続されている場合の
フィールド対応表は`references/meeting-field-mapping.md`を参照。
未接続の場合はこの節の処理は行わず、Microsoft 365 MCPサーバーの
接続方法をユーザーに案内するに留める。

## today/closeスキルからの呼び出しについて

`today`・`close`スキルからもmeetingスキルの実行フロー（カレンダー同期〜
`needs_attendance_check`/`needs_task_check`の確認・task化フローまで）が
自動的に呼び出される。呼ばれた場合も、通常`/meeting`実行時と同じ
対話フロー（project割り当て確認・実施確認・task化確認）をそのまま
ユーザーに提示してよい。

Google Calendar MCP未接続やAPI呼び出し失敗時は、本スキルの処理を
そこで中断し、呼び出し元（`today`/`close`）本来の処理はブロックしない。

`needs_task_check`は日付を問わず全件スキャン対象のため、対応せず
残したノートは`today`・`close`を実行するたびに繰り返し提示される
（仕様通りの動作である）。

## 参照ドキュメント

- `references/meeting-series-update.md`: 定例予定のoccurrence_id判定
  ロジック詳細
- `references/meeting-field-mapping.md`: Microsoft 365接続時の
  フィールド対応表
- `references/project-matching.md`: project自動紐付けルール（meeting専用）
- `references/conventions.md`: vaultプラグイン全体の共通実装規約
