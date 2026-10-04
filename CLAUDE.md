# Vault ルールブック

Obsidian を「第2の脳」として使う Vault。プロジェクト／タスク管理、ナレッジ、資料作成、情報整理、調べもののまとめを蓄積・活用する。本文・ファイル名は日本語。

## フォルダ
フォルダ名は番号付き（並び順の固定のため）。パスは必ず番号付きの名前で指定する。

| フォルダ | 用途 |
|---|---|
| `00_inbox/` | Obsidian で新しく作ったノートの一時置き場（Obsidian の新規ノートの作成先）。振り分けは `daily-end` が提案する |
| `10_projects/<名前>/` | プロジェクトノート本体（`<名前>.md`）＋そのプロジェクトの資料 |
| `20_tasks/` | タスク（1タスク1ノート、フラット） |
| `30_knowledge/` `40_research/` | 知識、調べもの（フラット。`project` で任意に紐づけ） |
| `50_documents/` | プロジェクトに属さない資料 |
| `60_daily/` | デイリーノート（その日のダッシュボード） |
| `70_meetings/` | 議事録（フラット。`project` で任意に紐づけ）。作るときは、このフォルダを右クリックして「新規ノート」で作り、テンプレートを挿入する |
| `90_system/` | 仕組み。`templates/`（テンプレート）、`bases/`（一覧）、`attachments/`（貼り付けた画像などの添付。Obsidian の添付の保存先）、`setup.md`（手順書） |

アーカイブ用のフォルダは置かない。完了したプロジェクト・タスクは `status: done` で管理し、元の場所に置いたままにする（Bases は `status` で表示を分ける）。

## プロパティ
- 共通: `type`（project / task / knowledge / research / doc / meeting / daily）、`created`（日付型）、`tags`
- project: `status`（active / on-hold / done）、`start`、`due`
- task: `status`（todo / doing / pending / done）、`project`（`"[[プロジェクト名]]"`）、`start`、`due`、`completed`、`memo`（自由記入。`pending` の理由など）
  - `start` / `due` は、作るときに指定がなければ当日にする（テンプレート・`task-add`・`meeting-followup`・`daily-end` のメモからのタスクで共通）。当日開始の todo はすぐ「遅れ」に出るが、気づけるようにするための意図どおり
  - 完了したら `status: done` と `completed` を必ず入れる（デイリーのダッシュボードが参照する）
  - `pending` は待ち・保留。中止・不要になったタスクは、確認のうえ削除する（`cancelled` は使わない）
  - 任意: `meeting`（`"[[議事録名]]"`）。議事録のアクションアイテムから `meeting-followup` で作ったタスクだけが持つ
- meeting: `date`（開催日）、`project`、`attendees`（リスト）、`source`（取り込み元の URL など）
  - アクションアイテムは `- [ ] 内容 @担当 期限:YYYY-MM-DD`（担当と期限は省略可。自分の担当は `@自分` か省略）。タスクにした行には、行末に ` → [[タスク名]]` が付く（`meeting-followup`）
- research: `source`（出典 URL）
- doc: `status`（draft / done）
- knowledge / research には `status` を付けない。
- doc / knowledge / research: 任意で `project`
- 日付プロパティ（created / start / due / completed / date）は `.obsidian/types.json` で日付型に固定。値は `YYYY-MM-DD`。

## タグの規約
- knowledge / research / doc には、Claude が分野のタグを1〜3個付ける（`knowledge-add`、`daily-end` のメモの振り分け）。ユーザーへの確認は不要で、新しく作ったタグは報告で知らせる。
- 既存のタグを優先し、同じ分野に別名のタグを作らない（表記をそろえる）。タグはプロジェクトをまたいだ話題で探すためのもので、プロジェクト名や種類（`type`）はタグにしない。
- project / task / daily / meeting は空でよい。スキルの解説ノート（`90_system/skill-docs/`）は `skill`。

## 命名
- ファイル名は日本語。日付プレフィックス（`YYYY-MM-DD_`）は daily・research・meeting のみ（議事録は `YYYY-MM-DD_会議名.md`）。
- 新規ノートは `90_system/templates/` の該当テンプレートに従う。

