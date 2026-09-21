---
type: knowhow
project: ""
tags:
  - vault/plugin
---
# gitのcore.autocrlfによる偽のdiffの見分け方

## 💡 概要・結論
- core.autocrlf=trueの環境ではLF/CRLF変換のみでgit statusが差分ありと表示されることがある。git diffの出力が空（警告のみ）ならば実質的な変更はない。

## 🛠 手順・実行方法 / 解決策
1. git status で変更ありと出たファイルに対し git diff --stat で差分行数を確認する
2. 'LF will be replaced by CRLF' という警告のみで差分本体が空なら偽陽性と判断する

## ⚠️ 注意点・ハマりポイント
- 警告メッセージを実際の差分と誤認しないよう、必ずgit diffの中身まで確認する

## 🔗 参照・関連リンク


---
## 📄 ノウハウ本文
> vaultプラグイン開発中、git statusでテンプレートファイルが変更済みと表示されたが、git diffの出力はCRLF警告のみで実際の差分は無かった。
