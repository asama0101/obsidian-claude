---
name: webclip
description: |
  指定URLのWebページを要約・画像保存してノート化する。「このページを
  クリップして」「Webクリップ作って」「/webclip <URL>」等のトリガーで
  起動する。
---

# webclip

## 目的
Webページの内容を後から参照できる形でVaultに保存する。

## 入力
対象URL。

## 出力
- `80_Attachments/` にダウンロード保存した主要画像
- `WebClip_Template.md` ベースのノート（`30_Resources/WebClips/`）

## 処理の流れ
1. **Claudeが対象URLをPlaywright（実ブラウザ経由）で取得する。**
   広告ブロック検知や会員限定表示のために本文がほとんど取得できないサイトが
   あるため、常に最初からPlaywrightのブラウザツールを使う
   （他の取得手段へのフォールバックはしない）。
   - `mcp__plugin_playwright_playwright__browser_navigate`で対象URLへ遷移する。
   - 遅延読み込み画像を取りこぼさないよう、本文・画像を取得する前に
     ページ全体を下までスクロールする。
   - `mcp__plugin_playwright_playwright__browser_evaluate`でページ内JSを実行し、
     本文テキスト（例: `document.querySelector('article') || document.body`の
     `innerText`）と本文中の画像URL一覧（`querySelectorAll('img')`の`src`。
     関連記事サムネイル・SNSアイコン等は除外）を取得する。
   - ページ内に「次ページ」等の分割ページへのリンクがないか確認する。
     あれば同様に`browser_navigate`→`browser_evaluate`を繰り返して辿り、
     各ページの本文・画像を記事内での出現順を保ったまま連結する。
     巡回には安全弁として上限20ページを設け、超えた場合は打ち切って
     その旨を最終報告でユーザーに伝える。
   - 取得が完了したら、開いたページ/タブを閉じる
     （`mcp__plugin_playwright_playwright__browser_close`等）。
2. **Claudeが取得した本文から要約・キーポイント・全文を作る。**
   - 3行程度または箇条書きの要約（`summary`）
   - 要点の箇条書き（`key_points`）
   - 本文の全文（`full_text`）
     - 記事本文中に含まれる画像は**全て**、元の記事内での位置関係を保ったまま
       標準Markdown画像記法`![alt](元の画像URL)`でテキスト中にインライン
       埋め込みする（テキスト自体は加工せず、長さの上限も設けない）。
     - 小さい画像・ロゴ・アイコン的な装飾画像は`full_text`への埋め込みからも
       除外してよい。
   - `summary`・`key_points`の各項目には、そのキーポイント単体を理解する上で
     本当に必要な画像だけを厳選し、`image_url`を設定する。
     - `full_text`側に既に本文の全画像が含まれるため、`summary`/`key_points`側で
       安易に画像を重ねる必要はない。対応が判別できない画像や、無くても
       理解に支障が無い画像は`image_url`に含めない。
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
     "full_text": "冒頭のテキスト\n\n![説明](https://example.com/img1.jpg)\n\n続きのテキスト..."
   }
   ```
   - `summary`/`key_points`の各要素は`text`（必須）と`image_url`（任意）を持つ
     オブジェクト。そのキーポイント単体の理解に本当に必要な、厳選した画像
     以外には`image_url`を設定しない。
   - `full_text`は記事本文の画像を全て、元の記事内での位置関係を保ったまま
     `![alt](元のURL)`形式でインライン埋め込みしたテキスト。
4. **カテゴリタグを確定する。**
   `python .claude/skills/vault/scripts/list_categories.py` を実行し、
   既存の `<category>/<topic>` タグ一覧を取得する。これを候補として
   （「新規作成」の選択肢も併記して）ユーザーに提示し、明示的に選択・
   入力するまで待つ（自動決定はしない。`references/category-tagging.md`
   を参照）。
5. **`webclip_save.py` を実行する。**
   ```
   python .claude/skills/vault/scripts/webclip_save.py \
     --url <URL> --content-json <JSONファイルパス> --tag <確定したタグ>
   ```
   - `summary`/`key_points`の`image_url`と`full_text`中の`![alt](URL)`を
     まとめて重複排除した上で、画像を`80_Attachments/`にダウンロード保存する
     （個々の失敗はスキップし、ノート作成自体は継続する）。
   - `full_text`中の`![alt](URL)`は、ダウンロードできた画像はローカル埋め込み
     `![[80_Attachments/...]]`に置換され、ダウンロードに失敗した箇所は
     取り除かれた上で「📄 クリップ本文」セクションにblockquote形式で入る。
   - `WebClip_Template.md`ベースのノートを`30_Resources/WebClips/`に作成し、
     結果（`note_path`・`images_saved`・`images_failed`）をJSONで出力する。
6. **Claudeが結果を要約報告する。**
   - 作成したノートのパス、保存できた画像数、失敗した画像があればその旨を
     ユーザーに伝える。

## 参照ドキュメント

- `references/category-tagging.md`: カテゴリタグ（`<category>/<topic>`）の
  取得方法・確認必須ポリシー（knowhowと共通）
