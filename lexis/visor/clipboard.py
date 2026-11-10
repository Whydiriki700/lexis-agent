# Copyright 2026 Riki Wahyudi (Osvyn)
# SPDX-License-Identifier: Apache-2.0
"""System clipboard access for the Visor's entry fields
(Master, 2026-11-11: Ctrl+C and Ctrl+V must work in every
entry, without exception).

Stdlib only. On Windows the Win32 clipboard is driven through
ctypes; elsewhere pyperclip is used when present, then the
platform tools (pbcopy/pbpaste, wl-copy/wl-paste, xclip).
Every failure is a quiet False or None: an entry must never
crash because the clipboard is unavailable.
"""

import subprocess
import sys


def _win_set(text: str) -> bool:
    import ctypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    if not user32.OpenClipboard(None):
        return False
    try:
        user32.EmptyClipboard()
        data = (text + "\0").encode("utf-16-le")
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        locked = kernel32.GlobalLock(handle)
        ctypes.memmove(locked, data, len(data))
        kernel32.GlobalUnlock(handle)
        return bool(user32.SetClipboardData(CF_UNICODETEXT, handle))
    finally:
        user32.CloseClipboard()


def _win_get():
    import ctypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    CF_UNICODETEXT = 13
    if not user32.OpenClipboard(None):
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        locked = kernel32.GlobalLock(handle)
        if not locked:
            return None
        try:
            return ctypes.wstring_at(locked)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _tool_set(text: str) -> bool:
    for cmd in (["pbcopy"], ["wl-copy"], ["xclip", "-selection",
                                            "clipboard"]):
        try:
            subprocess.run(cmd, input=text.encode("utf-8"),
                           check=True, timeout=5,
                           capture_output=True)
            return True
        except Exception:
            continue
    return False


def _tool_get():
    for cmd in (["pbpaste"], ["wl-paste"],
                ["xclip", "-selection", "clipboard", "-o"]):
        try:
            out = subprocess.run(cmd, check=True, timeout=5,
                                 capture_output=True)
            return out.stdout.decode("utf-8", "replace")
        except Exception:
            continue
    return None


def set_text(text: str) -> bool:
    try:
        if sys.platform == "win32":
            return _win_set(text)
        try:
            import pyperclip

            pyperclip.copy(text)
            return True
        except Exception:
            return _tool_set(text)
    except Exception:
        return False


def get_text():
    try:
        if sys.platform == "win32":
            return _win_get()
        try:
            import pyperclip

            value = pyperclip.paste()
            return value if isinstance(value, str) else None
        except Exception:
            return _tool_get()
    except Exception:
        return None
