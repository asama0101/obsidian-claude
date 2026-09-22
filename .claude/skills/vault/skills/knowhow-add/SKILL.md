---
name: knowhow
description: |
  雑多なメモ・ログ・コンソール出力等をナレッジノートとして整形保存する。
  「これノウハウとして残して」「ナレッジ化して」「/knowhow」等の
  トリガーで起動する。
---

# knowhow

## 目的
断片的な情報を再利用可能なナレッジノートとして整形する。

## 入力
雑多なメモ・ログ・コンソール出力等のテキスト。

## 出力
`Knowhow_Template.md` の構造（概要→手順→注意点）に整形した
ノート（`20_Areas/Knowledge/`）。

## 処理の流れ
1. Claude が入力（雑多なメモ・ログ・コンソール出力等）を読み、
   「概要・結論」「手順・実行方法/解決策」「注意点・ハマりポイント」
   「参照・関連リンク」に整形する。
2. 元の入力テキストは加工せず `original_text` としてそのまま保持する。
3. 上記を次の形式の JSON ファイルに書き出す。

   ```json
   {
     "title": "...",
     "overview": "...",
     "steps": ["...", "..."],
     "pitfalls": ["...", "..."],
     "references": ["...", "..."],
     "original_text": "..."
   }
   ```

4. `python .claude/skills/vault/scripts/list_categories.py` を実行し、
   既存の `<category>/<topic>` タグ一覧を取得する。これを候補として
   （「新規作成」の選択肢も併記して）ユーザーに提示し、明示的に選択・
   入力するまで待つ（自動決定はしない。`references/category-tagging.md`
   を参照）。
5. `scripts/knowhow_save.py --content-json <path> --tag <確定したタグ>`
   を実行する。スクリプトが `Knowhow_Template.md` を展開し、
   `20_Areas/Knowledge/` にノートを保存して `{"note_path": "..."}` を
   出力する。
6. 出力された `note_path` を確認し、保存結果をユーザーに報告する。

## カテゴリタグについて
Knowhowノートの分類は `tags` の `<category>/<topic>` 階層タグのみで
行う（独立した `category` プロパティは廃止済み）。取得方法・確認
必須ポリシーの詳細は `references/category-tagging.md` を参照。
