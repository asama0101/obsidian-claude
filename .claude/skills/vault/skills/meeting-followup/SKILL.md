---
name: meeting-followup
description: |
  議事録ノートのアクションアイテムをタスク化し、議事録側の該当行をリンクへ
  置き換え、最後に開催状況を確認して締めくくる。「議事録からタスク化して」
  「アクションアイテムを整理して」「/meeting-followup <議事録ノート>」等の
  トリガーで起動する。
---

# meeting-followup

## 目的
`meeting-followup`は単なる「アクションアイテムのタスク化」スキルではない。
**会議後の議事録整理**を行うスキルであり、アクションアイテムの抽出・
タスク化を中心に、全アイテムの処理が終わった最後に議事録ノートの
`attendance`プロパティも更新する。

`task`スキルから切り出した新設スキルである。

## 入力
議事録ノートのパス。

## 出力
- タスクノート（`Task_Template.md`ベース。保存先はプロジェクト解決フロー
  の結果次第で`20_Projects/<Name>/Tasks/`または`30_Areas/Tasks/`）
- 議事録ノート側の該当チェックボックス行の書き換え（`[[タスクノート名]]`
  への完全置換）

## 処理

1. `PYTHONUTF8=1 python .claude/skills/vault/scripts/task_extract.py --note <議事録ノートのパス>`
   を実行し、標準出力のJSON（`{"items": [...], "project": "[[...]]"|null}`）
   から未チェックのアクションアイテム候補（`items`）を取得する。
2. 抽出結果をユーザーに提示し、タスク化する項目を確認する。
3. タスク化する各アクションアイテムについて、プロジェクト解決フロー
   （`task-add`スキルと共通の設計）を実行する。
   `PYTHONUTF8=1 python .claude/skills/vault/scripts/list_projects.py`を実行し、標準出力の
   JSON（`{"projects": [...]}`）から`20_Projects/`直下の候補一覧を取得した
   上で、次の3択をユーザーに確認する（**自動推測はしない**）。
   - 既存プロジェクトから選ぶ
   - 新規プロジェクトを作成する（`project-add`スキルを呼び出す）
   - プロジェクトなしで進める（保存先は`30_Areas/Tasks/`になる）
4. `PYTHONUTF8=1 python .claude/skills/vault/scripts/task_save.py --title <item> [--project <project>] --source "[[議事録ノート名]]"`
   を実行してタスクノートを作成する（`start_date`は空欄のまま、`status`は
   テンプレートの既定値`1_todo`のまま作成される）。`--project`は省略可能で、
   プロジェクトなしを選んだ場合は省略する。`--project`に渡す値はプレーン名・
   `[[Name]]`形式のどちらでもよく、`task_save.py`が`vault_lib.normalize_project_link`
   で正規化してから`project`フロントマターへ`[[Name]]`形式で書き込む
   （既に`[[Name]]`形式なら二重ラップしない）。
5. タスクノート作成後、
   `PYTHONUTF8=1 python .claude/skills/vault/scripts/meeting_sync.py --link-task <議事録ノートのパス> --item-text <元のアクションアイテム本文> --item-index <出現順インデックス> --task-note <タスクノート名>`
   を実行する。これにより議事録ノート側の該当チェックボックス行が、
   **チェックせずに元の文言を消して**`- [ ] [[タスクノート名]]`へ完全な
   wikilinkに置き換わる。`--item-index`は、`--item-text`と完全一致する行が
   複数存在する場合に何番目の一致か（0始まり、出現順）を指定する引数で、
   省略時は`0`（最初の一致）になる。`--task-note`は必須引数であり、省略
   すると`--link-task には --task-note の指定が必要です`エラーになる。
   一致が見つからない場合は`{"status": "error", "reason": "item_not_found"}`
   （exit code 1）が返る。
6. すべてのアクションアイテムの処理が終わったら、議事録ノートの
   `attendance`が`1_scheduled`のままであればユーザーに開催状況を確認し、
   `PYTHONUTF8=1 python .claude/skills/vault/scripts/meeting_sync.py --set-attendance <note_path> --attendance <2_done|3_skip>`
   で更新する。既に`2_done`/`3_skip`であれば何もしない。
7. 結果をユーザーに要約報告する。

## 補足
- アクションアイテムが複数ある場合は、各アイテムごとに手順3〜5を繰り返す。
- `--link-task`実行後のチェックボックスは未チェック（`- [ ] `）のまま
  である。従来の「チェック済みにする」動作から変更されている点に注意する。
- プロジェクト解決フローは`task-add`・`meeting-setup`スキルのproject割当
  確認とも共通の設計である。
