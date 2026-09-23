# CLAUDE.md（このリポジトリ固有の運用ルール）

このファイルは`obsidian`リポジトリ（Obsidian Vault + Claude Codeプラグイン`vault`のモノレポ）でClaude Codeが作業する際の運用ルールを定める。
ユーザーのグローバル`~/.claude/CLAUDE.md`を上書きするものではなく、本リポジトリ固有の追加ルールとして併読する。
全体像・フォルダ構成・スキル一覧は[README.md](README.md)を参照。

## ブランチ運用

- 作業は必ず当日ブランチ（`YYYY-MM-DD`形式）上で行う。`main`への直接コミット・直接編集は行わない。
- `main`上でのファイル変更は`branch-guard.sh`フックがブロックする。ブロックされたら回避策を探さず、ユーザーに当日ブランチへの切り替えを確認する。
- 当日ブランチの作成・切り替えは`today-open`スキル（`today_start.py`）が担う。1日の作業開始時にまず`today-open`を実行する。
- 1日の作業終了時は`today-close`スキル（`close_day.py`）を実行する。当日ブランチの変更をコミットし、`main`へ`git merge --ff-only`でマージする。`--no-ff`やrebaseによる強制解決は行わない。
- マージ失敗（`merge_failed`）時は自動解決せず、`main`を当日ブランチへ取り込むか等の対応方針をユーザーに確認してから進める。

## 新スクリプト実装時のテスト方針

- TDD（テストを先に書き、失敗を確認してから実装する）を基本とする。実際に「Add failing tests for `<script>`」→「Implement `<script>`」の順でコミットする運用実績がある（例: `project_create.py`）。
- テストは`.claude/skills/vault/scripts/tests/`に`test_<script>.py`として追加する。
- テスト実行コマンド:
  ```bash
  cd .claude/skills/vault/scripts
  PYTHONUTF8=1 .venv/Scripts/python -m pytest
  ```
- 既存230件のテストを壊さないことを確認してからコミットする。
- スクリプト本体（`scripts/*.py`）は引き続き標準ライブラリのみで実装し、外部パッケージに依存しない。テストの実行にはpytestを使うが、これは`.claude/skills/vault/scripts/.venv/`に閉じたテスト専用の開発依存であり、`.gitignore`で除外している。スクリプト本体の依存方針を変える場合はユーザーに確認する。

## アーキテクチャ方針: 機械的処理はPython、人間判断はClaude確認

このリポジトリの全スキルに共通する設計原則。

- **決定的・機械的に処理できる作業**（ファイル名サニタイズ、ノートのfrontmatter更新、フォルダ作成、git操作等）は`scripts/*.py`が担う。`vault_lib.py`の共通関数を極力再利用する。
- **人間の判断が要る作業**（プロジェクトへの紐付け確認、カテゴリタグの確定、コンフリクト解決方針の決定等）は、スクリプト側で自動推測して確定させない。Claudeが選択肢をユーザーに提示し、確認済みの値をスクリプトへ引数として渡す。
- 良い実例: `task-add`スキルはCLI入力からタスク候補を抽出する処理と、保存前にプロジェクト紐付けをユーザーに確認する処理を分離している。`meeting-setup`スキルの新規作成ノート（`fuzzy_project_match`による自動推定を含む）も同様に、Claudeがユーザーへまとめて確認してから`--set-project`で反映する。
- 新しいスキル・スクリプトを追加する際も、この分離を維持する。「スクリプトが黙って推測して確定させる」実装は避ける。

## Vaultの手動編集について

ユーザーがVault内のノート・フォルダを手動で移動・削除するのは通常運用である。スキル実行時にVaultの状態が想定と異なっていても、それ自体を見慣れない変更として調査・確認する必要はない。ユーザーへの確認が必要なのは、スキル自身の処理（今回の実行で生じた変更）に関する判断のみである。

## スキル追加時の手順

`project-add`スキル追加時の実績（当時の旧名称`project`でのコミット履歴: 「Add failing tests」→「Implement `*_create.py`」→「Add project skill: SKILL.md作成」）を土台にした手順。現行のスキル命名規則は`<name>-add`等の動詞的サフィックス付き（例: `task-add`, `meeting-followup`）。

1. `scripts/tests/test_<name>_create.py`（あるいは相当のテスト）を先に書き、失敗することを確認する（RED）。
2. `scripts/<name>_*.py`を実装し、テストを通す（GREEN）。標準出力は1行のJSON（`status`フィールドで結果を判定できる形式）で返す既存スクリプトの慣例に合わせる。
3. `skills/<name>/SKILL.md`を作成する。既存スキルと同じ構成（frontmatter: `name`/`description`、本文: `## 目的`/`## 入力`/`## 出力`/`## 処理`）を踏襲する。`description`にはトリガーとなる発話例を含める。
4. `.claude-plugin/plugin.json`の`description`にスキル名を追記し、スキル集としての説明を最新化する。
5. スキルが複数ファイルにまたがる共通ルール（命名規則・紐付けロジック等）を新たに導入する場合は、`references/`に設計ドキュメントを追加する。関連する`SKILL.md`から参照リンクを張る。
6. テストスイート全件（230件+追加分）が通ることを確認してからコミットする。

## references/ ドキュメント一覧

`.claude/skills/vault/references/`配下。スキル横断のルールをまとめた設計ドキュメント。

| ファイル | 役割 |
|----------|------|
| `category-tagging.md` | Knowhow/WebClip共通のカテゴリタグ（`<category>/<topic>`形式の階層タグ）運用ルール |
| `conventions.md` | vaultプラグイン全体の共通実装規約（ファイル名サニタイズ等、`vault_lib.py`の決定的処理の一覧） |
| `meeting-field-mapping.md` | Microsoft 365/Outlook/Teams接続時のフィールド対応表（現状M365 MCP未接続のため将来対応） |
| `meeting-series-update.md` | 定例予定ノートの更新ロジック（`occurrence_id`による同一回/次回判定） |
| `project-matching.md` | `meeting`/`webclip`共通のプロジェクト自動紐付けルール（`vault_lib.fuzzy_project_match`） |

## 82_Bases/ Baseファイル一覧

| ファイル | フィルタ条件 | 役割 |
|----------|--------------|------|
| `Knowledge.base` | `type in ["knowhow", "webclip"]` | Knowhow/WebClip一括のナレッジノート一覧（全件ビュー・カテゴリ別グループビュー） |
| `Meetings.base` | `type == "meeting"` または `"meeting_series"` | 議事録一覧（単発・定例を横断表示） |
| `Projects.base` | `type == "project"` かつ `20_Projects/`配下 | プロジェクト一覧（Activeビューは`50_Archives/`を除外） |
| `Tasks.base` | `type == "task"` | タスク一覧（ステータス・プロジェクト・期限等を列表示） |

Base定義を追加・変更する場合、対象ノートのfrontmatter（`type`プロパティ等）との整合を確認する。
