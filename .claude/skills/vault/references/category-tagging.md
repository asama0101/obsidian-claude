# カテゴリタグ運用ルール（knowhow / webclip 共通）

Knowhow・WebClipのノートは共通の分類軸として、`tags`に
`<category>/<topic>`形式の階層タグを1本追加する（例:
`python/pandas`、`git/rebase`）。同じカテゴリ語彙をKnowhowと
WebClipで共有し、横断的に分類・検索できるようにするための仕組み。

Knowhowの旧`category`frontmatterプロパティは廃止済み。WebClipには
元々categoryの概念は無かった。今はどちらもこのタグのみで分類する。

## 既存候補の取得

`python .claude/skills/vault/scripts/list_categories.py [--vault-root <path>]`

- `40_Resources/Knowledge/`と`40_Resources/WebClips/`配下の全ノートの
  `tags`を走査し、`/`をちょうど1つ含むタグ（＝カテゴリタグ）だけを
  収集する。
- 重複を除去・ソートして`{"tags": ["git/xxx", "python/pandas", ...]}`
  をJSONで返す。判断は一切行わない機械的な集計処理。

## 確認必須ポリシー

カテゴリタグはClaudeが単独で自動決定してはならない。

1. `list_categories.py`の出力（既存タグ一覧）をユーザーに候補として
   提示する。「新規作成」（category・topicとも自由入力）の選択肢も
   必ず併記する。既存候補が0件（`{"tags": []}`）の場合は、自由入力
   だけに丸投げせず、保存しようとしている内容からClaudeが
   `<category>/<topic>`形式のタグ候補を数件判断して提案する
   （件数は内容に応じてClaudeが判断してよい）。この場合も自由入力の
   選択肢は併記し、提案はあくまで候補にとどめる。
2. ユーザーが既存タグを選ぶか新規タグを作るか、明示的に選択・入力
   するまで待つ。
3. 確定したタグを`knowhow_save.py --tag <値>` / `webclip_save.py --tag <値>`
   に渡す。

これは`task`スキルの「project不明なら必ず確認する」方針と同型。
`meeting`の`fuzzy_project_match`（1件に絞れれば自動設定する）とは
対照的に、カテゴリタグは常にユーザー確認を経る。
