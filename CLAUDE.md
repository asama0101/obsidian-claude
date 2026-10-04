# Vault ルールブック

Obsidian を「第2の脳」として使う Vault。入口はタスクの1本にし、タスクノートに経緯を書きため、1日の締めで知識を棚卸しして集約する。集めた判断・失敗・知見・進捗は、Claude Code の作業のインプットにする。本文・ファイル名は日本語。

## フォルダ
フォルダ名は番号付き（並び順の固定のため）。パスは必ず番号付きの名前で指定する。

| フォルダ | 用途 |
|---|---|
| `00_inbox/` | 振り分け前のタスク、grilling-html のセッション、ダウンロードした資料・文字起こしの置き場（Obsidian の新規ノートの作成先）。振り分けは `daily-end` が提案する |
| `10_projects/<名前>/` | プロジェクトノート本体（`<名前>.md`）＋そのプロジェクトの資料 |
| `20_tasks/` | 振り分け済みのタスク（1タスク1ノート、フラット） |
| `30_knowledge/` `40_research/` | 人が読む知識、調べもの（フラット。`project` で任意に紐づけ） |
| `50_documents/` | プロジェクトに属さない資料 |
| `60_daily/` | デイリーノート（その日のダッシュボード） |
| `70_meetings/` | 議事録（フラット。`project` で任意に紐づけ） |
| `80_context/` | Claude Code が読むインプット。`knowledge/`（技術知見）・`decisions/`（判断記録）・`mistakes/`（失敗記録）・`projects/`（進捗ログ）。`_index.md` と `_rules.md` は自動生成 |
| `90_system/` | 仕組み。`templates/`（テンプレート）、`bases/`（一覧）、`attachments/`（貼り付けた画像・会議の文字起こしなどの添付）、`skill-docs/`（スキルの解説）、`setup.md`（手順書） |

アーカイブ用のフォルダは置かない。完了・中止したものは `status` で管理し、元の場所に置いたままにする（Bases は `status` で表示を分ける）。

## 1日の流れ
- 朝: `daily-start` がデイリーノートを作り、ガントを更新して Obsidian で開く。Microsoft 365 コネクタが使えるときは、今日の会議の議事録の枠も作る（`meeting-import`）。
- 日中:
  - 思いついたら、すぐタスクにする（Obsidian: `Ctrl+N` → `Ctrl+Shift+N` でタスクのテンプレート。Claude: `task-add`）。`00_inbox/` に `idea` で入る。
  - 進めた経緯は、タスクノートの「経緯」に書く。大きいタスクは「チェックリスト」に分ける（`task-split`）。任せたいタスクは `task-run`。
  - 電話・口頭の突発メモは、デイリーの「今日のメモ」に書く。
  - 会議の後は `meeting-import` で議事録を仕上げ、アクションアイテムをタスクにする。
- 締め: `daily-end` が、振り返り・未完了と idea の整理・インボックスの振り分け・知識の棚卸し（`knowledge-harvest`）・議事録の取り込み残りを、1回の承認でまとめて行う。

## プロパティ
- 共通: `type`（project / task / knowledge / research / doc / meeting / daily / decision / mistake / progress）、`created`（日付型）、`tags`
- project: `status`（active / on-hold / done）、`start`、`due`
- task: `status`、`project`（`"[[プロジェクト名]]"`）、`start`、`due`、`completed`、`memo`（自由記入。保留や依頼の理由など）
  - `status` の値: `idea`（思いつき。やるかは未定）→ `todo`（やると決めたが未着手）→ `in_progress`（作業中）→ `done`（完了）。ほかに `waiting`（保留。自分の都合や前提待ちで止めている）、`requested`（依頼中。他の人に頼んで返事・成果を待っている）、`shelved`（塩漬け。当面やらないが捨てない）、`cancelled`（中止）。ダッシュボードの区分名は日本語で表示する
  - `idea` は `start` / `due` を空にする。`todo` 以降にするときに日付を入れる（指定がなければ当日。当日開始の todo はすぐ「遅れ」に出るが、気づけるようにするための意図どおり）
  - 完了したら `status: done` と `completed` を必ず入れる（デイリーのダッシュボードが参照する）
  - 中止・不要になったタスクは削除せず `cancelled` にする
  - 任意: `meeting`（`"[[議事録名]]"`）。`meeting-import` が議事録のアクションアイテムから作ったタスクだけが持つ
