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
2. **Claudeが取得した本文から要約・キーポイント・全文を作る。**
   - 3行程度または箇条書きの要約（`summary`）
   - 要点の箇条書き（`key_points`）
   - 本文の全文（`full_text`、長さの上限は設けず加工しない）
   - `summary`・`key_points`の各項目には、その項目の内容を表す画像が本文中に
     あると判断できた場合のみ`image_url`を設定する。
     - どの項目を表す画像か対応が判別できない画像は、そもそも`image_url`に
       含めない（保存しない）。
     - 小さい画像・ロゴ・アイコン的な画像はClaude自身の判断で候補から除外する。
   - 有料会員限定等の理由で本文の一部しか取得できなかった場合は、その旨を
     `full_text` 等に明記する（ノート作成前に必ず断り書きを入れる）。
3. **上記の内容をJSONファイルに書き出す。**
   ```json
   {
     "title": "...",
     "summary": [
       {"text": "...", "image_url": "https://..."},
       {"text": "..."}
     ],
     "key_points": [
       {"text": "...", "image_url": "https://..."},
       {"text": "..."}
     ],
     "full_text": "..."
   }
   ```
   - `summary`/`key_points`の各要素は`text`（必須）と`image_url`（任意）を持つ
     オブジェクト。対応する画像が無い・判別できない項目には`image_url`を
     設定しない。
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
