---
name: daily-end
description: 1日の終わりに、振り返りの下書き、未完了タスクと idea の整理案、インボックスの振り分け案、知識の棚卸し（knowledge-harvest）の案、議事録の取り込み残りを出す。1回の承認で、ノートとタスクを更新する。ユーザーが「1日を終える」「振り返りを書いて」「今日を締めて」「daily-end」と言ったときに使う。
allowed-tools: Bash(python ${CLAUDE_SKILL_DIR}/../daily-start/daily_start.py --gantt-only) Bash(python "${CLAUDE_SKILL_DIR}/../daily-start/daily_start.py" --gantt-only) Bash(python .claude/skills/daily-start/daily_start.py --gantt-only) Bash(python ${CLAUDE_SKILL_DIR}/../knowledge-harvest/harvest.py *) Bash(python "${CLAUDE_SKILL_DIR}/../knowledge-harvest/harvest.py" *) Bash(python .claude/skills/knowledge-harvest/harvest.py *)
---

# daily-end

Vault のルートで作業する。**ユーザーが承認するまで、ノートの作成・編集・移動も、タスクの更新もしない**（案をまとめて出し、1回の承認を待つ）。Git の操作はしない（ノートは Git で管理していない）。

## 手順
1. 対象は `60_daily/<今日 YYYY-MM-DD>.md`。無ければ、作成せずにユーザーへ伝えて終了する（作成は `daily-start`）。
2. デイリーノートを読み、「今日のメモ」を把握する。空欄は「未記入」として扱い、書かれていない内容を作らない。
3. `20_tasks/` と `00_inbox/` の直下のタスク（`type: task`）を読み、次を把握する（frontmatter の `status` `due` `start` `completed` `memo` と、本文の「経緯」）。
   - 今日完了したもの（`completed` が今日）
   - 進めるもの（`todo` / `in_progress` / `waiting` / `requested`）
   - `idea`
4. **振り返りの下書き**を作る。次の見出しで数行ずつ。根拠がない項目は書かず「未記入」とする。
   - できたこと（完了タスク、今日の経緯から）
   - 気づき・学び（今日のメモ、経緯から）
   - 明日へ（持ち越し・メモ）
5. **未完了タスクの整理案**（進めるもの）を表にする。タスクごとに推奨と理由を示す。
   - 翌日へ: `start` / `due` の変更案
   - 状態の変更: `in_progress`・`waiting`（保留。`memo` に理由）・`requested`（依頼中。`memo` に相手と内容）・`shelved`（塩漬け）・`cancelled`（中止）
   - 現状維持
   - タスクは削除しない（中止は `cancelled`）。
6. **idea の見直し案**: `idea` のタスクごとに、`todo` にする（`start` / `due` の案。指定がなければ当日）・`idea` のまま・`shelved`・`cancelled` のどれかを推奨する。作成から日が浅いものは「`idea` のまま」でよい。
7. **インボックスの振り分け案**: `00_inbox/` の直下（`.gitkeep` 以外）を1件ずつ表にする。無ければ省く。
   - タスク（`type: task`）: `project`（`10_projects/` のプロジェクト名。属さなければ空）を決め、`20_tasks/` へ移す。状態と日付は手順5・6の案に合わせる。タイトルから目的が読み取れないものは、目的が分かる名前への変更案を出す。
   - grilling-html のセッション（`<日時>_grilling_<テーマ>/` のフォルダ）・ダウンロードした資料などのファイル: プロジェクトに属せば `10_projects/<名前>/`、属さなければ `50_documents/` へ移す。
   - 会議の文字起こし（`.docx` / `.vtt`）や会議のメモ: 移さず、`meeting-import` で議事録にすることを提案する。
   - そのほかのノート: 内容に応じて移動先（`30_knowledge/`・`40_research/`（ファイル名に `YYYY-MM-DD_`）・`50_documents/` など）を推奨する。種類のテンプレート（`90_system/templates/`）にないプロパティ（`type` など）があれば補う案も示す。
   - 迷うものは選択肢を示して聞く。決まらないものは残す。
8. **知識の棚卸し**: `knowledge-harvest` スキル（`.claude/skills/knowledge-harvest/SKILL.md`）の手順2〜4で、今日のメモと、前回の棚卸し以降に更新したタスクの経緯から、案を作る。対象は、次のコマンドを**そのまま**実行して集める（`knowledge-harvest` の手順1の代わり）。
   ```
   python "${CLAUDE_SKILL_DIR}/../knowledge-harvest/harvest.py" targets
   ```
9. **議事録の取り込み残り**を指摘する（案ではなく報告）。
   - `00_inbox/` に残っている文字起こし・会議のメモ
   - 今日の議事録（`70_meetings/` の `date` が今日）のうち、アクションアイテムが空、またはタスクの印（` → [[`）がない行があるもの
   - どちらも `meeting-import` で処理できることを添える。
10. 手順4〜8の案をまとめて示し、ユーザーの承認（訂正があれば反映）を1回得る。
11. 承認されたものを実行する。
    - 振り返りを、デイリーノートの `## 振り返り` に書く（既存の記述があれば追記し、上書きしない）。
    - タスクの更新を frontmatter に反映する。`status: done` にするときは `completed` も必ず入れる。
    - インボックスの移動を行う。移動先に同名のものがあれば、上書きせずに伝える。
    - 棚卸しを、`knowledge-harvest` の手順5で行う（確認は、この承認で済んだものとする）。続けて、次のコマンドを**そのまま**順に実行する（`knowledge-harvest` の手順6の代わり。棚卸しで何も残さなかった場合も実行する）。
      ```
      python "${CLAUDE_SKILL_DIR}/../knowledge-harvest/harvest.py" index
      python "${CLAUDE_SKILL_DIR}/../knowledge-harvest/harvest.py" mark
      ```
12. タスクを更新・移動した場合だけ、ガントを更新するため次のコマンドを**そのまま**1回実行する。

```
python "${CLAUDE_SKILL_DIR}/../daily-start/daily_start.py" --gantt-only
```

## 注意
- `<!-- gantt:start -->` と `<!-- gantt:end -->` のマーカーと、その間は編集しない。
- 今日のメモと経緯の行は消さず、行末に印（` → [[ノート名]]`）を付けるだけにする。過去のデイリーのメモは対象にしない。
- 結果は「何を書いたか・何を更新・移動したか・棚卸しで作ったノート（付けたタグ。新規のタグは明記）・取り込み残り・次にやること」を簡潔に報告する。
