---
name: today-close
description: |
  1日の作業終了時に実行する。タスク・議事録の締め忘れがないかを確認した上で、
  当日ブランチの変更をコミットしmainへマージする。「今日を終わる」
  「クローズして」「/close」等のトリガーで起動する。
---

# today-close

## 目的
`today-close`は単なる「1日の変更をコミットするスキル」ではない。タスク・
議事録の締め忘れがないかを確認し、締め忘れていればユーザーに見直しを促した
上で、当日ブランチ上の変更（コミット済み・未コミット問わず）を当日デイリー
ノートの「本日作成・更新したノート」セクションに反映してコミットし、
`main` へ ff-only マージする。

## 処理

1. `meeting-setup`スキルの実行フローを呼び出す（カレンダー同期〜project割当
   確認まで）。これにより、meeting-setupスキルが作成・更新するノートを
   `close_day.py`のコミット対象として拾わせる。Google Calendar MCP未接続や
   API呼び出し失敗等でmeeting-setupスキル側が失敗する場合がある。その場合でも、
   today-close本来の処理（コミット・マージ・ブランチ削除）は継続する。

2. `meeting_sync.py`の直近の実行結果のうち`needs_attendance_check`を
   確認する。開催日が本日より前（当日は含まない）で`attendance`が
   `1_scheduled`のまま未更新のノートが含まれていれば、該当ノート一覧（`note_path`・`title`）を提示し
   「実施済み/不参加」をユーザーにまとめて確認する。確認結果は
   `PYTHONUTF8=1 python .claude/skills/vault/scripts/meeting_sync.py --set-attendance <note_path> --attendance <1_scheduled|2_done|3_skip>`
   （実施済みなら`2_done`、不参加なら`3_skip`）で反映する。該当ノートが
   無ければ何もしない。

3. `meeting_sync.py`の直近の実行結果のうち`needs_task_check`を確認
   する。`attendance`確定済み（`2_done`/`3_skip`）だが未消化のアクション
   アイテムが残る議事録が含まれていれば、該当議事録一覧を提示し
   `meeting-followup`スキルの実行を促す。**この確認は処理を中断しない**。
   一覧提示後もそのまま後続の処理（`close_day.py`実行）へ進む。該当が
   無ければ何もしない。

   上記2・3は、開催確認・アクションアイテム消化の抜け漏れを防ぐための
   確認ステップである。

4. 続けて`today-touched`スキルの実行フローを呼び出す（`today_touched.py`を
   引数なしで実行する）。手順1〜3で生じたノートの新規作成・更新も含め、
   コミット直前の状態で更新ノート一覧を最新化するため、close_day.py実行の
   直前に置く。エラー（`not_on_daily_branch`）が返っても、以降の処理は
   巻き戻さず、close_day.py側の同種チェックに委ねる。

5. `close_day.py` を実行する。

   ```
   PYTHONUTF8=1 python .claude/skills/vault/scripts/close_day.py
   ```

   Vault ルート以外から実行する場合や動作確認時は `--vault-root <path>`
   で対象を明示できる。