## メモの振り分け
- 短いメモ・URL・思いつきは、まずデイリーの「今日のメモ」に書く。ノートとして育てるものを Obsidian で新しく作ると、`00_inbox/` に入る。
- `00_inbox/` に残ったノートは、`daily-end` が振り分け案を出す（移動は承認後）。
- 「今日のメモ」も、`daily-end` が項目ごとに振り分け案（knowledge / research / タスク / 残す）を出す。承認後にノートを作り、元の行の末尾に ` → [[ノート名]]` を付ける（印のある行は処理済み）。過去のデイリーのメモは対象外。
- 振り分けは、内容に応じた移動先を提案して**承認後に実行**する（固定の移動先はない。迷えば聞く）。
- 資料はプロジェクトに属するなら `10_projects/<名前>/`、属さなければ `50_documents/`。
- プロジェクトノートの「知識・資料」（`project-materials.base`）には、`project` が一致する knowledge / research / doc と、プロジェクトのフォルダの中のファイル（PDF なども含む）が出る。
- 会話で調べた内容を残すときは `knowledge-add` スキルを使う（出典のある調べものは `40_research/`、自分の理解・手順は `30_knowledge/`）。
- 貼り付けた画像などの添付は `90_system/attachments/` に入る（Obsidian の設定）。

## デイリーノート
- `60_daily/YYYY-MM-DD.md`。作成は `daily-start` スキル（`.claude/skills/daily-start/daily-start.bat` から起動）。1日の終わりは `daily-end` スキル（振り返りの下書き、未完了タスクの整理案、今日のメモ・インボックスの振り分け案。承認後に更新する）。ブランチは使わない（ノートは Git で管理しない。「Git」の節）。
- フック（`.claude/settings.json`、本体は `.claude/hooks/vault_hooks.py`）:
  - セッション開始時: 今日のガントを更新し、短い状況（デイリーノートの有無、「遅れ」「今日が期限」の件数、インボックスの件数）を Claude に渡す。
  - Claude が `20_tasks/*.md` を編集した直後: ガントを更新する。デイリーノートがなければ、何も言わずに飛ばす。Obsidian での編集では動かない（次のセッション開始時か `gantt-update` で反映）。
- ガントだけの更新は `gantt-update` スキル（既存のノートのガントだけを再生成する。ノートの作成や Obsidian の起動はしない）。
- セクションの順序: 進行中のプロジェクト → 今日の会議 → タスク → ガントチャート → 今日のメモ → 振り返り（`daily-end` が書く）。「今日の予定」「今日の実績」は置かない。
- タスク・プロジェクト・今日の会議（`meetings.base`）は Bases の埋め込みで表示する。ガントは `.claude/skills/daily-start/daily_start.py` が `<!-- gantt:start -->` と `<!-- gantt:end -->` の間を再生成する。このマーカーは消さない。
- タスク本文のチェックリスト（`- [ ] 項目名 期限:YYYY-MM-DD`。期限は任意）は、ガントにマイルストーン（◇）として、そのタスクの表示開始日の位置に出る。期限が基準日より前の未完了は赤、完了（`- [x]`）はグレー。期限は名前の後ろに付くだけで位置は変わらない。分解は `task-split` スキル。
- 「遅れ」の定義（Bases とガントで共通。変えるときは `daily-tasks.base` と `daily_start.py` の `is_late` の両方を直す）: `todo` で `start` が基準日以前、`doing` / `pending` で `due` が基準日より前。
- ダッシュボードのタスクは1つの表を区分でグルーピングする: 1 遅れ → 2 今日が期限 → 3 進行中 → 4 保留 → 5 今日完了（1つのタスクは最初に該当した区分にだけ出る）。
- ガントの表示期間は、ノート日付〜90日後（`PAST_DAYS` / `FUTURE_DAYS`）。はみ出す分は端で切り `←` `→` を付ける。遅れは赤、`pending` は名前の先頭に `⏸`。未完了で `due` が基準日より前のタスクと、`start` が基準日より前の `todo` は、ガントに出さない（ダッシュボードの「遅れ」で見る）。完了済みは、その日に完了したものだけ。過去のデイリーノートは、ガントがその日のスナップショットとして固定される（ステータス基準の表示は今の状態になる）。

## 安全
- 削除・移動・外部送信は実行前に確認する。削除や上書きの前に対象の中身を確認する。
- 秘密情報（トークン、キー）をノートやコミットに含めない。
- 安全網は Obsidian のコアプラグイン「ファイル復元」（5分ごとのスナップショット、7日保存）。ノートの Git の履歴はない。

## Git（配布用）
- Git は、この環境（スキル・フック・設定・テンプレート・Bases・ルールブック・手順書）を他の PC で使うための配布用リポジトリにだけ使う。ノートは追跡しない（`.gitignore` は配布対象だけを許可するホワイトリスト）。ブランチは `main` だけで、作業用のブランチは切らない。
- コミットと push はユーザーが手で行う。Claude はコミット・push をしない（頼まれたときだけ、内容を確認してから行う）。
- 配布対象のファイルには、個人のパス・名前・メールアドレス・秘密情報を書かない。個人の要素は `PERSONAL.md`（追跡しない）に書く。
- `.git` は Vault 直下の1行のファイルで、実体は OneDrive の外にある（場所は `PERSONAL.md`）。消したり書き換えたりしない。

## 個人の設定
@PERSONAL.md
