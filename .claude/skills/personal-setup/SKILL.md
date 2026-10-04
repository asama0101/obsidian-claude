---
name: personal-setup
description: 個人の設定（Vault 直下の PERSONAL.md。環境・仕事と役割・進め方の好み）を、grilling-html の形式でインタビューして作成・更新する。新しい PC で使い始めるとき、ユーザーが「個人の設定を更新して」「PERSONAL.md を作って」「personal-setup」と言ったときに使う。
allowed-tools: Bash(python ${CLAUDE_SKILL_DIR}/../grilling-html/grilling_html.py *) Bash(python "${CLAUDE_SKILL_DIR}/../grilling-html/grilling_html.py" *) Bash(python .claude/skills/grilling-html/grilling_html.py *)
---

# personal-setup

Vault のルートで作業する。`PERSONAL.md` は CLAUDE.md から `@PERSONAL.md` で読み込まれる、この PC・この利用者に固有の設定で、Git では追跡しない（配布しない）。**ユーザーが最終確認で承認するまで、`PERSONAL.md` を書かない**。

## 項目
- 環境: OS、Vault のパス、OneDrive などの同期、`.git` の実体の場所、Obsidian の場所、使っている PC の台数
- 仕事と役割: 仕事の内容・役割、よく作る資料の種類、よく使う用語（task-run や棚卸しの判断に使う）
- 進め方の好み: 報告の仕方、確認の基準、文体など（すべてのプロジェクトに共通の好みは、ユーザーレベルの `~\.claude\CLAUDE.md` にあるので、Vault に固有のものだけ）

## 手順
1. **今の値を集める。** `PERSONAL.md` があれば読む。環境は、調べられる事実（Vault のパス、`.git` ファイルの中身、OS、`C:\Program Files\Obsidian\Obsidian.exe` の有無など）を先に調べる。調べた値はユーザーに聞かず、推奨案として示す。
2. **セッションを作る。** 個人の情報なので、セッションは Vault の外（このセッションのスクラッチパッド）に作る。
   ```
   python "${CLAUDE_SKILL_DIR}/../grilling-html/grilling_html.py" init --theme "personal-setup" --parent "<スクラッチパッドのパス>"
   ```
3. **インタビューする。** `grilling-html` スキルの手順2〜6で、上の項目を質問にする（1ラウンド3〜7問。決まっていない項目から聞く）。更新のときは、今の値を推奨案（`recommended`・`reason` に「今の値」）として示し、変える所だけ答えてもらう。選択肢が作りにくい項目は、今の値を1つ目の選択肢にして、自由入力で答えてもらう。
4. **最終確認。** `grilling-html` の手順7で、書き込む `PERSONAL.md` の全文を `summary` にして確認する。`修正あり` なら直して繰り返す。
5. **書く。** 承認されたら `PERSONAL.md` を書く（既存があれば置き換える。置き換える前に、変わる行をユーザーに示してある状態にする）。書式:
   ```
   ---
   type: doc
   status: draft
   created: <最初に作った日>
   tags: []
   ---
   # 個人の設定

   （CLAUDE.md から読み込まれる旨の1行）

   ## 環境
   ## 仕事と役割
   ## 進め方の好み
   ```
6. **後片付け。** セッションのフォルダ（スクラッチパッドの中）を消す。個人の情報を Vault の中にも残さない。
7. 報告: 変えた項目と、次の会話から反映されること（今の会話には反映されない）。

## 注意
- 秘密情報（パスワード、トークン、キー）は聞かない・書かない。
- `PERSONAL.md` は `.gitignore` のホワイトリストに入っていないので追跡されない。ホワイトリストに足さない。
- 配布対象のファイル（スキル・CLAUDE.md など）には、個人の情報を書かず、ここに書く。
