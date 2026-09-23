---
name: project-add
description: |
  新規プロジェクトを開始する。プロジェクト概要ノートと
  Tasks/・Meetings/・Documents/フォルダを一括作成する。
  「プロジェクトを始めて」「新規プロジェクト作って」「/project <name>」
  等のトリガーで起動する。
---

# project-add

## 目的
新規プロジェクトの箱（概要ノート＋フォルダ構成）を一括で用意する。

## 入力
プロジェクト名（必須）、期限（任意）。

## 出力
- `Project_Template.md` ベースの概要ノート（`20_Projects/<Name>/<Name>.md`）
- `20_Projects/<Name>/Tasks/`・`Meetings/`・`Documents/` の3フォルダ

## 処理
1. `PYTHONUTF8=1 python .claude/skills/vault/scripts/project_create.py --title <name> [--due-date YYYY-MM-DD]`
   を実行する。
2. 標準出力のJSONを`status`フィールドで判定する。
   - `"ok"`: `note_path`をユーザーに報告する。
   - `"error"`（`reason: "project_already_exists"`）: 同名の
     `20_Projects/<name>/`が既に存在する。既存ノートを使うか別名にするか
     ユーザーに確認する（自動的に別名採番はしない）。

## 補足
- ファイルをDocuments/へ保存する自動化は行わない。作成するのはフォルダ
  のみで、資料の配置はObsidian上でユーザーが手動で行う。
- LLM判断を伴わない完全に機械的な処理のため、`project_create.py`が
  全処理を担う。