- meeting: `date`（開催日）、`project`、`attendees`（リスト）、`source`（取り込み元。会議の URL・ID や元のファイル名）
  - アクションアイテムは `- [ ] 内容 期限:YYYY-MM-DD`（期限は省略可）。担当は書かない（他の人に頼んだものは、タスクの `requested` で表す）。タスクにした行には、行末に ` → [[タスク名]]` が付く
- research: `source`（出典 URL）
- doc: `status`（draft / done）
- decision / mistake / 80_context の knowledge: `date`（判断・失敗・知見の日）
- progress（進捗ログ）: `project`
- knowledge / research / decision / mistake / progress には `status` を付けない。
- doc / knowledge / research / decision / mistake: 任意で `project`
- 日付プロパティ（created / start / due / completed / date）は `.obsidian/types.json` で日付型に固定。値は `YYYY-MM-DD`。

## タスクノート
- 目的は原則としてタイトル（ファイル名）で示す。タイトルから目的が読み取れないときは、Claude が名前の変更を促す（`task-add` で作るとき、`daily-end` の振り分けのとき）。
- 本文の見出し: `## 完了条件`（`task-run` の grilling で埋まる。任意）/ `## チェックリスト`（`- [ ] 項目 期限:YYYY-MM-DD`）/ `## 経緯`（`### YYYY-MM-DD` の見出しで日ごとに追記）/ `## 成果`（成果物と、棚卸しで作ったノートへのリンク）。
- 新しいタスクは `00_inbox/` に `idea` で作る。`daily-end` の振り分けで `project` を決めて `20_tasks/` へ移す（フォルダは振り分け済みか、状態はやると決めたかを表し、別々に扱う）。会議で決まったタスクは、`meeting-import` が `20_tasks/` に直接作る。

## タグの規約
- knowledge / research / doc / decision / mistake / 80_context の knowledge には、Claude が分野のタグを1〜3個付ける（`knowledge-harvest`）。ユーザーへの確認は不要で、新しく作ったタグは報告で知らせる。
- 既存のタグを優先し、同じ分野に別名のタグを作らない（表記をそろえる）。タグはプロジェクトをまたいだ話題で探すためのもので、プロジェクト名や種類（`type`）はタグにしない。
- project / task / daily / meeting / progress は空でよい。スキルの解説ノート（`90_system/skill-docs/`）は `skill`。

## 命名
- ファイル名は日本語。日付プレフィックス（`YYYY-MM-DD_`）は daily・research・meeting のみ（議事録は `YYYY-MM-DD_会議名.md`）。進捗ログは `80_context/projects/<プロジェクト名> 進捗ログ.md`。
- grilling-html のセッションは `00_inbox/<日時>_grilling_<テーマ>/`。
- 新規ノートは `90_system/templates/` の該当テンプレートに従う（`80_context` は `context-knowledge.md`・`decision.md`・`mistake.md`・`progress.md`）。

## インボックスと振り分け
- `00_inbox/` に入るもの: 新しいタスク、grilling-html のセッション、ダウンロードした資料、会議の文字起こし。
- 振り分けは `daily-end` が案を出し、**承認後に実行**する（固定の移動先はない。迷えば聞く）。タスクは `20_tasks/` へ、セッションと資料はプロジェクトに属すれば `10_projects/<名前>/`、属さなければ `50_documents/` へ。文字起こしは `meeting-import` で議事録にする。
- 「今日のメモ」（電話・口頭の突発メモ）は、締めの棚卸しで、タスク・知識などに振り分ける。元の行の末尾に ` → [[ノート名]]` を付ける（印のある行は処理済み）。過去のデイリーのメモは対象外。
- プロジェクトノートの「知識・資料」（`project-materials.base`）には、`project` が一致する knowledge / research / doc / decision / mistake と、プロジェクトのフォルダの中のファイル（PDF なども含む）が出る。
- 貼り付けた画像などの添付は `90_system/attachments/` に入る（Obsidian の設定）。

