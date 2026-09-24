# task-gantt スキルのフロー

`task-gantt`は、Vault横断で`type: task`のノート全件を集計し、プロジェクト別のMermaid ganttチャートを当日デイリーノートに書き込むスキルである。CLI引数なしで`task_gantt.py`を実行するだけの決定的処理であり、他スキルにあるようなプロジェクト解決フロー・ユーザー確認分岐は無い。最後にClaudeが結果件数を要約報告する処理のみ判断を伴う。この図は、このVaultを使う人間が、スキルの動作が想定通りか確認するための文書である。

> **凡例**: 🔵 Python処理（決定的・機械的） / 🟠 Claude判断・ユーザー確認 / 🔴 エラー・中断

```mermaid
flowchart TD
    A[task_gantt.pyを実行する] --> B{当日デイリーノートが存在するか}
    B -- 存在しない --> B1[daily_note_not_foundエラーを返す]
    B -- 存在する --> C{GANTT_START/GANTT_ENDマーカーがあるか}
    C -- ない --> C1[gantt_marker_not_foundエラーを返す]
    C -- ある --> D["20_Projects/*/Tasks/*.mdと30_Areas/Tasks/*.mdのtaskノートパスを走査する"]
    D --> E[各ノートを読み込み type!=&quot;task&quot; または読み込みエラーのものを除外する]
    E --> F{タスクを分類する}
    F -- status: 5_cancel --> Fx[除外して集計対象から外す]
    F -- 期間条件を満たさない --> Fx
    F -- "start_date/due_dateが未設定・形式不正、<br/>またはstart_date>due_date（順序逆転）" --> F2[日程未確定タスクとして収集する]
    F -- "today<=due_date<=today+90日、または due_date<today かつ status not in 4_done/5_cancel" --> F3[バー表示タスクとして収集する]
    F2 --> G
    F3 --> G[プロジェクト別にグルーピングする]
    G --> H[Mermaid ganttチャートのコードブロックを生成する]
    H --> I{日程未確定タスクが1件以上あるか}
    I -- ある --> J[日程未確定タスク一覧をMarkdown箇条書きで生成する]
    I -- ない --> K
    J --> K[マーカー区間へ書き込む内容を組み立てる]
    K --> L[デイリーノートのGANTT_START/GANTT_END区間を上書きする]
    L --> M[sections/bar_tasks/unscheduled_tasksの件数をJSONで標準出力する]
    M --> N[Claudeが件数を要約してユーザーに報告する]

    class A python
    class B python
    class B1 error
    class C python
    class C1 error
    class D python
    class E python
    class F python
    class Fx python
    class F2 python
    class F3 python
    class G python
    class H python
    class I python
    class J python
    class K python
    class L python
    class M python
    class N claude

    classDef python fill:#dbe9ff,stroke:#4472c4,color:#1a1a1a;
    classDef claude fill:#ffe9cc,stroke:#e08000,color:#1a1a1a;
    classDef error fill:#ffd6d6,stroke:#c00000,color:#1a1a1a;
```

## 補足

- 対象タスクは`type: task`のノート全件（project紐付けの有無を問わない）。`status: "5_cancel"`は常に除外する。
- 期間フィルタ: `(today <= due_date <= today+90日)`または`(due_date < today かつ status not in ("4_done", "5_cancel"))`を満たすタスクのみがバー表示対象。`status: "4_done"`のバーには`done`タグが付くが、上記フィルタ上は「未完了」扱いされないため、`due_date`が過去のdoneタスクは結果的に自然消滅する（ローリングto-doガント）。
- `start_date`・`due_date`のいずれかが未設定・形式不正、または両方設定済みでも`start_date`が`due_date`より後（順序逆転）のタスクは、この期間フィルタを適用せず常に「日程未確定タスク」として列挙する。
- `project`フロントマター値は`vault_lib.extract_project_name`で正規化してからsection名に使う（`[[Name]]`形式で手入力されていてもプレーン表記と統合される）。実在するプロジェクトフォルダを指しているかの検証は行わない。
- タスク間の依存関係表現はv1では扱わない（対応するfrontmatterフィールドが存在しないため）。
- 実行のたびにマーカー区間を上書きする（差分更新ではない）。
- daily_note_not_foundエラー時は`today-open`スキルを先に実行するよう案内する。gantt_marker_not_foundエラー時は`80_Templates/Daily_Template.md`のマーカーを当該ノートへ手動で追記するよう案内する（自動追加は行わない）。いずれもファイルへの書き込みは一切行われない。

## 関連ドキュメント

- [task-gantt/SKILL.md](../.claude/skills/vault/skills/task-gantt/SKILL.md): 本フローの一次情報
- [task_gantt.py](../.claude/skills/vault/scripts/task_gantt.py): 実装本体
- [vault_lib.py](../.claude/skills/vault/scripts/vault_lib.py): `has_marker_block`・`extract_project_name`等の共有関数

---
最終更新: 2026-09-24
