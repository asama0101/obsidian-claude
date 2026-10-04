---
name: grilling-html
description: grilling（質問攻めで合意を作る手法）を HTML のフォームで行い、候補選択・自由入力・保留で内容を詰めて、最後に SPEC 形式で結果を出す。ユーザーが「HTML で grilling」「grilling-html」と明示したときだけ使う。通常の「grill」は grilling スキルを使う。
allowed-tools: Bash(python ${CLAUDE_SKILL_DIR}/grilling_html.py *) Bash(python "${CLAUDE_SKILL_DIR}/grilling_html.py" *) Bash(python .claude/skills/grilling-html/grilling_html.py *)
---

# grilling-html

`grilling` の流儀を HTML フォームで進め、合意内容を SPEC にまとめる。Vault ルートで作業する。設計は `10_projects/Claudeのスキル作成/grilling-html SPEC.md`。

## ルール（grilling から取り込み）
- 決定事項を design tree として扱う。前提が決着済みで今聞ける質問（frontier）を、1ラウンドにまとめて出す。回答を待ってから次へ進む。
- 各質問に推奨案（`recommended` と `reason`）を付ける。選択式にして、トレードオフを `desc` に書く。
- 環境から調べられる事実はサブエージェントに調べさせ、ユーザーには聞かない。決定だけをユーザーに聞く。調査待ちの質問は後のラウンドに回す。
- frontier が空になるまで続ける。ユーザーが承認するまで、実行（実装・ファイル作成）に移らない。
- 質問 ID（`Q1`, `Q2`…）はセッション通しで一意にする（ラウンドでリセットしない）。

## 手順
1. セッション作成: `python "${CLAUDE_SKILL_DIR}/grilling_html.py" init --theme "<テーマ>"` を実行する。テーマは ASCII の短い名前にする（Git Bash 経由の日本語引数は文字化けするため。例: `grilling-html`）。出力された絶対パス（以下 `<D>`）を控える。
2. 質問 JSON を書く。置き場所はスクラッチパッド。形式は `grilling_html.py` の docstring を参照（`title`, `intro`, `questions[]` = `id`, `title`, `body`, `multi`, `options[]` = `key`, `label`, `desc`、`recommended[]`, `reason`）。
3. 生成: `python "${CLAUDE_SKILL_DIR}/grilling_html.py" render --session-dir "<D>" --round <N> --input <json>` → `<D>\round-N.html`。
4. Playwright MCP で `browser_navigate` により `file:///<D のスラッシュ区切りパス>/round-N.html` を開く。ユーザーに「回答して『送信』を押し、ターミナルに『完了』と入力してください」と伝えて待つ。
5. 「完了」を受けたら、`browser_evaluate` で `() => ({ submitted: window.__submitted, md: window.__answersMd })` を実行する。
   - `submitted` が true なら、`md` をそのまま `<D>\round-N.answers.md` に書く（Write）。
   - false（未送信・ウィンドウを閉じた等）なら、書かずに続行方法を聞く。コピーボタンで Markdown を貼ってもらう手もある。
6. 回答を読んで design tree を更新し、次のラウンド（手順2〜）へ。ラウンドごとに新しい HTML を生成する。
7. frontier が空になったら、合意内容を SPEC 案（概要・流れ・受入条件・非目標・リスク・決定ログ）にまとめ、`{"title","intro","summary"}` の JSON で `render --final --round <N+1>` を実行して `final.html` を開く。回答は同様に `<D>\final.answers.md` に書く。
8. `承認` なら、SPEC の保存先と形式をユーザーに提案する（承認なしでは Vault に書かない）。保存したら `<D>\final-summary.md` にも要点を残し、`python "${CLAUDE_SKILL_DIR}/grilling_html.py" index --session-dir "<D>"` で `index.md` を更新する。`修正あり` ならコメントを反映して手順7を繰り返す。

## 回答 Markdown の書式（ページ側が生成する）
```
---
session: <フォルダ名>
round: <N>
---
## Q1
- 選択: A        （複数は「, 」区切り）
- 自由入力: …
- 補足: …
- 状態: 回答 / 保留 / 未回答
```
最終確認は `## 承認` に `判定`（承認 / 修正あり）と `コメント`。

## 注意
- 外部サービスへ送らない。HTML はローカルだけ。
- JS の `alert/confirm/prompt` は使わない（ブラウザ操作が止まる）。
- `file://` が開けない場合は、`--allow-unrestricted-file-access` 付きで Playwright MCP が設定されているかを確認する。
- 生成物（`90_system/grilling/`）のうち、git で追跡するのは Markdown（`*.answers.md`・`final-summary.md`・`index.md`）だけ。HTML は `.gitignore` で除外している（合意内容は Markdown に残るため）。
