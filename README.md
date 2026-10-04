# Vault

Obsidian を第2の脳として使う Vault。入口はタスクの1本にし、タスクノートに経緯を書きため、1日の締めで知識を棚卸しする。ルールは [[CLAUDE]]、セットアップ手順は [[90_system/setup]] を参照。

- 構成とプロパティ: `CLAUDE.md`（個人の設定は `PERSONAL.md`。Git では追跡しない）
- 1日の流れ: 朝 `daily-start` → 日中はタスクに経緯を書く（`task-add` / `task-split` / `task-run`）→ 締め `daily-end`（棚卸しは `knowledge-harvest`）
- インボックス: `00_inbox/`（振り分け前のタスク・grilling-html のセッション・資料・文字起こし。振り分けは `daily-end`）
- タスク一覧: `90_system/bases/tasks.base`（未完了・プロジェクト別・アイデア・塩漬け・中止・要修正・完了）
- プロジェクト一覧: `90_system/bases/projects.base`、プロジェクトごとの知識・資料: `90_system/bases/project-materials.base`
- ナレッジ・調べもの・判断・失敗の一覧: `90_system/bases/knowledge.base`
- Claude のインプット: `80_context/`（技術知見・判断記録・失敗記録・進捗ログ。索引 `_index.md` と再発防止のルール `_rules.md` は CLAUDE.md から読み込まれる）
- 議事録: `70_meetings/`（一覧は `90_system/bases/meetings.base`。作成とタスク化は `meeting-import`）
- そのほかのスキル: `project-add`（プロジェクトの追加）、`gantt-update`（ガントだけ更新）、`grilling-html`（HTML のフォームで grilling）、`personal-setup`（個人の設定のインタビュー）、`skill-explain`（スキルの解説ノート）
- フック: `.claude/hooks/vault_hooks.py`（セッション開始時の状況表示とガント更新、タスク編集後のガント更新、応答の完了・確認待ちの Windows の通知）
- スキルの解説: `90_system/skill-docs/`
