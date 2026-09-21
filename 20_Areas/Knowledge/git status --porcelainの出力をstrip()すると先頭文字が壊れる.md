---
type: knowhow
project: ""
category: "git"
tags:
  - knowhow
  - knowledge/git
---
# git status --porcelainの出力をstrip()すると先頭文字が壊れる

## 💡 概要・結論
- subprocessでgit status --porcelainの出力を扱う際、stdout全体にPythonのstrip()をかけると、行頭が半角スペース（インデックス側が未変更を示すコード）から始まる行の先頭文字が失われ、ファイルパスの1文字目が欠落する。

## 🛠 手順・実行方法 / 解決策
1. git status --porcelainの出力形式を確認する（先頭2文字がステータスコード、3文字目以降がパス）
2. stdoutに対してstrip()ではなくrstrip('\n')のみを使い、行頭の空白を保持する
3. porcelain出力をsplitlines()で1行ずつ処理し、各行の3文字目以降をパスとして取り出す

## ⚠️ 注意点・ハマりポイント
- strip()は文字列全体の前後の空白を除去するため、複数行出力の先頭行にある意味のある空白まで消えてしまう
- 単純な単一行の出力（ブランチ名など）で動作確認しただけでは気づきにくい

## 🔗 参照・関連リンク


---
## 📄 ノウハウ本文
> close_day.pyの実装中に発見: vault_lib.run_git()がresult.stdout.strip()を使っていたため、git status --porcelainの結果で先頭行が' M 70_Templates/Daily_Template.md'のようにスペースから始まる場合、先頭の意味ある空白が失われてパースがずれ、ファイル名の先頭文字が欠落した（'70_Templates/...'が'0_Templates/...'のようになる）。rstrip('\n')に変更して解決。
