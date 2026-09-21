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

## 入力
接続済みGoogle Calendar MCP経由で取得する本日以降の予定。

## 出力
- 単発予定: `Meeting_Template.md` ベースのノート
  （`20_Areas/Meetings/` またはプロジェクト判明時は
  `10_Projects/<Name>/Meetings/`）
- 定例予定: `Meeting_Series_Template.md` の
  NEW_MEETING_START/END差し替えロジックで追記、または新規作成

## 処理ステップ概要
1. 出席者が1人だけの予定は無視する
2. 単発予定はノート新規作成（プロジェクト特定できればプロジェクト配下）
3. 定例予定（`calendar_series_id`あり）は既存ファイルがあれば
   NEW_MEETING_START/ENDブロックを差し替えて追記、無ければ新規作成
4. カレンダー側で予定が変更されていれば既存ノートに反映
5. 既存ノート対応の予定が後から出席者1人のみに変わった場合
   （実質キャンセル）はノートを削除せず `status: cancelled` を
   frontmatterに追記

## 備考（次フェーズでの詳細実装対象）
- 詳細アルゴリズムは未実装。本ファイルは雛形。
- Microsoft 365 MCPは本環境では未接続。接続されていれば使い、
  無ければ接続方法を案内するフォールバックを実装する。
