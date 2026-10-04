# セットアップ手順

別の PC で同じ環境を再現するときの手順。

## 前提
- Windows、Obsidian（`C:\Program Files\Obsidian\Obsidian.exe`）、Git、Python 3
- Node.js（`npx` を使う。手順 4 の Playwright MCP と、手順 5 の grilling 用）、Google Chrome、Claude Code（`claude` コマンド）
- Vault の場所は任意（例: OneDrive の下に置いて同期する）。この PC の Vault の場所は `PERSONAL.md` に書く。

## 0. 配布用リポジトリから Vault を作る
- GitHub の非公開リポジトリには、スキル・フック・設定・テンプレート・Bases・ルールブック・手順書・空のフォルダ構成だけが入っている（ノートは入っていない）。
- 新しい PC では、Vault にしたいフォルダにクローンする。OneDrive の下に置く場合は、`.git` の実体を OneDrive の外に置く（手順3）。
- `PERSONAL.md`（個人の設定。Git では追跡しない）を作る。`personal-setup` スキルができるまでは、`CLAUDE.md` の「個人の設定」と同じ項目（環境・仕事と役割・進め方の好み）を手で書く。

## 1. Vault を開く
1. Obsidian で Vault としてそのフォルダを開く。
2. Bases、Daily notes、Templates はコアプラグインのため追加導入は不要（設定は `.obsidian/` に含まれる）。
3. 次の設定も `.obsidian/` に含まれる（配布用リポジトリに含まれる。手作業は不要）。`.obsidian/` の json を Obsidian の外で書き換えたときは、Obsidian を再起動して読み込ませる。
   - `app.json`: リンクの自動更新、添付の保存先 `90_system/attachments`、新規ノートの作成先 `00_inbox`、行番号、行の長さを制限しない、閲覧モードで開く、起動時にデイリーノートを開く。
   - `appearance.json` と `themes/Typora-Vue/`: テーマ Typora-Vue。
   - `hotkeys.json`: Ctrl+D でデイリーノートを開く、Ctrl+Shift+N でテンプレートを挿入する（既定で同じキーを使う「段落の削除」「新しいペインに新規ファイル」の割り当ては外している）。
   - `core-plugins.json`: Sync は無効（OneDrive で同期するため）。ファイル復元は有効（ノートの安全網）。

## 2. Git
- Git は配布用だけに使う。追跡するのは配布対象だけで、`.gitignore` がホワイトリストになっている（新しい配布対象を足すときは、`.gitignore` に `!` の行を足す）。
- ノートは追跡しない。ノートの安全網は Obsidian のコアプラグイン「ファイル復元」。
- ブランチは `main` だけ。コミットと push は手で行う。push の前に、追跡しているファイルに個人のパス・名前・メールアドレス・秘密情報がないことを確かめる（例: `git grep -n -i -e "<ユーザー名>" -e "<メールアドレス>"`）。
- 確認: `git ls-files` にノート（`20_tasks/` の `.md` など）と `PERSONAL.md` が出ないこと。

## 3. `.git` を OneDrive の外に置く
Vault を OneDrive の下に置く場合は、OneDrive の同期で壊れるのを避けるため、`.git` の実体を OneDrive の外に置く。Vault のフォルダで次を実行する（既存のリポジトリなら、実体が移動先へ移り、`.git` が1行のファイルになる）。移動先は `PERSONAL.md` の「環境」に書く。

```
git init --separate-git-dir "<OneDrive の外のフォルダ>"
```

確認: `.git` がファイルになっていて、`git status`・`git log`・`git fsck` がエラーなく動くこと。

元に戻すとき: Vault 直下の `.git` ファイルを消し、実体のフォルダを Vault 直下へ `.git` という名前で移す。

## 4. Playwright MCP（`grilling-html` スキル用）
`grilling-html` は、HTML のフォームをブラウザで開いて回答を読み取るために、Playwright MCP を使う。ユーザーレベルに追加する（Vault ごとの設定ではなく、この PC の Claude Code 全体の設定になる）。

```
claude mcp add --scope user playwright -- npx @playwright/mcp@latest --browser chrome --allow-unrestricted-file-access
```

- `npx` で `@playwright/mcp` を取得するため、外部へのダウンロードが発生する。
- `--allow-unrestricted-file-access` は、`file://` の HTML を開くために必要。他のプロジェクトにも効くため、`grilling-html` を使わなくなったら外す。
- 追加後は Claude Code を再起動し、`claude mcp list` で `playwright` が表示されることを確認する。

## 5. grilling スキル
質問を重ねて合意を作る `grilling` スキルは、Vault の外（ユーザー領域）にあるため、Vault の Git では再現されない。次のコマンドで入れる（`grilling-html` は、この手法を HTML フォームで行う Vault 内のスキルで、`grilling` とは別に動く）。

```
npx skills add https://github.com/mattpocock/skills --skill grilling
```

- `npx` で外部（GitHub: mattpocock/skills）から取得する。
- 入れ先は、`%USERPROFILE%\.claude\skills\grilling\`（`SKILL.md` と `agents\openai.yaml`）になる想定。この PC の現状から推定したもので、コマンドの実行結果での確認はしていない。
- 入れたあと、Claude Code を再起動し、`/grilling` が使えることを確認する。

## 6. 起動時の自動処理
`.claude/skills/daily-start/daily-start.bat` が `claude` 経由で `daily-start` スキル（`.claude/skills/daily-start/`）を呼び、スキルが `daily_start.py` を実行して次を行う。
1. 今日のデイリーノートがなければ `90_system/templates/daily.md` から作る。
2. デイリーノートのガントチャートを再生成する。
3. Obsidian でそのノートを開く。

スタートアップフォルダ（`shell:startup`）に `daily-start.bat` のショートカットを置くと、ログオン時に実行される。終わったあとも画面は閉じず（`pause`）、結果と警告を読める。何かキーを押すと閉じる。

テスト（unittest、追加インストール不要）: `python -m unittest discover -s .claude/skills/daily-start/tests`、`python -m unittest discover -s .claude/skills/meeting-followup/tests`、`python -m unittest discover -s .claude/hooks/tests`

## 6-2. フック
`.claude/settings.json` に登録済み（配布用リポジトリに含まれる。手作業は不要）。本体は `.claude/hooks/vault_hooks.py`（Python の標準ライブラリだけで動く）。
- SessionStart: ガントの更新と、短い状況を Claude に渡す。
- PostToolUse（Edit / Write）: Claude が `20_tasks/*.md` を編集したら、ガントを更新する。
- 確かめ方: Vault で `claude -p "セッション開始時のフックから受け取った「Vault の状況」を出力して"` を実行し、状況が表示されること。

手動実行: `python .claude\skills\daily-start\daily_start.py [--no-launch] [--gantt-only] [--date YYYY-MM-DD]`（ガントだけの更新は `--gantt-only`。`gantt-update` スキルと同じ）

## 7. 動作確認
- `20_tasks/` にタスクを1件作る（`start`・`due` を入れる）→ デイリーノートのガントに出る。
- `daily-start.bat` を実行して、デイリーノートが `60_daily/` に作られることを確認する。
- `/grilling` を呼び、質問が `Q1`・推奨回答の形式で出ることを確認する。
- `/grilling-html <テーマ>` を実行し、ブラウザでフォームが開くことを確認する（Playwright MCP の確認）。
- Bases の埋め込み表示は、Obsidian 上で目視確認する。
