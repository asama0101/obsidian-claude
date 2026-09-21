---
type: knowhow
project: ""
tags:
  - python/pathlib
---
# os.pathよりpathlibを使うべき理由（カテゴリタグ検証テスト）

## 💡 概要・結論
- pathlibはパス操作をオブジェクト指向で扱え、os.pathの文字列連結より安全で可読性が高い。

## 🛠 手順・実行方法 / 解決策
1. from pathlib import Path でインポートする
2. Path('dir') / 'file.txt' のように / 演算子でパスを結合する
3. p.exists() / p.is_file() 等のメソッドで判定する

## ⚠️ 注意点・ハマりポイント
- 文字列パスとの相互変換が必要な外部ライブラリでは str(p) で明示変換する

## 🔗 参照・関連リンク


---
## 📄 ノウハウ本文
> os.path.join(dir, file)よりPath(dir)/fileの方が読みやすく、WindowsとPOSIXの区切り文字差異も吸収してくれる。
