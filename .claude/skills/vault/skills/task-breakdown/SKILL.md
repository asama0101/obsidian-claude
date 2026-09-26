---
name: task-breakdown
description: |
  既存のタスクノート1件をtodo項目へ分解し、進捗メモへ追記した上で
  当日デイリーノートのガントチャートへ反映する。「タスクを分解して」
  「todoに分解して」「/task-breakdown <タスクノート>」等のトリガーで起動する。
---

# task-breakdown

## 目的
既存のタスクノート1件の内容をClaudeが読み、todo項目への分解案をユーザーに
確認した上で進捗メモへ反映し、続けてガントチャートへも反映する。

## 入力
対象タスクノートのパス（ユーザー指定、または対話で確認）。

## 出力
対象タスクノートの`## 📌 進捗メモ`セクション更新＋（成功時）当日デイリーノートの
ガントチャート更新。

## 処理

1. 対象タスクノートを特定する（ユーザーが指定していなければ、パスを確認する）。
2. Claudeが対象タスクノートの内容を読み、todo分解案を提示する。**次の内容を
   ユーザーに確認する（自動確定しない）**: 分解したtodo項目一覧、必要なら
   各todoの期日（自由記述可。【YYYY-MM-DD】形式でtodo文言に含める例: 「資料を作成する【2026-10-01】」）。
3. 確定したら以下を実行する。
   ```
   PYTHONUTF8=1 python .claude/skills/vault/scripts/task_todo_apply.py --note <path> --todo "<text>" --todo "<text>" ...
   ```
4. 標準出力のJSONを確認する。`status`が`error`なら`reason`
   （`no_todos`/`note_not_found`/`not_a_task_note`/`path_outside_vault`）を
   そのまま提示し処理を中断する。
5. 成功（`status: "ok"`）なら続けて以下を実行し、当日デイリーノートの
   ガントチャートへ反映する。
   ```
   PYTHONUTF8=1 python .claude/skills/vault/scripts/task_gantt.py
   ```
   `task_gantt.py`側が`error`（`daily_note_not_found`等）を返しても握りつぶさず、
   結果報告に含める。
6. 結果（追加件数・置換/追記モード・ガント反映結果）を要約報告する。
