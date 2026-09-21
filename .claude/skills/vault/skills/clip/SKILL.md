---
name: clip
description: |
  指定URLのWebページを要約・画像保存してノート化する。「このページを
  クリップして」「Webクリップ作って」「/clip <URL>」等のトリガーで
  起動する。
---

# clip

## 目的
Webページの内容を後から参照できる形でVaultに保存する。

## 入力
対象URL（任意でプロジェクトの手がかりとなるテキスト）。

## 出力
- `80_Attachments/` にダウンロード保存した主要画像
- `WebClip_Template.md` ベースのノート（`30_Resources/WebClips/`）

## 処理の流れ
1. **Claudeが対象URLをWebFetchで取得する。**
2. **Claudeが取得した本文から要約・キーポイント・抜粋・画像候補を作る。**
   - 3行程度または箇条書きの要約（`summary`）
   - 要点の箇条書き（`key_points`）
   - 本文からの抜粋（`excerpt`）
   - 埋め込む価値のある主要画像のURL一覧（`image_urls`）
     - 小さい画像・ロゴ・アイコン的な画像はClaude自身の判断で候補から除外する。
   - 有料会員限定等の理由で本文の一部しか取得できなかった場合は、その旨を
     `excerpt` 等に明記する（ノート作成前に必ず断り書きを入れる）。
3. **上記の内容をJSONファイルに書き出す。**
   ```json
   {
     "title": "...",
     "summary": ["...", "..."],
     "key_points": ["...", "..."],
     "excerpt": "...",
     "image_urls": ["https://...", "..."]
   }
   ```
4. **`clip_save.py` を実行する。**
   ```
   python .claude/skills/vault/scripts/clip_save.py \
     --url <URL> --content-json <JSONファイルパス> [--project-hint <text>]
   ```
   - 画像を`80_Attachments/`にダウンロード保存する（個々の失敗はスキップし、
     ノート作成自体は継続する）。
   - `project-hint`が指定された場合は`10_Projects/`配下からあいまい一致で
     プロジェクトを推定し、1件に絞れた場合のみfrontmatterに設定する。
   - `WebClip_Template.md`ベースのノートを`30_Resources/WebClips/`に作成し、
     結果（`note_path`・`images_saved`・`images_failed`）をJSONで出力する。
5. **Claudeが結果を要約報告する。**
   - 作成したノートのパス、保存できた画像数、失敗した画像があればその旨を
     ユーザーに伝える。
