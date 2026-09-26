---
name: task-gantt
description: |
  Vault横断で全タスクノートを集計し、プロジェクト別のMermaid ganttチャートを
  当日デイリーノートに書き込む。「ガントチャート作って」「タスクの進捗を
  可視化して」「/task-gantt」等のトリガーで起動する。
---

# task-gantt

## 目的
`20_Projects/*/Tasks/*.md`と`30_Areas/Tasks/*.md`のtaskノート全件を横断集計し、
Mermaid ganttチャートとして当日デイリーノートに書き込む。プロジェクト個別モードは
無く、常に全体横断で実行する。

## 入力
CLI引数なし。実行日を基準日として使う（`--today`はテスト・動作確認用の上書き）。

## 出力
当日デイリーノート（`10_Daily/YYYY-MM-DD.md`）の`<!-- GANTT_START -->`〜
`<!-- GANTT_END -->`区間へのMermaid ganttコードブロック（実行のたびに上書き）。
`start_date`または`due_date`が未設定・形式不正のタスクは、同じ区間内に
「日程未確定タスク」として別途箇条書きで列挙する。
書き込む内容はObsidianの折りたたみ可能なコールアウト内に収まるよう、
全行に`> `プレフィックス（空行は`>`のみ）を付与した状態で書き込む。

## 処理

1. `.claude/skills/vault/scripts/task_gantt.py`を引数なしで実行する。
   ```
   PYTHONUTF8=1 python .claude/skills/vault/scripts/task_gantt.py
   ```
2. スクリプトは標準出力にJSON（1行）を出す。`status`フィールドで結果を判定する。
   - `status: "ok"`: `sections`/`bar_tasks`/`unscheduled_tasks`の件数を要約して報告する。
   - `status: "error"`, `reason: "daily_note_not_found"`: 当日デイリーノートが
     存在しない。`today-open`スキルを先に実行するよう案内する。
   - `status: "error"`, `reason: "gantt_marker_not_found"`: 当日デイリーノートに
     `<!-- GANTT_START -->`/`<!-- GANTT_END -->`マーカーが無い。
     `80_Templates/Daily_Template.md`のマーカーを当該ノートへ手動で追記するよう
     案内する（自動追加は行わない）。

## 補足
- 対象タスク: `type: task`のノート全件（project紐付けの有無を問わない）。
  `status: "5_cancel"`は常に除外する。
- 期間フィルタ: 実行日を`today`として`(today <= due_date <= today+90日)`
  または`(due_date < today かつ status not in ("4_done", "5_cancel"))`を
  満たすタスクのみがバー表示対象。`status: "4_done"`のタスクは`done`タグで
  色分けして含めるが、上記フィルタ上は「未完了」扱いされないため、
  `due_date`が過去のdoneタスクは結果的に自然消滅する（ローリングto-doガント）。
- `start_date`・`due_date`のいずれかが未設定・形式不正のタスクは、この期間
  フィルタを適用せず、常に「日程未確定タスク」として列挙する。
- `project`フロントマター値は`vault_lib.extract_project_name`で正規化してから
  section名に使う（`[[Name]]`形式で手入力されていてもプレーン表記と統合される）。
  実在するプロジェクトフォルダを指しているかの検証は行わない。
- タスク間の依存関係表現はv1では扱わない（対応するfrontmatterフィールドが
  存在しないため）。
- ステータス色分け: バーには`status`・overdue（`due_date < today`かつ`status`が`4_done`/`5_cancel`以外）の組に応じてMermaid ganttのタグを付与する。`status: "4_done"`は常に`done`。それ以外でoverdueなら`crit`。非overdueは`status: "2_doing"`が`crit, active`、`status: "3_pending"`が`active`、`status: "1_todo"`・未知の値はタグ無し。さらに、次の2条件のいずれかを満たす場合も、`due_date`基準のoverdueとは別に`crit`になる（`_classify_task`の分類ロジック自体は変わらず色のみの変更。`status`が`4_done`/`5_cancel`のいずれでもない場合に限る）。
  - `status: "1_todo"`かつ`start_date`が今日以前（開始日超過、`_is_late_start`）
  - `due_date`が今日ちょうど（期限当日、`_is_due_today`）。`_is_overdue`自体は「期限日が今日より前」のままの意味を保ち、期限当日はここで別途OR結合される。
- todoのmilestone表示: taskノート本文の`## 📌 進捗メモ`見出し配下のチェックボックス行（`- [ ] `/`- [x] `）をtodoとして抽出し、対応するバーの直下に`milestone`タグの行として描画する（日付は親タスクの`start_date`、期間`0d`）。完了チェックボックス（`- [x] `/`- [X] `）は`done`タグを追加で付与する。本文が無い空のプレースホルダー行はtodoとして抽出しない。親タスクの`status`が`"4_done"`の場合は、todoのmilestone行を一切出力しない（バー行自体は`done`タグ付きで従来通り表示する）。todoの文言に`【YYYY-MM-DD】`形式の期日表記を含めた場合、ラベルの一部としてそのままmilestone行のラベルに反映される（コード側でのパース・検証は行わない）。
- ★で囲まれた最終タスクのmilestone表示: タイトル（ファイル名）が`★`で始まり`★`で終わる（`★`1文字のみは対象外）タスクは、プロジェクトの「最終タスク（イベント）」として扱われ、通常のバー行の代わりに`milestone`タグのみの行で表示する。日付は`due_date`基準（期間`0d`）。色はstatusのみで決まり、`status: "4_done"`なら`done, milestone`、それ以外は`crit, milestone`（overdueかどうかは問わない）。バー表示対象になるかどうかの分類ロジック（期間フィルタ等）自体は変更しない。★タスク自身のtodoのmilestone行は上記の通常ロジックのままそのまま出力される。
- `80_Templates/Daily_Template.md`側でGANTT_START/GANTT_ENDマーカーは`> [!INFO]+ 📊 タスクガントチャート`という独立したコールアウト内に配置されており、「要スケジュール確認タスク（14日以内）」コールアウトとは別のコールアウトである。

## today-openスキルからの呼び出しについて

`today-open`スキルからも本スキルの実行フローが自動的に呼び出される
（`daily_note`が`"skipped"`の場合も含め、`today_start.py`が`status: "ok"`を
返すたびに毎回実行される）。呼ばれた場合も通常実行時と同じ処理・報告内容
でよい。`daily_note_not_found`/`gantt_marker_not_found`が返っても
`today-open`本来の処理（ブランチ作成・デイリーノート作成）は巻き戻さない。
