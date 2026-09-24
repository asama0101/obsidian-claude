---
name: task-add
description: |
  ユーザーの発話・CLI入力から単発のタスクを抽出し、プロジェクトへの紐づけを
  確認した上でタスクノートを作成する。「タスクにして」「これタスク化して」
  「/task-add」等のトリガーで起動する。
---

# task-add

## 目的
ユーザーの発話・CLI入力から単発のタスクを抽出し、プロジェクトへの紐づけを
確認した上でタスクノートを作成する。

`task`スキルのフリーフォーム入力パターンを分割して新設したスキルである。

## 入力
CLI入力（フリーフォーム）。

## 出力
`Task_Template.md` ベースのノート
（`20_Projects/<Name>/Tasks/`、プロジェクトなしの場合は`30_Areas/Tasks/`）。

## 処理

1. Claude自身がユーザー発言からタイトル・期限を抽出する（決定的処理では
   ないため`task_extract.py`は使わない）。
2. プロジェクト解決フロー: `PYTHONUTF8=1 python .claude/skills/vault/scripts/list_projects.py`
   を実行し、標準出力のJSON（`{"projects": [...]}`）から`20_Projects/`直下の
   候補一覧を取得する。次の3択をユーザーに確認する（**自動推測はしない**）。
   - 既存プロジェクトから選ぶ
   - 新規プロジェクトを作成する（`project-add`スキルを呼び出す）
   - プロジェクトなしで進める
3. `PYTHONUTF8=1 python .claude/skills/vault/scripts/task_save.py --title <text> [--project <project>] [--due-date YYYY-MM-DD]`
   を実行する。`--project`は省略可能で、省略時（プロジェクトなしを選んだ場合）
   は`30_Areas/Tasks/`へ保存される。既存プロジェクトを選んだ場合・新規作成した
   場合は`20_Projects/<Name>/Tasks/`へ保存される。議事録経由ではないため
   `--source`は付与しない。`--project`に渡す値はプレーン名・`[[Name]]`形式の
   どちらでもよく、`task_save.py`が`vault_lib.normalize_project_link`で正規化
   してから`project`フロントマターへ`[[Name]]`形式で書き込む（既に`[[Name]]`
   形式なら二重ラップしない）。
4. `{"status": "error", "reason": "project_not_found"}`（`--project`が
   `20_Projects/<Name>/`として実在しない値だった場合、exit code 1）が返ったら、
   候補一覧を出し直して再度ユーザーに選択を依頼する。
5. 標準出力のJSON（`{"note_path": "..."}`）から`note_path`を取得し、
   作成結果をユーザーに報告する。

## 補足
- `task_save.py`は作成時に`created_date`のみを自動セットし、`start_date`は
  空欄のまま作成する。`start_date`はユーザーが後からデイリーノートに埋め込
  まれたBaseビューから指定する想定であり、`task-add`スキル自身が自動セット
  することはない。
- `status`はテンプレートの既定値`1_todo`のまま作成される。
- `due_date`は指定が無ければ空欄のまま作成される。
