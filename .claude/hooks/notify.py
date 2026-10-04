"""Windows の通知（トースト）を出す。vault_hooks.py から使う。

PowerShell 5.1 の WinRT（Windows.UI.Notifications）で表示する。追加のインストールは不要。
通知の差出人は Windows PowerShell の AppUserModelID を借りる（未登録の ID では表示されないため）。
launch に obsidian:// の URI を渡すと、通知をクリックしたときにそのノートを Obsidian で開く。

テスト用: 環境変数 VAULT_NOTIFY_LOG にファイルのパスがあれば、表示せずに内容を JSON の1行で追記する。
"""
import base64
import json
import os
import subprocess
from xml.sax.saxutils import escape

APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"

SCRIPT = r"""
[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml(@'
__XML__
'@)
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('__APP__').Show($toast)
"""


def toast_xml(title, lines, launch=""):
    texts = "".join(f"<text>{escape(t)}</text>" for t in [title, *lines][:3])
    attrs = f' activationType="protocol" launch="{escape(launch, {chr(34): "&quot;"})}"' if launch else ""
    return f"<toast{attrs}><visual><binding template=\"ToastGeneric\">{texts}</binding></visual></toast>"


def show(title, lines, launch=""):
    """通知を出す。失敗しても例外は投げない（フックを止めない）。"""
    log = os.environ.get("VAULT_NOTIFY_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"title": title, "lines": lines, "launch": launch}, ensure_ascii=False) + "\n")
        return
    script = SCRIPT.replace("__XML__", toast_xml(title, lines, launch)).replace("__APP__", APP_ID)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            capture_output=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        pass
