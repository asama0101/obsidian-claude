---
paths:
  - "10_projects/**"
  - "30_knowledge/**"
  - "50_documents/**"
  - "80_context/**"
---

# プロジェクト・知識・資料・Claude のインプット

## プロジェクト（`10_projects/<名前>/<名前>.md`）
- プロパティ: `status`（active / on-hold / done）・`start`・`due`。追加は `project-add`。
- 「知識・資料」（`project-materials.base`）には、`project` が一致する knowledge / doc と、プロジェクトのフォルダの中のファイル（PDF なども）が出る。

## knowledge（`30_knowledge/`）
- `status` は付けない。いつの情報かは `created` で見る。
- 任意で `source`（主な出典 URL）。複数の出典や URL でない出典は、本文の「出典」に書く。
- 任意で `project`。

## doc（`50_documents/` か、プロジェクトのフォルダ）
- `status`（draft / done）。任意で `project`。

## 80_context
- プロパティを付けない。テンプレートはない。書式の正本は `.claude/skills/knowledge-harvest/SKILL.md` の「80_context の書式」（`harvest.py` が解析するので崩さない）。
- 1件は `## タイトル`。リンクは `[[判断記録#タイトル]]` の形。
- 進捗ログはプロジェクトごとの `## プロジェクト名` の節。「現在の要約」を書き換え、日付の記録を新しい順に足す。
- `_index.md` と `_rules.md` は自動生成なので、手で編集しない。
