---
name: task
description: |
  議事録のアクションアイテムやCLI入力からタスクノートを抽出・作成する。
  「タスク化して」「アクションアイテムをタスクにして」「/task」等の
  トリガーで起動する。
---

# task

## 目的
アクションアイテムや口頭指示をタスクノートとして構造化する。

## 入力
議事録のアクションアイテム、またはCLI入力（フリーフォーム）。

## 出力
`Task_Template.md` ベースのノート（`10_Projects/<Name>/Tasks/`）。

## 処理パターン

### (a) 議事録ノート指定時
1. `python scripts/task_extract.py --note <議事録ノートのパス>` を実行する。
2. 標準出力のJSON（`{"items": [...], "project": "[[...]]"|null}`）から
   `items`（アクションアイテムのテキスト一覧）と `project` を得る。
3. 各itemについて、`project` が `null` ならユーザーに確認する。
   `python scripts/list_projects.py` を実行して候補一覧
   （`{"projects": [...]}`）を取得し、その一覧からどのプロジェクトに
   紐づけるか選んでもらう。
4. 確認が済んだら item ごとに
   `python scripts/task_save.py --title <item> --project <project> [--due-date YYYY-MM-DD] [--source "[[議事録ノート名]]"]`
   を呼び、タスクノートを作成する。`--source`は議事録経由で呼ばれた
   場合のみ指定し、省略可。

### (b) フリーフォーム入力時
1. Claude自身がユーザー発言からアクションアイテムを抽出する
   （決定的処理ではないため `task_extract.py` は使わない）。
2. 紐づくプロジェクトが不明な場合は、`python scripts/list_projects.py`
   を実行して候補一覧（`{"projects": [...]}`）を取得し、その一覧を
   提示してユーザーに確認する。**自動推測はしない**
   （meetingスキルのfuzzy_project_matchによる自動推定とは方針が異なる）。
3. 確認が済んだら `python scripts/task_save.py --title <text> --project <project> [--due-date YYYY-MM-DD]`
   を呼び、タスクノートを作成する。

## 補足
- `task_save.py` は `project` が空文字列だとエラー
  （`{"status": "error", "reason": "project_required"}`、exit code 1）を
  返す。これはプロジェクト確認漏れを検出するガードであり、Claude側は
  必ずユーザー確認を済ませてから呼び出すこと。
- `task_save.py` は `project` が `10_Projects/<Name>/` として実在しない
  場合もエラー（`{"status": "error", "reason": "project_not_found"}`、
  exit code 1）を返す。`list_projects.py` の候補一覧から選んだ値を渡せば
  通常発生しないが、発生した場合は候補一覧を出し直してユーザーに再確認
  する。
- `status` は常に `1_todo` で作成される。
- `due_date` は指定が無ければ空欄のまま作成される。
- `--source` に改行や `"` を含めるとエラー
  （`{"status": "error", "reason": "invalid_source"}`、exit code 1）を
  返す。
