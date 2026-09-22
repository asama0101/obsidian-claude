# knowhow-add スキルのフロー

この図は、このVaultを使う人間が、スキルの動作が想定通りか確認するための文書である。

雑多なメモ・ログ・コンソール出力等を、Claudeが「概要・手順・注意点」の構造に整形し、カテゴリタグをユーザーに確認した上でナレッジノートとして保存するスキル。原文は加工せず`original_text`として保持する。

> **凡例**: 🔵 Python処理（決定的・機械的） / 🟠 Claude判断・ユーザー確認 / 🔴 エラー・中断 / ⚪ 未実装（今後追加予定の処理）

```mermaid
flowchart TD
    A[雑多なメモ・ログ・コンソール出力を受け取る] --> B["Claudeが概要・結論/手順・実行方法解決策/注意点・ハマりポイント/参照・関連リンクに整形する"]
    B --> C[原文を無加工のまま original_text として保持する]
    C --> D[整形結果+原文をJSONファイルに書き出す]
    D --> E["list_categories.py を実行し既存のcategory/topicタグ一覧を取得する"]
    E --> F{既存タグ候補は1件以上あるか}
    F -->|あり| G[既存タグ一覧+新規作成の選択肢をユーザーに提示する]
    F -->|0件| H[内容からClaudeがcategory/topicタグ候補を数件提案する新規作成の選択肢も併記]
    G --> I[ユーザーがタグを選択または新規入力するまで待つ]
    H --> I
    I --> J[確定したタグと整形済み内容を渡してknowhow_save.pyを実行する]
    J --> K[Knowhow_Template.md を展開しfrontmatterと本文に分割する]
    K --> L[frontmatterにタグを追加する]
    L --> M[本文の各セクション概要・手順・注意点・参照・原文を差し込む]
    M --> N[20_Areas/Knowledge/ にノートファイルを保存する]
    N --> O{保存は成功したか}
    O -->|成功| P[note_pathを標準出力にJSONで返す]
    O -->|失敗 テンプレート読込エラー等| Q[エラーを報告し処理を中断する]
    P --> R[Claudeがnote_pathを確認しユーザーに保存結果を報告する]

    class B claude
    class C python
    class D python
    class E python
    class F python
    class G claude
    class H claude
    class I claude
    class J python
    class K python
    class L python
    class M python
    class N python
    class O python
    class P python
    class Q error
    class R claude

    classDef python fill:#dbe9ff,stroke:#4472c4,color:#1a1a1a;
    classDef claude fill:#ffe9cc,stroke:#e08000,color:#1a1a1a;
    classDef error fill:#ffd6d6,stroke:#c00000,color:#1a1a1a;
    classDef future fill:#e6e6e6,stroke:#666666,stroke-dasharray: 5 5,color:#1a1a1a;
```

## 補足

- カテゴリタグは`<category>/<topic>`形式の階層タグ1本のみで分類する（旧`category`frontmatterプロパティは廃止済み）。
- `list_categories.py`は`20_Areas/Knowledge/`と`20_Areas/WebClips/`配下のノートを走査し、`/`をちょうど1つ含むタグだけを重複排除・ソートして返す機械的な集計処理であり、判断は行わない。
- カテゴリタグの確定はClaudeが単独で自動決定してはならない。既存候補が0件の場合でも自由入力だけに丸投げしない。Claudeが候補を提案した上で、ユーザーの明示的な選択・入力を待つ（詳細は`.claude/skills/vault/references/category-tagging.md`）。
- ノート保存時、`title`から`vault_lib.sanitize_filename`でファイル名を生成し、同名ファイルが既に存在する場合は`vault_lib.unique_path`で衝突を回避する。
- 保存失敗時（テンプレートファイルが見つからない等）の具体的なリカバリ手順はソースコード上未規定であり、本図では「エラー報告・中断」までを示すにとどめる。

## 関連ドキュメント

- [knowhow-add/SKILL.md](../.claude/skills/vault/skills/knowhow-add/SKILL.md): 本フローの一次情報
- [knowhow_save.py](../.claude/skills/vault/scripts/knowhow_save.py): 実装本体（ノート保存処理）
- [list_categories.py](../.claude/skills/vault/scripts/list_categories.py): 既存カテゴリタグ一覧の取得処理
- [category-tagging.md](../.claude/skills/vault/references/category-tagging.md): カテゴリタグ運用ルール

---
最終更新: 2026-09-23
