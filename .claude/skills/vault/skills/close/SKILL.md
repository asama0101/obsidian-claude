---
name: close
description: |
  1日の作業終了時に実行する。当日ブランチの変更をコミットしmainへ
  マージする。「今日を終わる」「クローズして」「/close」等のトリガーで
  起動する。
---

# close

## 目的
1日の作業内容を確定し、mainブランチへ統合する。当日ブランチ上の
変更（コミット済み・未コミット問わず）を当日デイリーノートの
「本日作成・更新したノート」セクションに反映した上でコミットし、
`main` へ ff-only マージする。

## 処理
1. `close_day.py` を実行する。

   ```
   python .claude/skills/vault/scripts/close_day.py
   ```

   Vault ルート以外から実行する場合や動作確認時は `--vault-root <path>`
   で対象を明示できる。

2. スクリプトは標準出力に1行のJSONを返す。`status` フィールドに応じて
   次のように解釈する。

   - `"ok"`: 正常に完了した。`updated_notes`（今日更新されたノート名の
     一覧）・`committed`（コミットを行ったか）・`pushed`（`origin` へ
     push できたか）を確認し、ユーザーに要約を報告する。
   - `"already_closed"`: `main` と当日ブランチの HEAD が既に一致して
     いる（既にclose済み）。追加の作業は不要である旨をユーザーに伝える。
   - `"error"`（`reason: "not_on_daily_branch"`）: 現在のブランチが
     `YYYY-MM-DD` 形式でない。当日ブランチへ切り替えてから再実行するよう
     案内する。
   - `"merge_failed"`: `git merge --ff-only` が失敗した（`main` が
     当日ブランチの分岐後に進んでいる等）。スクリプトは `--no-ff` や
     rebase 等で自動的に強制解決しない。`detail` の内容をそのまま
     ユーザーに提示し、`main` を先に取り込む（当日ブランチへ `main`
     を取り込んでから再実行する等）か手動でどう解決したいかの判断を
     仰ぐ。ユーザーの指示なしに競合解決を進めない。

3. いずれの場合も、終了コードが非ゼロ（`error`/`merge_failed`）のときは
   Vault の状態（現在のブランチ・`git status`）を変更前後で確認し、
   意図しない状態のまま放置しない。

## 備考
- 当日ブランチ自体は `close` 実行後も削除されない。
- 実装本体・詳細な除外規則は `scripts/close_day.py` を参照。