## 棚卸しと Claude のインプット
- `knowledge-harvest`（`daily-end` から呼ぶ。単独でも使える）が、今日のメモと、前回の棚卸し以降に更新したタスクの「経緯」（ファイルの更新日時で判定）から、次を作るか既存に追記する。取り出した行の末尾に ` → [[ノート]]` を付け、タスクの「成果」にもリンクを足す。
  - 人が読むもの: knowledge（`30_knowledge/`）・research（`40_research/`）・doc
  - Claude のインプット（`80_context/`）: 技術知見（Claude の作業に効く短く指示的な知見）・判断記録（背景 / 選択肢 / 決定 / 理由 / 影響 / 見直す条件）・失敗記録（何が起きたか / 原因 / 対策 / 再発防止のルール）・進捗ログ（プロジェクトごと。先頭の「現在の要約」を書き換え、日付の記録を新しい順に追記。基本的に Claude が読む専用）
- 棚卸しのたびに `80_context/_index.md`（索引）と `80_context/_rules.md`（再発防止のルール）が自動生成され、下の「Claude のインプット」で常に読み込まれる。詳しい内容は、索引から必要なノートを開いて読む。
- 会話の途中で判断や失敗が起きたら、Claude はその場で「判断記録／失敗記録に残しますか」と一言提案する（承認されたら `knowledge-harvest` の手順で1件だけ記録する）。
- Claude Code の自動メモリー（Vault の外）には、Claude の作業の癖（ツールの使い方・手順の守り方）だけを置く。ユーザーの仕事の判断・失敗・知見・進捗は `80_context/` に置く。

## 議事録
- `meeting-import` が、会議の情報から議事録（`70_meetings/`）を作り、アクションアイテムを承認のうえタスク（`todo` か `requested`）にする。
- 取り込み元: Microsoft 365 コネクタ（Anthropic 公式。テナントの管理者の同意が得られてから。読み取りだけ）、`00_inbox/` に置いた文字起こし（Teams の要約からダウンロードした `.vtt` / `.docx`）、議事録や会話に貼り付けた要約・メモ。
- 手で作るときは、`70_meetings/` を右クリックして「新規ノート」で作り、テンプレートを挿入する。

## タスクの実行
- `task-run` が、grilling-html で「完了条件」を決め、承認後にサブエージェントがバックグラウンドで実行する。結果は「経緯」と「成果」に記録され、ユーザーが確認して OK なら `done`、NG なら差し戻して再実行する。
- 任せるのは Vault の中で完結する作業（調べもの・下書き・整理）だけ。外部への送信・公開、Vault の外の変更はしない。

