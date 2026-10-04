# Vault

Obsidian を第2の脳として使う Vault。ルールは [[CLAUDE]]、セットアップ手順は [[90_system/setup]] を参照。

- 構成とプロパティ: `CLAUDE.md`
- タスク一覧: `90_system/bases/tasks.base`
- プロジェクト一覧: `90_system/bases/projects.base`
- ナレッジ・調べもの一覧: `90_system/bases/knowledge.base`
- プロジェクトごとの知識・資料: `90_system/bases/project-materials.base`（プロジェクトノートに埋め込み）
- インボックス: `00_inbox/`（Obsidian で新しく作ったノートの一時置き場。`daily-end` が振り分け案を出す）
- デイリーノート: `60_daily/`（`daily-start` スキルで作成、`daily-end` スキルで振り返りと今日のメモの振り分け）
- 追加・分解のスキル: `project-add` / `task-add` / `task-split`
- 調べものの保存: `knowledge-add`（`30_knowledge/` か `40_research/` に保存。タグは Claude が付ける）
- フック: `.claude/hooks/vault_hooks.py`（セッション開始時の状況表示とガント更新、タスク編集後のガント更新）
- 議事録: `70_meetings/`（一覧は `90_system/bases/meetings.base`。アクションアイテムのタスク化は `meeting-followup` スキル）