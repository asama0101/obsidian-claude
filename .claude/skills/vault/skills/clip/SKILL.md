---
name: clip
description: |
  指定URLのWebページを要約・画像保存してノート化する。「このページを
  クリップして」「Webクリップ作って」「/clip <URL>」等のトリガーで
  起動する。
---

# clip

## 目的
Webページの内容を後から参照できる形でVaultに保存する。

## 入力
対象URL。

## 出力
- `80_Attachments/` にダウンロード保存した主要画像
- `WebClip_Template.md` ベースのノート（`30_Resources/WebClips/`）

## 処理ステップ概要
1. 本文抽出・要約（3行/箇条書き）
2. 主要画像を `80_Attachments/` にダウンロード保存し埋め込み
3. `WebClip_Template.md` からノート作成

## 備考（次フェーズでの詳細実装対象）
- 詳細アルゴリズムは未実装。本ファイルは雛形。
