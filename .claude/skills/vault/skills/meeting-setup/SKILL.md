---
name: meeting-setup
description: |
  Google Calendar（将来的にはMicrosoft 365も）の予定から議事録ノートを
  作成・更新し、新規作成したノートのproject割当まで確認する。
  「議事録を作って」「今日の会議のノート作って」「/meeting-setup」等の
  トリガーで起動する。
---

# meeting-setup

## 目的
カレンダー上の予定と議事録ノートを同期し、新規作成したノートのproject割当
まで確認する。開催確認（`attendance`更新）は`today-close`スキル、議事録
からのタスク化は`meeting-followup`スキルがそれぞれ担うため、本スキルの
範囲には含まない。

## 実行フロー

1. Claudeが接続済みGoogle Calendar MCP（`list_events`）で本日分の予定を
   取得し（先読み廃止、本日1日分のみ）、その結果（`{"events": [...]}`
   または配列そのもの）を一時JSONファイルへ書き出す。
2. `PYTHONUTF8=1 python .claude/skills/vault/scripts/meeting_sync.py --events-json <path>`
   を実行する（`--vault-root`は省略可。省略時はVaultルート自動検出）。
3. 標準出力のJSONを見て、結果をユーザーへ要約報告する。各フィールドの内容は次の通り。

   | フィールド | 内容 |
   |------------|------|
   | `created` | 新規作成したノートのパス一覧 |
   | `updated` | 日時・URL・開催場所・参加者などを更新した既存ノートのパス一覧 |
   | `skipped_single_attendee` | 出席者1人以下かつ既存ノートも無く、無視したイベントID一覧 |
   | `cancelled` | 既存ノート対応の予定が出席者1人以下になり、`attendance`を`3_skip`にしたノートのパス一覧 |
   | `no_project` | 新規作成したがprojectを自動推定できなかったノートの`{"note_path", "title"}`一覧 |
   | `deleted` | カレンダー側でキャンセルされ物理削除された単発ノートのパス一覧 |
   | `needs_attendance_check` | 開催確認が必要なノートの`{"note_path", "title"}`一覧。`today-close`スキルが消費する（本スキル自身はここで確認を求めない） |
   | `needs_task_check` | `attendance`確定済み（`2_done`/`3_skip`）なのに未チェックのアクションアイテムが残っているノートの`{"note_path", "title"}`一覧。`today-close`スキルが消費する（本スキル自身はここで確認を求めない） |

4. `created`一覧の各ノートについて、project割当を改めて確認する。自動推定に
   失敗した`no_project`のノートだけでなく、`fuzzy_project_match`で自動的に
   割り当てられたノートも含めて、**新規作成された全ノートを対象**にする。
   各ノートについてReadツールでfrontmatterの`project`値を確認した上で、
   - 既存プロジェクトから選ぶ
   - 新規プロジェクトを作成する（`project-add`スキルを呼び出す）
   - プロジェクトなしで進める

   の3択を、`created`一覧全体でまとめてユーザーに確認する（自動推定できて
   いた場合はその値をデフォルト候補として提示してよい）。
5. 確定した値をノートごとに
   `PYTHONUTF8=1 python .claude/skills/vault/scripts/meeting_sync.py --set-project <note_path> --project <value>`
   で反映する。`<value>`はクォート無し`[[プロジェクト名]]`形式、プロジェクト
   なしの場合は空文字列`""`を渡す（`task_save.py`の`--project`と同じ記法）。
   例えば：
   ```
   PYTHONUTF8=1 python .claude/skills/vault/scripts/meeting_sync.py --set-project <note_path> --project [[九州旅行]]
   PYTHONUTF8=1 python .claude/skills/vault/scripts/meeting_sync.py --set-project <note_path> --project ""
   ```
   このときノートは新しいproject値に応じて`10_Projects/<Name>/Meetings/`
   または`20_Areas/Meetings/`へ自動的に移動される。`--project`が
   `10_Projects/<Name>/`として実在しない値だった場合は
   `{"status": "error", "reason": "project_not_found"}`が返るので、
   候補一覧を出し直してユーザーに再選択してもらう。`updated`（既存ノート
   更新）はproject欄に一切触れないため、この確認フローの対象外である。

`meeting_sync.py`自体が全ての判定（新規作成/更新/キャンセル反映/
定例の回判定）を行うため、Claude側でノートを直接編集する必要はない。

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
4. カレンダー側で日時・URL・開催場所・参加者のいずれかが変更されていれば
   既存ノートに反映する。議事・決定事項などユーザー手書き欄は変更しない。
5. 既存ノート対応の予定が後から出席者1人以下に変わった場合（実質キャンセル）の扱い、および削除対象になるかどうかは、単発予定と定例予定で異なる。

   | 予定種別 | キャンセル時の挙動 | 削除対象か |
   |----------|--------------------|------------|
   | 単発予定 | ノートを削除せず`attendance`を`3_skip`にする（`status`欄は廃止） | 開催日（`date`）が今日であり、かつ今日取得したevents一覧に対応する`calendar_event_id`が無いノートが対象。該当すればカレンダー側でキャンセルされたとみなし、中身を確認せず物理削除する（`deleted`） |
   | 定例予定 | シリーズ全体をキャンセルにせず、対象occurrenceのブロック内に`(キャンセル)`と注記した上で、同ブロックの`attendance`も`3_skip`にする | 削除対象外 |

## Microsoft 365 / Outlook / Teams連携について

本環境ではMicrosoft 365 MCPは未接続。接続されている場合の
フィールド対応表は`references/meeting-field-mapping.md`を参照。
未接続の場合はこの節の処理は行わず、Microsoft 365 MCPサーバーの
接続方法をユーザーに案内するに留める。

## today-open/today-closeスキルからの呼び出しについて

`today-open`・`today-close`スキルからもmeeting-setupスキルの実行フロー
（カレンダー同期〜project割当確認まで）が自動的に呼び出される。呼ばれた
場合も、通常`/meeting-setup`実行時と同じ対話フロー（project割当確認）を
そのままユーザーに提示してよい。

Google Calendar MCP未接続やAPI呼び出し失敗時は、本スキルの処理を
そこで中断し、呼び出し元（`today-open`/`today-close`）本来の処理はブロックしない。

`needs_attendance_check`/`needs_task_check`は日付を問わず`meeting_sync.py`
実行のたびに全件スキャンして返される検出結果であり、本スキル自身はこれを
消費しない。`today-close`スキルが該当ノート一覧の提示・確認・案内を担う
（詳細は`today-close/SKILL.md`を参照）。対応せず残したノートは
`today-open`・`today-close`を実行するたびに繰り返し検出される。

## 参照ドキュメント

- `references/meeting-series-update.md`: 定例予定のoccurrence_id判定
  ロジック詳細
- `references/meeting-field-mapping.md`: Microsoft 365接続時の
  フィールド対応表
- `references/project-matching.md`: project自動紐付けルール（meeting-setup専用）
- `references/conventions.md`: vaultプラグイン全体の共通実装規約
- [`../../../../../80_SkillFlows/meeting-setup-flow.md`](../../../../../80_SkillFlows/meeting-setup-flow.md): 本フローの設計ドキュメント（Mermaid図付き）
