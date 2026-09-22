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
   python .claude/skills/vault/scripts/today_start.py
   ```
2. スクリプトは標準出力にJSON(1行)を出す。`status`フィールドで結果を判定する。
   - `status: "blocked"`
     - `branches`に未マージの過去日ブランチ名の一覧が入る。
     - このスクリプト自身はマージ・削除を行わない。
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
3. `status: "ok"`の場合、結果報告の前に続けてmeeting-setupスキルの実行フローを
   呼び出す（詳細は備考のリンク参照）。1日の開始時にカレンダー予定を
   反映した議事録ノートを揃えておくためである。Google Calendar MCP未接続
   やAPI呼び出し失敗等でmeeting-setupスキル側が失敗した場合がある。その場合でも、
   today-openの処理（ブランチ作成・デイリーノート作成）は既に完了しているため
   巻き戻さない。失敗した旨は結果報告に含める。
4. 正常終了（`status: "ok"`）ならユーザーに結果（ブランチ状態・デイリーノート作成有無・
   Carryover転記元、およびmeeting-setupスキルの実行結果）を簡潔に報告する。

## 備考
- 当日ブランチの作成前に、`origin`リモートが設定されていれば`main`を
  `git pull --ff-only`で最新化する（失敗しても処理は続行する）。
- Carryover転記は前日ノートの`<!-- CARRYOVER_START -->`〜`<!-- CARRYOVER_END -->`
  ブロックの中身のみを読み取り、元ノートは一切変更しない。
- 前日ノートは`00_Daily/`内を日付降順に走査し、当日より前で最初に見つかったもの
  （連続していなくてもよい）を使う。見つからなければCarryoverは空のまま作成する。
- meeting-setupスキルの自動実行の詳細は`meeting-setup/SKILL.md`の
  「today-open/today-closeスキルからの呼び出しについて」を参照。
