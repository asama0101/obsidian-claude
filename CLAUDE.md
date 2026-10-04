<!--
保守者向けのメモ（HTML のコメントは Claude には読み込まれない）
- このファイルは Claude が毎回読む規約だけを書く。人向けの説明・図解は README.md、環境の作り方は 90_system/setup.md。
- 一部のフォルダにだけ効く細則は .claude/rules/（paths 指定。該当のファイルを読み書きするときだけ読み込まれる）。手順はスキル（.claude/skills/）。
- 足すときは「消すと Claude が間違えるか」で判断し、目安 200 行以内に保つ。
-->
# Vault ルールブック

Obsidian を「第2の脳」として使う Vault。タスクノートに経緯を書きため、1日の締め（`daily-end`）で知識を棚卸しする。棚卸しで集めた判断・失敗・知見・進捗（`80_context/`）は、Claude の作業のインプットにする。

## フォルダ
番号付きの名前で指定する（`40` は空き番号）。アーカイブ用のフォルダはない。完了・中止したものは `status` を変えて、元の場所に置いたままにする。

| フォルダ | 入れるもの |
|---|---|
| `00_inbox/` | 振り分け前のタスク・grilling-html のセッション・ダウンロードした資料・会議の文字起こし |
| `10_projects/<名前>/` | プロジェクトノート（`<名前>.md`）と、そのプロジェクトの資料 |
| `20_tasks/` | 振り分け済みのタスク（1タスク1ノート、フラット） |
| `30_knowledge/` | 人が読む知識（解説・手順・ノウハウ・出典のある調べもの。フラット） |
| `50_documents/` | プロジェクトに属さない資料 |
| `60_daily/` | デイリーノート `YYYY-MM-DD.md` |
| `70_meetings/` | 議事録 `YYYY-MM-DD_会議名.md`（フラット） |
| `80_context/` | Claude のインプット（`技術知見.md`・`判断記録.md`・`失敗記録.md`・`進捗ログ.md`。`_index.md`・`_rules.md` は自動生成） |
| `90_system/` | `templates/`・`bases/`・`attachments/`（貼り付けた添付）・`skill-docs/`（スキルの解説）・`setup.md` |

## ノートの書き方
- 本文とファイル名は日本語。日付のプレフィックスは daily と meeting だけに付ける。
- 新しいノートは `90_system/templates/` の該当テンプレートから作る。
- 共通のプロパティ: `type`（project / task / knowledge / doc / meeting / daily）・`created`。種類ごとのプロパティは、`.claude/rules/` の該当ファイルとテンプレートに従う。
- タグ（`tags`）は使わない。分類はフォルダ・`type`・`project` で行う。
- 日付のプロパティ（`created` / `start` / `due` / `completed` / `date`）の値は `YYYY-MM-DD`（`.obsidian/types.json` で日付型に固定してある）。
- プロジェクトへの紐づけは `project: "[[プロジェクト名]]"`。
- タスクの `status` の値: `idea` → `todo` → `in_progress` → `done`。止まっているときは `waiting`（保留）か `requested`（他の人に依頼中）、当面やらないときは `shelved`、中止は `cancelled`。

## Claude のインプット（80_context）
- 作業の前に、下で読み込んでいる `_rules.md`（再発防止のルール）を守り、`_index.md`（索引）から関係する件を開いて読む。
- 会話の途中で判断や失敗が起きたら、その場で「判断記録／失敗記録に残しますか」と一言提案する。承認されたら `knowledge-harvest` の手順で1件だけ記録する。
- `_index.md` と `_rules.md` は手で編集しない（`harvest.py index` が作り直す）。
- 自動メモリー（Vault の外）には Claude の作業の癖だけを置く。ユーザーの仕事の判断・失敗・知見・進捗は `80_context/` に置く。

## 自動で動くもの（フック）
- `.claude/settings.json` に登録し、本体は `.claude/hooks/vault_hooks.py`。
- セッション開始時: 今日のガントを更新し、状況（遅れ・今日が期限・idea・インボックスの件数）を Claude に渡す。
- Claude が `20_tasks/*.md` か `00_inbox/*.md` を編集した直後: ガントを自動で更新する。手で再生成しなくてよい。
- Obsidian での編集では、ガントは更新されない。反映するときは `gantt-update` を使う。

## 安全
- 削除・移動・外部への送信は、実行前に確認する。削除や上書きの前に、対象の中身を読む。
- IMPORTANT: ノートは Git で追跡していない。消したノートを戻せるのは Obsidian の「ファイル復元」（7日分）だけ。タスクは削除せず、中止なら `status: cancelled` にする。
- 秘密情報（トークン、キー）をノートやコミットに含めない。

## Git（配布用）
- Git は、この環境（スキル・フック・設定・テンプレート・Bases・ルールブック・手順書）を他の PC に配るためだけに使う。`.gitignore` は配布対象だけを許可するホワイトリスト。配布対象を足すときは `!` の行を足す。
- ブランチは `main` だけ。作業用のブランチは切らない。
- コミットと push はユーザーが手で行う。Claude は頼まれたときだけ、内容を確認してから行う。
- 配布対象のファイルには、個人のパス・名前・メールアドレス・秘密情報を書かない。個人の要素は `PERSONAL.md`（追跡しない。更新は `personal-setup`）に書く。
- Vault 直下の `.git` は、OneDrive の外にある実体を指す1行のファイル。消したり書き換えたりしない。

## テスト
スクリプト（`.claude/skills/*/` の `.py`・`.claude/hooks/`）を変えたら、該当するテストを実行する。標準ライブラリの unittest だけで動く。

```
python -m unittest discover -s .claude/skills/daily-start/tests
python -m unittest discover -s .claude/skills/meeting-import/tests
python -m unittest discover -s .claude/skills/knowledge-harvest/tests
python -m unittest discover -s .claude/hooks/tests
```

## 個人の設定
@PERSONAL.md

## 読み込むインプット
@80_context/_rules.md
@80_context/_index.md
