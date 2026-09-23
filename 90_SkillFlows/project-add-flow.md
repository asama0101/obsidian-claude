# project-add スキルのフロー

`project-add`スキルは、プロジェクト名を受け取り、概要ノートと`Tasks/`・`Meetings/`・`Documents/`の3フォルダを一括作成する。同名プロジェクトが既に存在する場合は何も変更せず、ユーザーに確認を求める。本ドキュメントは、この一連の処理が想定通りに動くかを人間が確認するためのものである。

> **凡例**: 🔵 Python処理（決定的・機械的） / 🟠 Claude判断・ユーザー確認 / 🔴 エラー・中断 / ⚪ 未実装（今後追加予定の処理）

```mermaid
flowchart TD
    A[ユーザーがプロジェクト作成を依頼する] --> B[Claudeがプロジェクト名を受け取る]
    B --> C{期限の指定はあるか}
    C -->|あり| D[期限付きでproject_create.pyを実行する]
    C -->|なし| E[期限なしでproject_create.pyを実行する]
    D --> F[20_Projects/名前/ が既に存在するか確認する]
    E --> F
    F --> G{project_already_existsか}
    G -->|存在する| H[同名フォルダが既にあるとエラーを返す]
    H --> I[既存ノートを使うか別名にするかユーザーに確認する]
    G -->|存在しない| J[Project_Templateから概要ノートを作成する]
    J --> K[Tasks/・Meetings/・Documents/フォルダを作成する]
    K --> L[作成した概要ノートのパスをユーザーに報告する]

    class B claude
    class C claude
    class D python
    class E python
    class F python
    class G python
    class H error
    class I claude
    class J python
    class K python
    class L claude

    classDef python fill:#dbe9ff,stroke:#4472c4,color:#1a1a1a;
    classDef claude fill:#ffe9cc,stroke:#e08000,color:#1a1a1a;
    classDef error fill:#ffd6d6,stroke:#c00000,color:#1a1a1a;
    classDef future fill:#e6e6e6,stroke:#666666,stroke-dasharray: 5 5,color:#1a1a1a;
```

## 補足

- **期限の指定はあるか**: ユーザーが期限を伝えていれば`--due-date`付きで`project_create.py`を実行する。伝えていなければ期限なしで実行する。
- **`project_already_exists`か**: `20_Projects/<名前>/`ディレクトリが実行時点で既に存在するかどうかで判定する。スクリプトは自動採番せず、存在する場合は何も作成・変更しない。
- **既存ノートを使うか別名にするか**: `project_already_exists`エラー時にClaudeがユーザーへ確認する。スクリプト側は判断しない。
- 今回の刷新後、`task-add`/`meeting-followup`スキルからも呼び出されるようになるが、呼び出し元が増えるだけで、project-add自身のフロー（本図の内容）は変わらない。

## 関連ドキュメント

- [project-add/SKILL.md](../.claude/skills/vault/skills/project-add/SKILL.md): 本フローの一次情報
- [project_create.py](../.claude/skills/vault/scripts/project_create.py): 実装本体

---
最終更新: 2026-09-23
