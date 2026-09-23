# webclip-add スキルのフロー

指定URLのWebページをPlaywrightで取得する。取得した内容をもとにClaudeが要約・カテゴリ確認を行う。その結果を受けて`webclip_save.py`がノート化・画像保存を行う一連の流れを示す。人間がこのスキルの挙動を確認する用途のドキュメント。

> **凡例**: 🔵 Python処理（決定的・機械的） / 🟠 Claude判断・ユーザー確認 / 🔴 エラー・中断 / ⚪ 未実装（今後追加予定の処理）

```mermaid
flowchart TD
    A[対象URLを受け取る] --> A1{Playwrightが使用可能か}
    A1 -- 使用可能 --> B[PlaywrightでURLへ遷移する]
    A1 -- 使用不可 --> A2["ユーザーにPlaywrightのセットアップを促し処理を中断する(新規)"]
    B --> C[ページ最下部までスクロールする]
    C --> D[本文テキストと本文中の画像URL一覧を取得する]
    D --> E{次ページへのリンクがあるか}
    E -- ある --> F{巡回ページ数が上限20ページ以内か}
    F -- 内 --> G[次ページへ遷移し本文・画像を追記取得する]
    G --> E
    F -- 超過 --> H[巡回を打ち切り、その旨を最終報告に含める]
    H --> I
    E -- ない --> I[開いたページ/タブを閉じる]
    I --> J[取得した本文から要約・キーポイント・全文を作成する]
    J --> K{会員限定等で本文が一部しか取得できなかったか}
    K -- はい --> L[全文に断り書きを明記する]
    K -- いいえ --> M
    L --> M[title/summary/key_points/full_textをJSONに書き出す]
    M --> N[list_categories.pyで既存カテゴリタグ一覧を取得する]
    N --> O[候補一覧と新規作成の選択肢をユーザーに提示し確定を待つ]
    O --> P[webclip_save.pyを実行する]
    P --> Q[summary/key_points/full_text中の画像URLを重複排除して収集する]
    Q --> R[画像を81_Attachments/へ1件ずつダウンロードする]
    R --> S{個々の画像ダウンロードは成功したか}
    S -- 成功 --> T[ローカル埋め込み記法に置換する]
    S -- 失敗 --> U[そのURLをスキップし失敗リストに記録する]
    T --> V
    U --> V[WebClip_Template.mdを基にノート本文を組み立てる]
    V --> W[30_Areas/WebClips/にノートを保存する]
    W --> X[note_path・images_saved・images_failedをJSONで出力する]
    X --> Y[Claudeが作成結果と失敗画像の有無をユーザーに報告する]

    class A1 future
    class A2 future
    class B claude
    class C claude
    class D claude
    class E claude
    class F claude
    class G claude
    class H error
    class I claude
    class J claude
    class K claude
    class L claude
    class M claude
    class N python
    class O claude
    class P python
    class Q python
    class R python
    class S python
    class T python
    class U python
    class V python
    class W python
    class X python
    class Y claude

    classDef python fill:#dbe9ff,stroke:#4472c4,color:#1a1a1a;
    classDef claude fill:#ffe9cc,stroke:#e08000,color:#1a1a1a;
    classDef error fill:#ffd6d6,stroke:#c00000,color:#1a1a1a;
    classDef future fill:#e6e6e6,stroke:#666666,stroke-dasharray: 5 5,color:#1a1a1a;
```

## 補足

- URL取得手段はPlaywright（実ブラウザ経由）に固定されており、他手段へのフォールバックは行わない。ページ遷移・スクロール・本文取得・次ページ遷移・タブを閉じるまでの一連のブラウザ操作は、Claudeが実ブラウザ経由のMCPツール（Playwright）を直接操作して行うものであり、Pythonスクリプトの決定的処理ではない。
- ページ巡回には安全弁として上限20ページが設けられており、超過時は打ち切って最終報告でその旨を伝える。
- カテゴリタグは`list_categories.py`が既存タグ候補を機械的に収集するだけで、採用可否・新規作成の判断はユーザー確認を経てClaudeが確定する（自動決定はしない）。
- `webclip_save.py`実行以降（画像URLの重複排除・ダウンロード・ローカル埋め込みへの置換・ノート本文の組み立て・保存・結果出力）はすべて同スクリプト内の決定的処理である。画像ダウンロードは1件ずつ独立して行われ、個別の失敗はスキップされる。ダウンロードに失敗した画像は`full_text`中の埋め込み記法ごと取り除かれ、ノート作成自体は継続する。
- 会員限定等の理由で本文の一部しか取得できなかった場合、ノート作成前に必ず断り書きを本文に明記する。
- URL受け取り直後のPlaywright使用可否確認(新規)は、Playwright未セットアップ時に無案内で失敗することを防ぐために追加したロジックである。

## 関連ドキュメント

- [webclip-add/SKILL.md](../.claude/skills/vault/skills/webclip-add/SKILL.md): 本フローの一次情報
- [webclip_save.py](../.claude/skills/vault/scripts/webclip_save.py): 実装本体（ノート化・画像保存処理）
- [list_categories.py](../.claude/skills/vault/scripts/list_categories.py): 既存カテゴリタグ一覧の取得処理

---
最終更新: 2026-09-23
