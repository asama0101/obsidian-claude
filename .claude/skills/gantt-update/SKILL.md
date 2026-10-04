---
name: gantt-update
description: 今日のデイリーノートのガントチャートだけを、20_tasks のタスクから再生成する（ノートの作成や Obsidian の起動はしない）。ユーザーが「ガントを更新して」「ガントチャートを最新にして」「gantt-update」と言ったときに使う。
allowed-tools: Bash(python ${CLAUDE_SKILL_DIR}/../daily-start/daily_start.py --gantt-only) Bash(python "${CLAUDE_SKILL_DIR}/../daily-start/daily_start.py" --gantt-only) Bash(python ${CLAUDE_SKILL_DIR}/../daily-start/daily_start.py --gantt-only *) Bash(python "${CLAUDE_SKILL_DIR}/../daily-start/daily_start.py" --gantt-only *) Bash(python .claude/skills/daily-start/daily_start.py --gantt-only) Bash(python .claude/skills/daily-start/daily_start.py --gantt-only *)
---

# gantt-update

次のコマンドを**そのまま**1回だけ実行する。引数の追加や改変、ほかのコマンドの実行はしない。

```
python "${CLAUDE_SKILL_DIR}/../daily-start/daily_start.py" --gantt-only
```

実行結果の1行目（`更新: ...` または `警告: ...`）をユーザーに短く伝える。2行目以降に `注意: ...`（ガントに出せなかったタスク）があれば、それも伝える。エラーが出たら、そのメッセージをそのまま報告して終了する。

- 更新するのは、`60_daily/<今日>.md` の `<!-- gantt:start -->` 〜 `<!-- gantt:end -->` の間だけ。ほかの部分は変更しない。
- 次の場合は、何も更新せず、警告を伝えて終了する。
  - 今日のデイリーノートがない（作成は `daily-start`）。
  - ノートにガントのマーカーがない。
- ノートの作成、Obsidian の起動はしない。これらを行うときは `daily-start` を使う。
- 今日以外の日付を更新したいとき（ユーザーの指示がある場合のみ）は、`--date YYYY-MM-DD` を付ける。
