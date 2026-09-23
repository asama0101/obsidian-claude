"""既存ノートから使用済みの階層カテゴリタグを収集するスクリプト。

Knowhow(30_Areas/Knowledge)とWebClip(30_Areas/WebClips)配下のノートを走査し、
frontmatterのtags:から`<category>/<topic>`形式(`/`をちょうど1つ含む)のタグだけを
抽出して候補として返す。判断はせず、重複排除とソートのみ行う機械的な収集であり、
候補の採用可否は呼び出し元のスキルが人間に確認する。標準ライブラリのみに依存する。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import vault_lib


def list_category_tags(vault_root: Path) -> list[str]:
    """vault_root配下のKnowhow/WebClipノートから階層カテゴリタグを収集する。"""
    target_dirs = [
        vault_root / "30_Areas" / "Knowledge",
        vault_root / "30_Areas" / "WebClips",
    ]

    found: set[str] = set()
    for target_dir in target_dirs:
        if not target_dir.exists():
            continue
        for note_path in target_dir.rglob("*.md"):
            text = note_path.read_text(encoding="utf-8")
            fm_text, _ = vault_lib.split_frontmatter(text)
            for tag in vault_lib.get_fm_tags(fm_text):
                if tag.count("/") == 1:
                    found.add(tag)

    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="既存ノートから階層カテゴリタグの候補を収集する")
    parser.add_argument("--vault-root", default=None)
    args = parser.parse_args(argv)

    vault_root = Path(args.vault_root) if args.vault_root else vault_lib.VAULT_ROOT
    tags = list_category_tags(vault_root)

    print(json.dumps({"tags": tags}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