## デイリーノート
- `60_daily/YYYY-MM-DD.md`。作成は `daily-start` スキル（`.claude/skills/daily-start/daily-start.bat` から起動）。1日の終わりは `daily-end` スキル。
- セクションの順序: 進行中のプロジェクト → 今日の会議 → タスク → アイデア・インボックス（`idea` と、`00_inbox/` にある未完了のタスク）→ ガントチャート → 今日のメモ → 振り返り（`daily-end` が書く）。「今日の予定」「今日の実績」は置かない。
- タスク・プロジェクト・今日の会議（`meetings.base`）は Bases の埋め込みで表示する。ガントは `.claude/skills/daily-start/daily_start.py` が `<!-- gantt:start -->` と `<!-- gantt:end -->` の間を再生成する。このマーカーは消さない。
- ガントだけの更新は `gantt-update` スキル（既存のノートのガントだけを再生成する。ノートの作成や Obsidian の起動はしない）。
- タスク本文のチェックリスト（`- [ ] 項目名 期限:YYYY-MM-DD`。期限は任意）は、ガントにマイルストーン（◇）として、そのタスクの表示開始日の位置に出る。期限が基準日より前の未完了は赤、完了（`- [x]`）はグレー。期限は名前の後ろに付くだけで位置は変わらない。分解は `task-split` スキル。
- 「遅れ」の定義（Bases とガントで共通。変えるときは `daily-tasks.base` と `daily_start.py` の `is_late` の両方を直す）: `todo` で `start` が基準日以前、`in_progress` / `waiting` / `requested` で `due` が基準日より前。
- ダッシュボードのタスクは1つの表を区分でグルーピングする: 1 遅れ → 2 今日が期限 → 3 作業中 → 4 依頼中 → 5 保留 → 6 今日完了（1つのタスクは最初に該当した区分にだけ出る）。`idea` / `shelved` / `cancelled` はこの表にもガントにも出さない（`idea` は「アイデア・インボックス」、`shelved` / `cancelled` は `tasks.base` で見る）。
- ダッシュボードとガントは、`20_tasks/` と `00_inbox/` の両方（どちらも直下）のタスクを対象にする。
- ガントの表示期間は、ノート日付〜90日後（`PAST_DAYS` / `FUTURE_DAYS`）。はみ出す分は端で切り `←` `→` を付ける。遅れは赤、`in_progress` は強調、`waiting` は名前の先頭に `⏸`、`requested` は `✉`。未完了で `due` が基準日より前のタスクと、`start` が基準日より前の `todo` は、ガントに出さない（ダッシュボードの「遅れ」で見る）。完了済みは、その日に完了したものだけ。過去のデイリーノートは、ガントがその日のスナップショットとして固定される（ステータス基準の表示は今の状態になる）。

## フックと通知
`.claude/settings.json` に登録。本体は `.claude/hooks/vault_hooks.py`（通知は `notify.py`）。
- セッション開始時: 今日のガントを更新し、短い状況（デイリーノートの有無、「遅れ」「今日が期限」「idea」の件数、インボックスのタスクとその他の件数）を Claude に渡す。
- Claude がファイルを編集した直後: 編集したファイルを記録する。`20_tasks/*.md` か `00_inbox/*.md` ならガントも更新する（デイリーノートがなければ飛ばす。Obsidian での編集では動かない。次のセッション開始時か `gantt-update` で反映）。
- Claude の応答が終わるたび: Windows の通知で「完了」と、そのターンで作成・編集したファイルを知らせる（クリックで最初のファイルを Obsidian で開く）。
- 許可や入力を待っているとき: Windows の通知で「確認待ち」を知らせる。

## 安全
- 削除・移動・外部送信は実行前に確認する。削除や上書きの前に対象の中身を確認する。
- 秘密情報（トークン、キー）をノートやコミットに含めない。
- 安全網は Obsidian のコアプラグイン「ファイル復元」（5分ごとのスナップショット、7日保存）。ノートの Git の履歴はない。

## Git（配布用）
- Git は、この環境（スキル・フック・設定・テンプレート・Bases・ルールブック・手順書）を他の PC で使うための配布用リポジトリにだけ使う。ノートは追跡しない（`.gitignore` は配布対象だけを許可するホワイトリスト）。ブランチは `main` だけで、作業用のブランチは切らない。
- コミットと push はユーザーが手で行う。Claude はコミット・push をしない（頼まれたときだけ、内容を確認してから行う）。
- 配布対象のファイルには、個人のパス・名前・メールアドレス・秘密情報を書かない。個人の要素は `PERSONAL.md`（追跡しない。作成・更新は `personal-setup`）に書く。
- `.git` は Vault 直下の1行のファイルで、実体は OneDrive の外にある（場所は `PERSONAL.md`）。消したり書き換えたりしない。

## 個人の設定
@PERSONAL.md

## Claude のインプット
@80_context/_rules.md
@80_context/_index.md
