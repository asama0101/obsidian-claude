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

## taskノートの`project`値
taskノートの`project`フロントマター値は常に`[[Name]]`形式
（Obsidianのwikilink）で統一する。`82_Bases/Tasks.base`の
`ProjectTasks`/`ProjectCompletedTasks`ビューは`project ==
link(this.file.name)`というLink型前提のフィルタを使っている。
そのため、プレーンテキストのままでは正しく表示されない。

書き込み前に`vault_lib.normalize_project_link(value: str) -> str`
（`extract_project_name`の直後に配置）で正規化してから
`set_fm_value`に渡す。

- 冪等: 既に`[[Name]]`形式なら変更しない
- 空文字列は正規化対象外: project未指定の意味を保持するため
  `"[[]]"`のような値にしない
- 実装例: `task_save.py:29`（`build_note_text`関数内）

## マーカー間コンテンツの置換
`vault_lib.get_marker_block` / `set_marker_block`を使う。
`<!-- X_START -->`〜`<!-- X_END -->`の間だけを置き換える
（マーカー行自体は残す）。対象: CARRYOVER（today）、
UPDATED_NOTES（close）、NEW_MEETING（meeting）、GANTT（task-gantt）。

`set_marker_block`は対象ノートにマーカーが存在しない場合、
無変更で元のテキストをそのまま返す（サイレント）。呼び出し元が
書き込みの成否を正確に報告する必要がある場合は、事前に
`vault_lib.has_marker_block`でマーカーの存在を確認すること
（`task_gantt.py`の実装を参照）。

## taskノートの「進捗メモ」見出しセクション操作
`vault_lib.PROGRESS_HEADING_PATTERN`（`## 📌 進捗メモ`見出しにマッチする正規表現）と、それを使う`get_heading_section` / `set_heading_section` / `extract_checkboxes`は、`task_gantt.py`（todoの読み取り・ガント上へのmilestone描画）と`task_todo_apply.py`（todoの追記・置換）の2ファイルで共有される規約である。

- `get_heading_section(text, pattern)`: 見出し直後〜次見出し直前の範囲を前後の改行1個ずつを除去して返す。見出しが無ければ空文字。
- `set_heading_section(text, pattern, new_content)`: 同範囲を`new_content`に置換する（前後に改行を1個ずつ挿入）。見出しが無ければ元のtextをそのまま返す。
- `extract_checkboxes(section_text)`: `- [ ] 本文` / `- [x] 本文` / `- [X] 本文`形式のチェックボックス行を`(label, done)`のタプルのリストで返す。本文が空のプレースホルダー行は除外する。

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
