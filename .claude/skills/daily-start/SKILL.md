---
name: daily-start
description: 今日のデイリーノートを作成し、ガントチャートを再生成して Obsidian で開く。スタートアップ（daily-start.bat）や、ユーザーが「デイリーノートを作って」「ガントを更新して」と言ったときに使う。
allowed-tools: Bash(python ${CLAUDE_SKILL_DIR}/daily_start.py) Bash(python "${CLAUDE_SKILL_DIR}/daily_start.py") Bash(python ${CLAUDE_SKILL_DIR}/daily_start.py *) Bash(python "${CLAUDE_SKILL_DIR}/daily_start.py" *) Bash(python .claude/skills/daily-start/daily_start.py) Bash(python .claude/skills/daily-start/daily_start.py *)
---

# daily-start

次のコマンドを**そのまま**1回だけ実行する。引数の追加や改変、ほかのコマンドの実行はしない。

```
python "${CLAUDE_SKILL_DIR}/daily_start.py"
```

実行結果の1行目（`作成: ...` / `既存: ...`）をユーザーに短く伝える。2行目以降に `注意: ...` があれば、それも伝える。エラーが出たら、そのメッセージをそのまま報告して終了する。

- ノートが既にあれば作成せず、ガントのみ再生成する。
- 読めないタスクや、`start` / `due` が空・不正なタスクは、ガントに出さずに `注意: ...` に名前が出る。
- ガントだけ更新したいときは、このスキルではなく `gantt-update` スキルを使う（ノートの作成をしない）。
- Obsidian を起動したくないとき（ユーザーの指示がある場合のみ）は `--no-launch` を付ける。
- テスト: `python -m unittest discover -s .claude/skills/daily-start/tests`
