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
2. 内容から `category`（例: `python`, `git`, `obsidian` 等）を推測する。
3. 元の入力テキストは加工せず `original_text` としてそのまま保持する。
4. 上記を次の形式の JSON ファイルに書き出す。

   ```json
   {
     "title": "...",
     "category": "...",
     "overview": "...",
     "steps": ["...", "..."],
     "pitfalls": ["...", "..."],
     "references": ["...", "..."],
     "original_text": "..."
   }
   ```

5. `scripts/knowhow_save.py --content-json <path>` を実行する。
   スクリプトが `Knowhow_Template.md` を展開し、`20_Areas/Knowledge/`
   にノートを保存して `{"note_path": "..."}` を出力する。
6. 出力された `note_path` を確認し、保存結果をユーザーに報告する。

## category と階層タグの役割分担
- frontmatter の `category` は Bases（Dataview代替のクエリ/一覧機能）で
  ノートを分類・絞り込みするための値。
- `tags` に追加する `knowledge/<category>` は、要件書で定めたタグ運用方針
  （階層タグでの分類）に沿ったもの。
- 両者は用途が異なるため、`knowhow_save.py` はどちらも同時に設定する。
