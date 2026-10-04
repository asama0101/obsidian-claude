---
name: meeting-followup
description: 議事録ノート（70_meetings/）のアクションアイテムを、承認を得てタスクノート（20_tasks/）に起こし、議事録側の行末に「→ [[タスク名]]」の印を付ける。開始日・期限・プロジェクトは一覧にして1回でまとめて確認する。ユーザーが「議事録からタスク化して」「アクションアイテムをタスクにして」「会議のフォローアップ」「meeting-followup」と言ったときに使う。
allowed-tools: Bash(python ${CLAUDE_SKILL_DIR}/meeting_actions.py *) Bash(python "${CLAUDE_SKILL_DIR}/meeting_actions.py" *) Bash(python .claude/skills/meeting-followup/meeting_actions.py *) Bash(python ${CLAUDE_SKILL_DIR}/../daily-start/daily_start.py --gantt-only) Bash(python "${CLAUDE_SKILL_DIR}/../daily-start/daily_start.py" --gantt-only) Bash(python .claude/skills/daily-start/daily_start.py --gantt-only)
---

# meeting-followup

Vault のルートで作業する。議事録の書式は `90_system/templates/meeting.md`、タスクの書式は `90_system/templates/task.md`。**タスクの作成と議事録の書き換えは、案を示してユーザーが承認したものだけ**行う。

- アクションアイテムの書式: `- [ ] 内容 @担当 期限:YYYY-MM-DD`（担当と期限は省略可。自分の担当は `@自分` か省略）。
- 処理済みの印: 行末の ` → [[タスク名]]`（スクリプトが付ける）。印のある行、完了（`- [x]`）の行は対象外。

## 手順
コマンドは、下に書いた形のまま実行する（改変したり、自己流のコマンドを足したりしない）。議事録名・タスク名・項目の文言などの値は、シングルクォートで囲んで渡す（ダブルクォートの中では `$` やバッククォートが展開され、値が黙って変わるため）。値の中の `'` は `'\''` と書く。

1. **議事録を決める。** ユーザーが指定したものを使う（`70_meetings/` のファイル名。`.md` は省略できる）。指定がなければ、`70_meetings/` で今日の日付から始まるノートを探し、1件ならそれを使うことを伝え、複数なら選んでもらう。無ければ、どれかを聞く。
2. **項目を取得する。** `python "${CLAUDE_SKILL_DIR}/meeting_actions.py" list --meeting '<議事録名>'` を実行する。
   - `not_found` なら、議事録名を確認し直す。`invalid` なら、`problems` を伝えて終える。
   - `items` が空なら、その旨を伝えて終える。
   - 結果の `project` が議事録のプロジェクト（無ければ空）、`date` が開催日。各項目は `text`（本文そのもの。手順6で使う）・`content`（内容）・`assignee`（担当）・`due`（期限）。
3. **プロジェクトの候補を把握する。** `10_projects/` の直下のフォルダ名が、プロジェクト名。
4. **案を一覧で示し、まとめて1回だけ確認する。** 各項目について、タスクにするか、タスク名、`start`、`due`、`project` の案を表にする。
   - タスク名: `content` を日本語で簡潔に整える。Windows で使えない文字 `\ / : * ? " < > |` は除く。`20_tasks/` に同名があれば、別名を提案する。
   - `start`: 既定は今日。`due`: 項目の `due`。無ければ今日（推測で別の日にしない。表で「既定」と分かるようにする）。
   - `project`: 既定は議事録の `project`。
   - `assignee` が空でも `自分` でもない項目は、「他の人の担当」として表とは別に示す。ユーザーが希望したものだけタスクにする。
   - 案を確定させず、ユーザーが確認・訂正した値だけを使う。タスクにしない項目は、そのまま残す。
5. **タスクを作る。** 承認された項目ごとに、`90_system/templates/task.md` に従って `20_tasks/<タスク名>.md` を作る。
   - `status: todo`、`project: "[[プロジェクト名]]"`（無ければ空）、`start`・`due`、`completed` は空、`memo` は空、`created` は今日、`tags: []`。
   - `project` の次の行に `meeting: "[[<議事録名>]]"` を足す（このスキルで作るタスクだけが持つプロパティ）。
   - 本文は見出し `# <タスク名>` のあとに、`議事録 [[<議事録名>]] のアクションアイテム「<content>」から作成。` と1行書く。
   - 既存のノートは上書きしない。
6. **議事録に印を付ける。** 作ったタスクごとに、`python "${CLAUDE_SKILL_DIR}/meeting_actions.py" link --meeting '<議事録名>' --text '<手順2の text>' --task '<タスク名>'` を実行する。
   - `text` は手順2の結果をそのまま使う（行番号でなく文言で指定する）。
   - 結果が `linked` 以外のときは、タスクを作り直さない。手順2の `list` をもう一度実行して、議事録の現在の文言を確かめる（確認のあいだに Obsidian で書き換えられた可能性がある）。作成済みのタスク名と現在の文言をユーザーに示し、確認を取ってから、現在の文言で `link` だけをやり直す。
7. **ガントを更新する。** タスクを1件以上作ったら、次のコマンドを**そのまま**1回実行する（`main` 上や今日のデイリーノートが無いときは警告が出るだけなので、そのまま伝える）。

```
python "${CLAUDE_SKILL_DIR}/../daily-start/daily_start.py" --gantt-only
```

8. **報告する。** 作ったタスクの一覧（名前・プロジェクト・開始日〜期限）、タスクにしないで残した項目、他の人の担当として残した項目を伝える。

## 注意
- 対象は `## アクションアイテム` の節だけ。`## 議事・決定事項` などからは、勝手にタスクを作らない。
- 議事録の frontmatter や、ほかの行は書き換えない（印を付けるのはスクリプトだけ）。
- 外部サービスへ情報を送らない。
- テスト: `python -m unittest discover -s .claude/skills/meeting-followup/tests`
