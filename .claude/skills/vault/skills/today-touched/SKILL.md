---
name: today-touched
description: |
  日中いつでも「本日作成・更新したノート」一覧を再生成する。当日ブランチ上の
  git diffベースで更新ノートを検出し、当日デイリーノートに反映する。
  「今日の更新ノート一覧を更新して」「更新ノート一覧を最新化して」
  「/today-touched」等のトリガーで起動する。
---

# today-touched

## 目的
日中いつでも「本日作成・更新したノート」一覧を再生成できるようにする。
`today-close`スキルはclose処理（締め忘れ確認・コミット・mainへのマージ）の
一部としてのみこの一覧を反映するため、日中の途中経過を確認したい場合には
使えない。本スキルは更新ノート一覧の再生成のみを行い、締め忘れ確認・
コミット・マージは一切行わない。

## 処理

1. `.claude/skills/vault/scripts/today_touched.py`を引数なしで実行する。

   ```
   PYTHONUTF8=1 python .claude/skills/vault/scripts/today_touched.py
   ```

   Vault ルート以外から実行する場合や動作確認時は `--vault-root <path>`
   で対象を明示できる。

2. スクリプトは標準出力に1行のJSONを返す。`status`フィールドで結果を判定する。
   - `status: "ok"`: `updated_notes`フィールドに反映したノート名一覧が入る。
     件数・一覧をユーザーに要約して報告する。
   - `status: "error"`, `reason: "not_on_daily_branch"`: 現在のブランチが
     `YYYY-MM-DD`形式でない。当日ブランチへ切り替えてから再実行するよう
     案内する。何も書き込まれていない。

## 補足
- 冪等スクリプトであり、実行のたびに当日ブランチ上のgit diff（`main`との
  分岐点以降のコミット済み変更＋未コミット変更）から一覧を再計算する。
- `today-close`実行後にさらに同日中の更新が必要になり、日中に`close`（`main`
  へのff-onlyマージ）が複数回挟まる場合、`main`が当日ブランチに追いつくたびに
  差分基準（`merge-base(main, HEAD)`）が前進する。そのため、直近の差分だけを
  見ると、それより前に記録済みだった更新ノートが一覧から消えて見える。
  これを防ぐため、新しい差分結果は「今回の差分」だけで置き換えるのではなく、
  既存のマーカーブロックに既に記録済みのノート（実在するもののみ）と**和集合**
  してから書き込む。実装は`_merge_with_existing_entries`を参照。
- 更新ノート一覧は`type`別（project/meeting/task/knowhow/webclip/other）に
  グルーピングして当日デイリーノートの`UPDATED_NOTES_START`/
  `UPDATED_NOTES_END`区間へ書き込む。当日ノート自身・`80_Templates/`・
  `.claude/`配下・非`.md`・実在しないファイル（削除されたノート）は除外する
  （和集合対象の既存記録も含め、実在しないノートは除外される）。
- 実装本体・詳細な除外規則は`scripts/today_touched.py`を参照。

## today-closeスキルからの呼び出しについて

`today-close`スキルからも本スキルの実行フローが自動的に呼び出される
（手順1〜3のmeeting-setup実行・meeting_sync確認より後、手順5の
`close_day.py`実行より前）。手順1〜3で生じたノートの新規作成・
frontmatter変更も含め、コミット直前の状態で更新ノート一覧を最新化する
ためにこの位置に置かれている。`today_touched.py`は`close_day.py`と
import/subprocess関係を持たない完全に独立したスクリプトであり、
毎回全体を再計算する冪等スクリプトである。`status: "error"`
（`not_on_daily_branch`）が返っても、today-close本来の処理は巻き戻さず、
`close_day.py`側の同種チェックに委ねてそのまま後続処理へ進む。
