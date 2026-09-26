# today-open スキルのフロー

`today-open`スキルは、1日の作業を開始する準備（当日ブランチの作成・デイリーノートの作成・カレンダー予定の同期）を自動化する。この図は、スキルが想定通りに動いているかを人間が確認するためのものである。

> **凡例**: 🔵 Python処理（決定的・機械的） / 🟠 Claude判断・ユーザー確認 / 🔴 エラー・中断 / ⚪ 未実装（今後追加予定の処理）

```mermaid
flowchart TD
    Start([today_start.py を実行する]) --> CheckBlocked{未マージの過去日ブランチが残っているか}
    class CheckBlocked python

    CheckBlocked -->|残っている| Blocked[ユーザーに未マージブランチの対応方針を確認し<br/>処理を先に進めない]
    class Blocked error

    CheckBlocked -->|残っていない| CheckBranch{当日日付のブランチは既に存在するか}
    class CheckBranch python

    CheckBranch -->|存在する| CheckoutExisting[既存の当日ブランチへcheckoutする]
    class CheckoutExisting python

    CheckBranch -->|存在しない| CreateBranch[originがあれば事前にmainを最新化したうえで<br/>mainから当日ブランチを新規作成しcheckoutする]
    class CreateBranch python

    CreateBranch --> CheckStray{mainに残っていた追跡済みファイルの<br/>未コミット変更があるか<br/>(未追跡の新規ファイルは対象外)}
    class CheckStray python

    CheckStray -->|あり| CommitStray[新ブランチ上でgit add -u→コミットする<br/>stray_changes_committedにコミットSHAを記録する]
    class CommitStray python

    CheckStray -->|なし| CheckNote{当日のデイリーノートは既に存在するか}
    CommitStray --> CheckNote
    CheckoutExisting --> CheckNote
    class CheckNote python

    CheckNote -->|存在する| SkipNote[デイリーノートの作成をスキップする]
    class SkipNote python

    CheckNote -->|存在しない| FindPrev[10_Daily内で当日より前の日付のうち<br/>最も新しいノートを探す]
    class FindPrev python

    FindPrev --> ExtractCarryover[見つかった場合、そのノートのCARRYOVERブロックの<br/>中身だけを読み取る（元ノートは変更しない）]
    class ExtractCarryover python

    ExtractCarryover --> CreateNote[Daily_Templateから当日のデイリーノートを作成し<br/>Carryoverの内容を転記する]
    class CreateNote python

    SkipNote --> CallMeeting[続けてmeeting-setupスキルの実行フローを呼び出す<br/>カレンダー予定を議事録ノートに反映する]
    CreateNote --> CallMeeting
    class CallMeeting claude

    CallMeeting --> MeetingResult{meeting-setupスキルの呼び出しは成功したか}
    class MeetingResult python

    MeetingResult -->|失敗<br/>未接続・API呼び出し失敗等| MeetingFailed[失敗した旨を記録する<br/>today-openの処理内容は巻き戻さない]
    class MeetingFailed error

    MeetingResult -->|成功| CallGantt[続けてtask-ganttスキルの実行フローを呼び出す<br/>タスクのガントチャートを最新化する]
    MeetingFailed --> CallGantt
    class CallGantt claude

    CallGantt --> GanttResult{task_gantt.pyの実行は成功したか}
    class GanttResult python

    GanttResult -->|失敗<br/>daily_note_not_found/gantt_marker_not_found| GanttFailed[失敗した旨を記録する<br/>today-openの処理内容は巻き戻さない]
    class GanttFailed error

    GanttResult -->|成功| Report[ブランチ状態・デイリーノート作成有無・<br/>meeting-setupスキルの実行結果・<br/>task-ganttスキルの実行結果をユーザーに報告する]
    GanttFailed --> Report
    class Report claude

    classDef python fill:#dbe9ff,stroke:#4472c4,color:#1a1a1a;
    classDef claude fill:#ffe9cc,stroke:#e08000,color:#1a1a1a;
    classDef error fill:#ffd6d6,stroke:#c00000,color:#1a1a1a;
    classDef future fill:#e6e6e6,stroke:#666666,stroke-dasharray: 5 5,color:#1a1a1a;
```

## 補足

- **未マージの過去日ブランチが残っているか**: `git branch --no-merged main`で判定する。当日ブランチ以外にYYYY-MM-DD形式のブランチが残っていれば`status: "blocked"`となり、`today-open`の処理はそこで止まる。マージ・削除はスクリプト自身では行わない。
- **当日日付のブランチは既に存在するか**: 既存なら`branch: "existing"`としてcheckoutのみ行う。存在しなければ`main`から新規作成し`branch: "created"`となる。新規作成時、`origin`リモートが設定されていれば`main`を`git pull --ff-only`で最新化する（失敗しても処理は続行する）。
- **mainに残っていた追跡済みファイルの未コミット変更があるか**: `branch: "created"`のときのみ発生する分岐。`checkout -b`直後に`git status --porcelain --untracked-files=no`で検出する（未追跡の新規ファイルは対象外）。あれば新ブランチ上で`git add -u`→コミットし、コミットSHAを`stray_changes_committed`に記録する。無ければ`stray_changes_committed`は`null`のまま。既存の当日ブランチへの単純checkout（`branch: "existing"`）ではこの分岐自体を通らないため、常に`null`。
- **当日のデイリーノートは既に存在するか**: 存在すれば`daily_note: "skipped"`となり以降の転記処理は行わない。存在しなければ`daily_note: "created"`となり、前日ノートが見つかった場合は`carryover_source`にその日付が入る（見つからなければ`null`）。
- **meeting-setupスキルの呼び出しは成功したか**: Google Calendar MCP未接続やAPI呼び出し失敗時はここで失敗として扱われるが、`today-open`本来の処理（ブランチ作成・デイリーノート作成）は既に完了しているため巻き戻さない。失敗した旨は最終報告に含める。
- **task_gantt.pyの実行は成功したか**: `daily_note`が`"skipped"`（既存ノート再利用）の場合も含め、`status: "ok"`なら毎回実行する（`task_gantt.py`はマーカー区間を毎回上書きする冪等な処理のため、再実行しても問題ない）。`daily_note_not_found`/`gantt_marker_not_found`はここで失敗として扱われるが、`today-open`本来の処理は巻き戻さない。失敗した旨は最終報告に含める。

## 関連ドキュメント

- [today-open/SKILL.md](../.claude/skills/vault/skills/today-open/SKILL.md): 本フローの一次情報
- [meeting-setup/SKILL.md](../.claude/skills/vault/skills/meeting-setup/SKILL.md): today-open/today-closeスキルからのmeeting-setupスキル自動呼び出しの詳細
- [task-gantt/SKILL.md](../.claude/skills/vault/skills/task-gantt/SKILL.md): today-openスキルからのtask-ganttスキル自動呼び出しの詳細

---
最終更新: 2026-09-25
