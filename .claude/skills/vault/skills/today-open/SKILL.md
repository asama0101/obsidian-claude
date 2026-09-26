---
name: today-open
description: |
  1日の作業開始時に実行する。当日日付のgitブランチを作成し、
  デイリーノートを新規作成する。「今日を始める」「デイリーノート作って」
  「/today」等のトリガーで起動する。
---

# today-open

## 目的
1日の作業を開始するための準備を自動化する。

## 処理
1. `.claude/skills/vault/scripts/today_start.py` を引数なしで実行する。
   ```
   PYTHONUTF8=1 python .claude/skills/vault/scripts/today_start.py
   ```
2. スクリプトは標準出力にJSON(1行)を出す。`status`フィールドで結果を判定する。
   - `status: "blocked"`
     - `branches`に未マージの過去日ブランチ名の一覧が入る。
     - このスクリプト自身はマージ・削除を行わない。
     - `stray_changes_committed`は常に`null`（後述の新規ブランチ作成処理まで
       到達していないため）。
     - ユーザーに「未マージの過去日ブランチ（例: `branches`の内容）が残っています。
       マージまたは破棄してから再実行してください」と確認し、対応方針が決まるまで
       `today-open`の処理を先に進めない。
   - `status: "ok"`
     - `branch`: `"existing"`（当日ブランチが既にありcheckoutのみ実施）
       または`"created"`（`main`から新規作成しcheckout）。
     - `daily_note`: `"skipped"`（当日のデイリーノートが既に存在し何もしなかった）
       または`"created"`（`Daily_Template.md`から新規作成した）。
     - `daily_note`が`"created"`のとき、`carryover_source`に転記元にした前日ノートの
       日付（`YYYY-MM-DD`）が入る。前日ノートが見つからなければ`null`。
     - `stray_changes_committed`: `branch`が`"created"`のとき、`main`上に残っていた
       追跡済みファイルの未コミット変更を新ブランチ上でコミットした場合、その
       コミットSHA（文字列）が入る。変更が無かった場合、または`branch`が
       `"existing"`（既存の当日ブランチへの単純checkout）の場合は常に`null`。
3. `status: "ok"`の場合、結果報告の前に続けてmeeting-setupスキルの実行フローを
   呼び出す（詳細は備考のリンク参照）。1日の開始時にカレンダー予定を
   反映した議事録ノートを揃えておくためである。Google Calendar MCP未接続
   やAPI呼び出し失敗等でmeeting-setupスキル側が失敗した場合がある。その場合でも、
   today-openの処理（ブランチ作成・デイリーノート作成）は既に完了しているため
   巻き戻さない。失敗した旨は結果報告に含める。
4. 続けてtask-ganttスキルの実行フローを呼び出す（`task_gantt.py`を引数なしで
   実行する）。1日の開始時点でタスクのガントチャートを最新化しておくためである。
   `daily_note`が`"skipped"`（既存ノートを再利用）の場合も含め、`status: "ok"`
   なら常に実行する（`task_gantt.py`はマーカー区間を毎回上書きする冪等な処理
   のため、再実行しても問題ない）。`status: "error"`
   （`daily_note_not_found`/`gantt_marker_not_found`）が返っても、
   today-openの処理（ブランチ作成・デイリーノート作成・meeting-setupスキルの
   実行結果）は巻き戻さない。失敗した旨は結果報告に含める。
5. 正常終了（`status: "ok"`）ならユーザーに結果（ブランチ状態・デイリーノート作成有無・
   Carryover転記元、meeting-setupスキルの実行結果、およびtask-ganttスキルの
   実行結果）を簡潔に報告する。

## 備考
- 当日ブランチの作成前に、`origin`リモートが設定されていれば`main`を
  `git pull --ff-only`で最新化する（失敗しても処理は続行する）。
- `main`から新規に当日ブランチを作成する場合（`branch: "created"`）、
  `checkout -b`の直後に、`main`上に残っていた追跡済みファイルの未コミット
  変更（`git status --porcelain --untracked-files=no`で検出。未追跡の新規
  ファイルは対象外）があれば、新ブランチ上で`git add -u`→コミットする
  （本来`branch-guard.sh`によりmain上での書き込みは発生しないはずだが、
  OneDrive同期によるファイルシステムレベルの復元等、gitの外側で生じうる
  想定外の変更に対する一般的な安全策）。既存の当日ブランチへの単純checkout
  （`branch: "existing"`）ではこの処理は行われない。このパスは`main`を
  一切checkoutしないため、構造上この機能が発動しない設計上の割り切りである。
- Carryover転記は前日ノートの`<!-- CARRYOVER_START -->`〜`<!-- CARRYOVER_END -->`
  ブロックの中身のみを読み取り、元ノートは一切変更しない。
- 前日ノートは`10_Daily/`内を日付降順に走査し、当日より前で最初に見つかったもの
  （連続していなくてもよい）を使う。見つからなければCarryoverは空のまま作成する。
- meeting-setupスキルの自動実行の詳細は`meeting-setup/SKILL.md`の
  「today-open/today-closeスキルからの呼び出しについて」を参照。
- task-ganttスキルの詳細（対象タスクの絞り込み条件・出力形式）は
  `task-gantt/SKILL.md`を参照。
