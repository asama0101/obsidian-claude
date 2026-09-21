# obsidian

Obsidian VaultとClaude Codeプラグイン（`vault`）を1リポジトリで管理するモノレポ。
Vault本体（Markdownノート・テンプレート・Bases定義）と、その運用を自動化するClaude Codeスキル群を同居させている。
このリポジトリを初めて触る人（将来の自分を含む）が、構成と日々の使い方を把握するための入口。

## これは何か

- **Obsidian Vault**: PARA的な構成のノート群（デイリーノート・プロジェクト・ナレッジ等）。
- **Claude Codeプラグイン**: `.claude/skills/vault/` に実装された7つのスキル。
  ノート作成・議事録同期・タスク抽出などをPythonスクリプト＋Claudeの判断で自動化する。

両者は密結合している。スキルが読み書きする対象がVault自身のノートだからである。

## フォルダ構成

| パス | 役割 |
|------|------|
| `00_Daily/` | デイリーノート（`today`スキルが作成） |
| `10_Projects/` | プロジェクト単位のフォルダ。各配下に `Tasks/`・`Meetings/`・`Documents/` |
| `20_Areas/Knowledge/` | ナレッジノート（`knowhow`スキルが整形） |
| `20_Areas/Meetings/` | プロジェクトに紐付かない議事録 |
| `30_Resources/WebClips/` | Webクリップ（`webclip`スキルが保存） |
| `40_Archives/` | 完了・非アクティブになったノートの置き場 |
| `70_Templates/` | 各ノート種別のテンプレート（後述） |
| `80_Attachments/` | 画像等の添付ファイル |
| `90_Bases/` | Obsidian Bases定義（`*.base`ファイル、後述） |
| `.claude/skills/vault/` | Claude Codeプラグイン本体（後述） |

## プラグイン本体の構成

```
.claude/skills/vault/
├── .claude-plugin/plugin.json   # プラグイン定義（name/version/description）
├── skills/<name>/SKILL.md       # 各スキルの仕様（7スキル分）
├── scripts/                     # 実装本体（Pythonスクリプト）
│   ├── vault_lib.py             # 共通ヘルパー（ファイル名サニタイズ・プロジェクト紐付け等）
│   ├── <name>_*.py              # 各スキルのエントリポイント
│   └── tests/                   # ユニットテスト（139件）
└── references/                  # スキル横断の設計ドキュメント（後述）
```

## 7スキルの一覧

各スキルの詳細は `SKILL.md` にまとまっている。ここでは役割のみ示す。

| スキル | 役割 | 詳細 |
|--------|------|------|
| `today` | 当日ブランチを作成し、デイリーノートを新規作成する（1日の作業開始） | [SKILL.md](.claude/skills/vault/skills/today/SKILL.md) |
| `meeting` | Google Calendarの予定から議事録ノートを作成・更新する | [SKILL.md](.claude/skills/vault/skills/meeting/SKILL.md) |
| `webclip` | 指定URLのWebページを要約・画像保存してノート化する | [SKILL.md](.claude/skills/vault/skills/webclip/SKILL.md) |
| `knowhow` | 雑多なメモ・ログをナレッジノートとして整形保存する | [SKILL.md](.claude/skills/vault/skills/knowhow/SKILL.md) |
| `task` | 議事録のアクションアイテムやCLI入力からタスクノートを抽出・作成する | [SKILL.md](.claude/skills/vault/skills/task/SKILL.md) |
| `project` | プロジェクト概要ノートとTasks/Meetings/Documentsフォルダを一括作成する | [SKILL.md](.claude/skills/vault/skills/project/SKILL.md) |
| `close` | 当日ブランチの変更をコミットしmainへマージする（1日の作業終了） | [SKILL.md](.claude/skills/vault/skills/close/SKILL.md) |

## 90_Bases/ のBases定義

Obsidian Basesプラグインのビュー定義。対応するノート種別を一覧・フィルタ表示する。

| ファイル | 対象 |
|----------|------|
| `Knowhow.base` | `type == "knowhow"` のノート（全件・カテゴリ別の2ビュー） |
| `Meetings.base` | `type == "meeting"` / `"meeting_series"` のノート |
| `Projects.base` | `10_Projects/` 配下の `type == "project"` のノート |
| `Tasks.base` | `type == "task"` のノート |

## セットアップ要件

- **Python**: スクリプトは標準ライブラリのみで動作する（`pathlib`・`argparse`・`urllib.request`等）。追加パッケージのインストールは不要。
- **Git**: `today`/`close`スキルがブランチ操作・コミット・マージを行うため必須。
- **Google Calendar MCP**: `meeting`スキルの実行にはClaude CodeにGoogle Calendar MCP（`list_events`）が接続済みである必要がある。未接続の場合、`meeting`スキルは動作しない。
- **Microsoft 365 MCP**: 任意。接続時のフィールド対応は `references/meeting-field-mapping.md` を参照（本リポジトリの標準構成では未接続）。

## 日次ワークフロー

1. `today` を実行し、当日ブランチ（`YYYY-MM-DD`形式）を作成してデイリーノートを用意する。
2. 作業中は `meeting`・`webclip`・`knowhow`・`task`・`project` を必要に応じて実行し、当日ブランチ上にノートを蓄積する。
3. 作業終了時に `close` を実行し、当日ブランチの変更をコミットして `main` へ ff-only マージする。

ブランチ運用・スクリプト実装方針など、Claude Codeがこのリポジトリで作業する際の詳細ルールは [CLAUDE.md](CLAUDE.md) を参照。

## テストの実行方法

```bash
cd .claude/skills/vault/scripts
PYTHONUTF8=1 python -m unittest discover -s tests
```

現在139件全て成功する。

---
最終更新: 2026-09-21
