# Microsoft 365 / Outlook / Teams 接続時のフィールド対応表

現時点（本ドキュメント作成時点）ではMicrosoft 365 MCPは未接続であり、
`meeting_sync.py`はGoogle Calendar MCP（`list_events`）が返す
イベント形式のみを扱う。将来Microsoft 365（Outlook Calendar /
Teams会議）のMCPが接続された場合に備え、Google Calendar側の
フィールドとMicrosoft Graph API相当のフィールドの対応関係を
以下にまとめる。

## フィールド対応表

| Google Calendar (list_events) | Microsoft Graph相当 | 備考 |
|---|---|---|
| `summary` | `subject` | イベントタイトル |
| `attendees` | `attendees` | Microsoft Graph側は`type: "resource"`（会議室等のリソース）を含みうる。出席者人数カウントからは**除外**する（人間の出席者のみで1人以下判定を行う） |
| `recurringEventId` | `seriesMasterId` | 定例予定のシリーズ共通ID |
| `id` | `id` | イベント（1回分）固有ID。定例予定ではoccurrence判定に使う |
| `hangoutLink` / `conferenceData` | `onlineMeeting.joinUrl` | オンライン会議URL |
| `location` | `location` / `locations` | Microsoft Graph側は`locations`が配列になりうる点に注意 |
| `description` | `body` / `bodyPreview` | 本文はHTML形式で返る場合があるため、project推定に使う際はプレーンテキスト化が必要になりうる |
| `start.dateTime` / `end.dateTime` | `start.dateTime` / `end.dateTime` | タイムゾーン表現の差異に注意（Graphは`start.timeZone`を別フィールドで持つ） |

## 運用方針

Microsoft 365 MCPが未接続の環境では、上記マッピングに基づく処理は
一切行わない。`meeting`スキル実行時にMCP接続状況を確認し、未接続で
あればこの節の処理をスキップし、ユーザーに接続方法（Microsoft 365
MCPサーバーの追加）を案内するに留める。誤って未対応のイベント形式を
Google Calendar用のパーサーに渡さないこと。
