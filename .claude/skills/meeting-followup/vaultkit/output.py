"""スクリプトの標準出力。`status`フィールドを持つ1行のJSONで返す。"""
import json
import sys


def format_result(status, **fields):
    return json.dumps({"status": status, **fields}, ensure_ascii=False)


def emit(status, **fields):
    """1行のJSONをUTF-8で標準出力へ書く（Windowsの既定の文字コードに依存しない）。"""
    sys.stdout.buffer.write((format_result(status, **fields) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()
