#!/usr/bin/env python3
"""議事録ノートの「アクションアイテム」の節を読み、処理済みの印（タスクへのリンク）を付ける。

  meeting_actions.py list --meeting <議事録名>
      未処理の項目と、議事録のプロジェクト・開催日を返す。項目は text（本文そのもの）・content・assignee・due。
  meeting_actions.py link --meeting <議事録名> --text <本文> --task <タスク名>
      その項目の行末に ` → [[タスク名]]` を足す。タスクのノートが 20_tasks/ に無ければ拒否する。

議事録は 70_meetings/、タスクは 20_tasks/ から探す。名前の `.md` は省略できる。
書き換えるのは本文の該当行だけで、frontmatter は書き換えない。
結果は1行の JSON。`status` は ok / linked / not_found / invalid。ok・linked 以外は終了コード1。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vaultkit import frontmatter  # noqa: E402
from vaultkit.meetings import link_action, parse_item, project_name, unresolved_actions  # noqa: E402
from vaultkit.output import emit  # noqa: E402
from vaultkit.paths import find_note, vault_root  # noqa: E402


def _text(value):
    return value if isinstance(value, str) else ""


def main(argv=None):
    parser = argparse.ArgumentParser(description="議事録のアクションアイテム")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("list", "link"):
        command = sub.add_parser(name)
        command.add_argument("--meeting", required=True)
        if name == "link":
            command.add_argument("--text", required=True)
            command.add_argument("--task", required=True)
    args = parser.parse_args(argv)

    path = find_note("meeting", args.meeting)
    if path is None:
        emit("not_found", meeting=args.meeting.removesuffix(".md"))
        return 1
    try:
        with open(path, encoding="utf-8", newline="") as f:
            text = f.read()
    except UnicodeDecodeError as error:
        emit("invalid", problems=[f"議事録を読めません: {error}"])
        return 1
    relative = path.relative_to(vault_root()).as_posix()

    if args.command == "list":
        try:
            meta, _ = frontmatter.parse(text)
        except frontmatter.FrontmatterError as error:
            emit("invalid", problems=[f"frontmatterを読めません: {error}"])
            return 1
        emit(
            "ok",
            meeting=path.stem,
            path=relative,
            date=_text(meta.get("date", "")),
            project=project_name(_text(meta.get("project", ""))),
            items=[parse_item(body) for body in unresolved_actions(text)],
        )
        return 0

    task_path = find_note("task", args.task)
    if task_path is None:
        emit("invalid", problems=[f"タスクノートがありません: {args.task}"])
        return 1
    try:
        updated = link_action(text, args.text, task_path.stem)
    except ValueError as error:
        emit("invalid", problems=[str(error)])
        return 1
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(updated)
    emit("linked", path=relative, text=args.text, task=task_path.stem)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
