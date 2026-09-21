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

1. Claudeが接続済みGoogle Calendar MCP（`list_events`）で本日〜+7日の
   予定を取得し、その結果（`{"events": [...]}`または配列そのもの）を
   一時JSONファイルへ書き出す。
2. `python .claude/skills/vault/scripts/meeting_sync.py --events-json <path>`
   を実行する（`--vault-root`は省略可。省略時はVaultルート自動検出）。
3. 標準出力のJSON（`created` / `updated` / `skipped_single_attendee` /
   `cancelled` / `no_project`の各リスト）を見て、結果をユーザーへ要約報告する。
4. `no_project`が空でなければ、`10_Projects/`直下のディレクトリ名一覧
   （＋「プロジェクトなし」の選択肢）を提示し、`no_project`内の各ノート
   （`title`で識別）についてどれに割り当てるかを1回の確認でまとめて
   ユーザーに尋ねる。
5. ユーザーが割り当てを決めたら、ノートごとに
   `python .claude/skills/vault/scripts/meeting_sync.py --set-project <note_path> --project <value>`
   を実行してproject欄へ反映する（`<value>`はプロジェクト選択時は
   `"[[ディレクトリ名]]"`、「プロジェクトなし」選択時は`""`）。

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
4. カレンダー側で日時・URLが変更されていれば既存ノートに反映する。
   議事・決定事項などユーザー手書き欄は変更しない。
5. 既存ノート対応の予定が後から出席者1人以下に変わった場合
   （実質キャンセル）は、単発予定ならノートを削除せず
   `status: cancelled`をfrontmatterに追記する。定例予定なら
   シリーズ全体はキャンセルにせず、対象occurrenceのブロック内に
   `(キャンセル)`と注記する。

## Microsoft 365 / Outlook / Teams連携について

本環境ではMicrosoft 365 MCPは未接続。接続されている場合の
フィールド対応表は`references/meeting-field-mapping.md`を参照。
未接続の場合はこの節の処理は行わず、Microsoft 365 MCPサーバーの
接続方法をユーザーに案内するに留める。

## 参照ドキュメント

- `references/meeting-series-update.md`: 定例予定のoccurrence_id判定
  ロジック詳細
- `references/meeting-field-mapping.md`: Microsoft 365接続時の
  フィールド対応表
- `references/project-matching.md`: project自動紐付けルール（共通）
- `references/conventions.md`: vaultプラグイン全体の共通実装規約
