"""20_Projects/配下のプロジェクトディレクトリ名一覧を返すスクリプト。

`20_Projects/`直下のサブディレクトリ名を列挙するだけの機械的な処理であり、
標準ライブラリのみに依存する。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import vault_lib


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="20_Projects/配下のプロジェクト名一覧を取得する")
    parser.add_argument("--vault-root", default=None)
    args = parser.parse_args(argv)

    vault_root = Path(args.vault_root) if args.vault_root else vault_lib.VAULT_ROOT
    projects = vault_lib.list_project_names(vault_root / "20_Projects")

    print(json.dumps({"projects": projects}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