6. スクリプトは標準出力に1行のJSONを返す。`status` フィールドに応じて
   次のように解釈する。

   - `"needs_task_review"`: タスクの日付・ステータス見直しが必要な状態。
     `tasks`フィールドに`{"note_path", "title"}`形式で該当タスク一覧が入る。
     **以降のコミット・マージ処理は一切実行されていない**（`close_day.py`
     自体がここで打ち切っている）。該当タスクは次の3条件のいずれかを満たす。
     1. `created_date`が本日かつ`start_date`未設定
     2. `start_date`が本日かつ`status`が`1_todo`
        （`3_pending`は意図的な保留状態であり、単純な未着手忘れとは異なるため対象外）
     3. `due_date`が本日かつ`status`が`4_done`/`5_cancel`以外

     ユーザーに該当タスク一覧を提示し、デイリーノートに埋め込まれた
     Baseビューから日付・ステータスを見直すよう促し、修正後に再度
     `today-close`スキルを実行するよう案内する。

   - `"ok"`: 正常に完了した。以下のフィールドを確認し、ユーザーに要約を報告する。

     | フィールド | 内容 |
     |------------|------|
     | `committed` | コミットを行ったか |
     | `branch_deleted` | `main`へのff-onlyマージ後、当日ブランチを`git branch -d`で削除した（マージ直後のため通常失敗しない。万一失敗した場合はスクリプトが異常終了しJSON自体が出力されない。そのため値は常に`true`固定であり、削除の成否を判定した結果ではない） |
     | `pushed` | `origin`へpushできたか |

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
   - `"post_merge_mismatch"`: `main` へのff-onlyマージ自体は成功したが、
     マージ直後の作業ツリーが `main` のコミット内容と完全に一致していない
     （`git status --porcelain`が非空）。`merge_failed`とは異なりマージ
     コマンド自体は失敗していない点に注意する。`detail`にporcelain形式の
     差分をそのまま含む。**このステータスではブランチ削除（`git branch -d`）
     ・`origin`へのpushのいずれも実行されていない**ため、当日ブランチは
     削除されずに残る。スクリプトはこの時点で既に`git checkout main`を
     実行済みであり、終了時点のカレントブランチは`main`である。ただし
     `git merge --ff-only`はコミットを一切変えないため、`main`と当日
     ブランチはこの時点で同一コミットを指しており、作業ツリーの状態を
     調査するうえで`main`上のままでも当日ブランチをcheckoutしても実質的な
     違いはない。`detail`の内容をそのままユーザーに提示し、`git status`で
     原因（意図しないファイル変更等、OneDrive同期によるファイルシステム
     レベルの復元等を含む）を調査するよう案内する。必要に応じて
     `git checkout <当日ブランチ名>`で明示的に切り替えても構わない。
     スクリプトはここでも自動修復しない。なお、Windows環境で
     `core.autocrlf=true`設定時、改行コード正規化のタイミングにより実害の
     ない誤検知が発生する可能性がある（既知の残存リスクとして受け入れ済み。
     コード側での緩和策は未実装）。

7. いずれの場合も、終了コードが非ゼロ（`needs_task_review`/`error`/
   `merge_failed`/`post_merge_mismatch`）のときはVault の状態（現在の
   ブランチ・`git status`）を変更前後で確認し、意図しない状態のまま
   放置しない。

## 備考
- `main` へのff-onlyマージ成功後、作業ツリーがマージ後のコミット内容と
  完全に一致していることを確認したうえで、当日ブランチは`git branch -d`
  （安全な削除。未マージなら失敗する）で自動的に削除される。不一致
  （`post_merge_mismatch`）があればブランチ削除・pushは行わない。
- 実装本体・詳細な除外規則は `scripts/close_day.py` を参照。
- 更新ノート一覧の再生成ロジックは`today-touched`スキル（`scripts/today_touched.py`）
  に切り出されている。呼び出し方の詳細は`today-touched/SKILL.md`の
  「today-closeスキルからの呼び出しについて」を参照。
- meeting-setupスキルの自動実行の詳細は`meeting-setup/SKILL.md`の
  「today-open/today-closeスキルからの呼び出しについて」を参照。
- `needs_attendance_check`・`needs_task_check`の検出ロジック自体は
  `meeting_sync.py`の`_scan_stale_and_pending`に実装済みで、
  `meeting-setup`スキルの実行フロー（手順1）呼び出し時に毎回結果へ含まれる。
  today-closeスキルが担うのは、この既存の検出結果を消費して
  ユーザーに確認・案内するオーケストレーション部分のみである。
- 設計上の経緯: 上記の開催確認・タスク化チェック（処理2・3）は、
  `meeting-setup`スキルから「開催確認」「タスク化」パターンが削除された
  ことに伴う、更新忘れ防止のための代替措置として導入された。
