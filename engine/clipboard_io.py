"""The computer's clipboard, for LOKI's own window (Paste/Copy that always work).

The app window (pywebview: WebView2 / WKWebView) can block the browser's paste - no right-click menu,
and on some machines Ctrl+V does nothing in a field. The window then asks the engine, which runs on
the same computer, to read or write the clipboard. Only ever on an explicit click/keypress in the
window (bearer token), never logged, at most MAX characters.
"""
from __future__ import annotations

import subprocess
import sys

MAX = 20000


def read() -> str:
    if sys.platform == "win32":
        return _win_read()
    cmds = [["pbpaste"]] if sys.platform == "darwin" else [["wl-paste", "-n"], ["xclip", "-selection", "clipboard", "-o"]]
    for cmd in cmds:
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=3)
            if out.returncode == 0:
                return out.stdout.decode("utf-8", errors="replace")[:MAX]
        except (OSError, subprocess.SubprocessError):
            continue
    return ""


def write(text: str) -> bool:
    text = str(text or "")[:MAX]
    if sys.platform == "win32":
        return _win_write(text)
    cmds = [["pbcopy"]] if sys.platform == "darwin" else [["wl-copy"], ["xclip", "-selection", "clipboard"]]
    for cmd in cmds:
        try:
            if subprocess.run(cmd, input=text.encode("utf-8"), timeout=3).returncode == 0:
                return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


def _win_read() -> str:   # pragma: no cover - Windows only
    import ctypes  # pylint: disable=import-outside-toplevel
    from ctypes import wintypes  # pylint: disable=import-outside-toplevel
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    if not user32.OpenClipboard(None):
        return ""
    try:
        handle = user32.GetClipboardData(13)   # CF_UNICODETEXT
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)[:MAX]
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _win_write(text: str) -> bool:   # pragma: no cover - Windows only
    try:
        subprocess.run(["clip"], input=text.encode("utf-16-le"), timeout=3, creationflags=0x08000000)
        return True
    except (OSError, subprocess.SubprocessError):
        return False
