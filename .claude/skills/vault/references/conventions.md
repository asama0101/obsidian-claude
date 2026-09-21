# 共通実装規約

vaultプラグインの全スキルが従う共通ルール。決定的な処理は
`scripts/vault_lib.py`の関数として実装済みで、各スキルはこれらを
呼び出すPythonスクリプト（`scripts/*.py`）を実行するだけでよい。

## ファイル名
- `vault_lib.sanitize_filename`: Windows禁止文字 `\ / : * ? " < > |` を
  ノートタイトルから除去し、80文字で切り詰める。
- `vault_lib.unique_path`: 既存ファイルと衝突する場合は`-2`等の
  suffixを付与する（内容の上書きは絶対にしない）。

## 既存ノートのfrontmatter部分更新
`vault_lib.get_fm_value` / `set_fm_value`を使う。frontmatter全体を
YAMLとして再構成せず、該当キーの行だけを文字列操作で置換する
（コメントや手書き整形を壊さないため）。

## マーカー間コンテンツの置換
`vault_lib.get_marker_block` / `set_marker_block`を使う。
`<!-- X_START -->`〜`<!-- X_END -->`の間だけを置き換える
（マーカー行自体は残す）。対象: CARRYOVER（today）、
UPDATED_NOTES（close）、NEW_MEETING（meeting）。

## Templater風プレースホルダ
`vault_lib.fill_template`が扱う4種のみ: `{{title}}`
`{{date:YYYY-MM-DD}}` `{{date:ddd}}`（日本語の曜日1文字）
`{{time:HH:mm}}`。Obsidianのテンプレート挿入機能は使わない
（Pythonスクリプトが直接ファイルを書くため）。

## スクリプトとの連携
各SKILL.mdは`python .claude/skills/vault/scripts/<script>.py`を実行し、
標準出力のJSONを見て結果を判断する。`status`が`blocked`/`error`系
ならその内容をそのままユーザーに提示し、次の指示を仰ぐ。
`ok`系なら結果を要約して報告する。
