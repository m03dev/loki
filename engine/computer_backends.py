"""The hands and eyes of LOKI's `computer` tool, one backend per OS - ctypes only, nothing to install.

  Windows  screen: GDI BitBlt; mouse/keyboard: SendInput (Unicode typing); accessibility tree: UI
           Automation through comtypes (the one optional package; without it the tree is empty and the
           tool falls back to vision); focused app: GetForegroundWindow + its process name. The process is
           made per-monitor DPI aware so UIA rectangles, the screenshot and the mouse share one pixel grid.
  macOS    screen: /usr/sbin/screencapture; mouse/keyboard: Quartz CGEvent; accessibility tree: AXUIElement
           (ApplicationServices) - the app running LOKI needs Accessibility and Screen Recording permission
           (System Settings > Privacy & Security); coordinates are points, the screenshot is pixels (Retina 2x),
           `scale` converts.
  Linux    xdotool + an X screenshot tool when present; no tree (vision only). Not a target machine; kept so
           the tool says something useful there.

The interactive control types follow Windows-MCP (github.com/CursorTouch/Windows-MCP, MIT,
src/windows_mcp/tree/config.py INTERACTIVE_CONTROL_TYPE_NAMES) - licence in engine/licenses/Windows-MCP-MIT.txt.
Every backend has the same small surface (see Backend); computer_use.py adds safety, logging, finding and
vision on top, and tests use FakeBackend.
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

# Normalised roles a small model sees (one word each).
INTERACTIVE_ROLES = {"button", "link", "field", "checkbox", "radio", "combobox", "menuitem", "tab", "listitem",
                     "treeitem", "slider", "spinner", "cell", "header", "scrollbar", "splitbutton", "menu"}


def encode_png(width: int, height: int, rgb: bytes) -> bytes:
    """A PNG from packed 8-bit RGB rows (standard library only)."""
    stride = width * 3
    raw = b"".join(b"\x00" + rgb[y * stride:(y + 1) * stride] for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def png_size(data: bytes) -> tuple:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return 0, 0
    return struct.unpack(">II", data[16:24])


def parse_keys(combo: str) -> tuple:
    """'ctrl+shift+s' -> (['ctrl', 'shift'], 's'); 'enter' -> ([], 'enter'). Raises ValueError."""
    aliases = {"control": "ctrl", "ctl": "ctrl", "option": "alt", "opt": "alt", "command": "cmd", "super": "win",
               "windows": "win", "meta": "cmd", "return": "enter", "escape": "esc", "del": "delete", "bksp": "backspace",
               "pgup": "pageup", "pgdn": "pagedown", "arrowup": "up", "arrowdown": "down", "arrowleft": "left",
               "arrowright": "right", "spacebar": "space"}
    parts = [p.strip().lower() for p in str(combo or "").replace(" + ", "+").split("+") if p.strip()]
    if not parts:
        raise ValueError("give keys, e.g. 'enter', 'ctrl+s', 'cmd+space'")
    parts = [aliases.get(p, p) for p in parts]
    mods, key = parts[:-1], parts[-1]
    for m in mods:
        if m not in ("ctrl", "alt", "shift", "cmd", "win"):
            raise ValueError("%r is not a modifier (ctrl, alt, shift, cmd, win)" % m)
    return mods, key


class Backend:
    name = "none"
    scale = 1.0          # screenshot pixels per input unit

    def available(self) -> tuple:
        return False, "no backend"

    def screenshot(self) -> bytes:
        raise RuntimeError("no screenshot on this machine")

    def screen_size(self) -> tuple:
        return 0, 0

    def elements(self, limit: int = 400) -> list:
        return []

    def frontmost(self) -> dict:
        return {"app": "", "title": ""}

    def click(self, x: int, y: int, button: str = "left", count: int = 1) -> None:
        raise RuntimeError("no mouse")

    def type_text(self, text: str) -> None:
        raise RuntimeError("no keyboard")

    def key(self, combo: str) -> None:
        raise RuntimeError("no keyboard")

    def scroll(self, x: int, y: int, clicks: int) -> None:
        raise RuntimeError("no mouse")

    def cursor(self) -> tuple:
        return -1, -1

    def open_app(self, name: str) -> str:
        raise RuntimeError("cannot open apps here")

    def activate(self, name: str) -> bool:
        """Bring an open app to the front (and give it a window if it has none). False if it could not."""
        return False

    def apps(self) -> list:
        return []

    def kill_pressed(self) -> bool:
        return False


# ============================================================================ Windows
UIA_TYPES = {50000: "button", 50001: "calendar", 50002: "checkbox", 50003: "combobox", 50004: "field",
             50005: "link", 50006: "image", 50007: "listitem", 50008: "list", 50009: "menu", 50010: "menubar",
             50011: "menuitem", 50012: "progressbar", 50013: "radio", 50014: "scrollbar", 50015: "slider",
             50016: "spinner", 50017: "statusbar", 50018: "tab", 50019: "tabitem", 50020: "text", 50021: "toolbar",
             50022: "tooltip", 50023: "tree", 50024: "treeitem", 50025: "custom", 50026: "group", 50027: "thumb",
             50028: "datagrid", 50029: "cell", 50030: "document", 50031: "splitbutton", 50032: "window",
             50033: "pane", 50034: "header", 50035: "header", 50036: "table", 50037: "titlebar", 50038: "separator"}
# Windows-MCP INTERACTIVE_CONTROL_TYPE_NAMES, as UIA ids
UIA_INTERACTIVE = {50000, 50007, 50011, 50004, 50002, 50013, 50003, 50005, 50031, 50019, 50024, 50029, 50035,
                   50016, 50015, 50014}
VK = {"enter": 0x0D, "tab": 0x09, "esc": 0x1B, "backspace": 0x08, "delete": 0x2E, "insert": 0x2D, "space": 0x20,
      "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "home": 0x24, "end": 0x23, "pageup": 0x21,
      "pagedown": 0x22, "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B, "cmd": 0x5B, "capslock": 0x14,
      "printscreen": 0x2C, "menu": 0x5D}
VK.update({"f%d" % i: 0x6F + i for i in range(1, 13)})
WIN_APPS = {"notepad": "notepad.exe", "calculator": "calc.exe", "calc": "calc.exe", "paint": "mspaint.exe",
            "explorer": "explorer.exe", "file explorer": "explorer.exe", "wordpad": "write.exe",
            "cmd": "cmd.exe", "task manager": "taskmgr.exe", "snipping tool": "snippingtool.exe"}


class WindowsBackend(Backend):
    name = "windows"

    def __init__(self) -> None:
        import ctypes  # pylint: disable=import-outside-toplevel
        from ctypes import wintypes  # pylint: disable=import-outside-toplevel
        self.ct, self.wt = ctypes, wintypes
        self.user32 = ctypes.windll.user32
        self.gdi32 = ctypes.windll.gdi32
        self.kernel32 = ctypes.windll.kernel32
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)      # per-monitor aware: one pixel grid
        except Exception:  # noqa: BLE001
            try:
                self.user32.SetProcessDPIAware()
            except Exception:  # noqa: BLE001
                pass
        self._uia = None
        self._uia_error = ""

        ULONG_PTR = ctypes.c_size_t

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

        class _U(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", _U)]

        self.INPUT, self.KEYBDINPUT, self.MOUSEINPUT = INPUT, KEYBDINPUT, MOUSEINPUT
        self.user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        self.user32.GetForegroundWindow.restype = wintypes.HWND

    def available(self) -> tuple:
        return True, "Windows: SendInput + GDI" + ("" if self._load_uia() else " (no UI Automation: %s)" % self._uia_error)

    # ---- screen
    def screen_size(self) -> tuple:
        return self.user32.GetSystemMetrics(0), self.user32.GetSystemMetrics(1)

    def screenshot(self) -> bytes:
        ct, wt = self.ct, self.wt
        w, h = self.screen_size()
        hdc = self.user32.GetDC(0)
        mem = self.gdi32.CreateCompatibleDC(hdc)
        bmp = self.gdi32.CreateCompatibleBitmap(hdc, w, h)
        old = self.gdi32.SelectObject(mem, bmp)
        try:
            self.gdi32.BitBlt(mem, 0, 0, w, h, hdc, 0, 0, 0x00CC0020 | 0x40000000)   # SRCCOPY | CAPTUREBLT

            class BITMAPINFOHEADER(ct.Structure):
                _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                            ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                            ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                            ("biClrImportant", wt.DWORD)]
            info = BITMAPINFOHEADER()
            info.biSize, info.biWidth, info.biHeight = ct.sizeof(BITMAPINFOHEADER), w, -h   # top-down rows
            info.biPlanes, info.biBitCount, info.biCompression = 1, 32, 0
            buf = ct.create_string_buffer(w * h * 4)
            self.gdi32.GetDIBits(mem, bmp, 0, h, buf, ct.byref(info), 0)
        finally:
            self.gdi32.SelectObject(mem, old)
            self.gdi32.DeleteObject(bmp)
            self.gdi32.DeleteDC(mem)
            self.user32.ReleaseDC(0, hdc)
        bgra = buf.raw
        rgb = bytearray(w * h * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
        return encode_png(w, h, bytes(rgb))

    # ---- input
    def _send(self, items: list) -> None:
        arr = (self.INPUT * len(items))(*items)
        self.user32.SendInput(len(items), arr, self.ct.sizeof(self.INPUT))

    def _key_input(self, vk: int = 0, scan: int = 0, flags: int = 0):
        item = self.INPUT()
        item.type = 1
        item.u.ki = self.KEYBDINPUT(vk, scan, flags, 0, 0)
        return item

    def click(self, x: int, y: int, button: str = "left", count: int = 1) -> None:
        self.user32.SetCursorPos(int(x), int(y))
        down, up = {"left": (0x2, 0x4), "right": (0x8, 0x10), "middle": (0x20, 0x40)}.get(button, (0x2, 0x4))
        for _ in range(max(1, int(count))):
            self.user32.mouse_event(down, 0, 0, 0, 0)
            self.user32.mouse_event(up, 0, 0, 0, 0)
            time.sleep(0.05)

    def scroll(self, x: int, y: int, clicks: int) -> None:
        self.user32.SetCursorPos(int(x), int(y))
        self.user32.mouse_event(0x0800, 0, 0, self.ct.c_uint32(int(clicks) * 120 & 0xFFFFFFFF).value, 0)

    def type_text(self, text: str) -> None:
        items = []
        for unit in struct.unpack("<%dH" % (len(text.encode("utf-16-le")) // 2), text.encode("utf-16-le")):
            if unit == 10:       # newline -> Enter
                items += [self._key_input(VK["enter"]), self._key_input(VK["enter"], flags=2)]
                continue
            items += [self._key_input(0, unit, 4), self._key_input(0, unit, 4 | 2)]   # KEYEVENTF_UNICODE (+KEYUP)
        if items:
            self._send(items)

    def key(self, combo: str) -> None:
        mods, key = parse_keys(combo)
        if key in VK:
            code = VK[key]
        elif len(key) == 1 and key.isalnum():
            code = ord(key.upper())
        else:
            raise ValueError("unknown key %r" % key)
        downs = [self._key_input(VK[m]) for m in mods] + [self._key_input(code)]
        ups = [self._key_input(code, flags=2)] + [self._key_input(VK[m], flags=2) for m in reversed(mods)]
        self._send(downs + ups)

    def cursor(self) -> tuple:
        pt = self.wt.POINT()
        self.user32.GetCursorPos(self.ct.byref(pt))
        return pt.x, pt.y

    def kill_pressed(self) -> bool:
        state = self.user32.GetAsyncKeyState
        return bool(state(VK["ctrl"]) & 0x8000 and state(VK["alt"]) & 0x8000 and state(VK["esc"]) & 0x8000)

    # ---- apps
    def _proc_name(self, hwnd) -> str:
        pid = self.wt.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, self.ct.byref(pid))
        handle = self.kernel32.OpenProcess(0x1000, False, pid.value)
        if not handle:
            return ""
        try:
            buf = self.ct.create_unicode_buffer(1024)
            size = self.wt.DWORD(1024)
            if self.kernel32.QueryFullProcessImageNameW(handle, 0, buf, self.ct.byref(size)):
                return Path(buf.value).stem.lower()
        finally:
            self.kernel32.CloseHandle(handle)
        return ""

    def _title(self, hwnd) -> str:
        n = self.user32.GetWindowTextLengthW(hwnd)
        buf = self.ct.create_unicode_buffer(n + 1)
        self.user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def frontmost(self) -> dict:
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return {"app": "", "title": ""}
        pid = self.wt.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, self.ct.byref(pid))
        return {"app": self._proc_name(hwnd), "title": self._title(hwnd), "pid": int(pid.value)}

    def activate(self, name: str) -> bool:
        want = Path(WIN_APPS.get(str(name or "").strip().lower(), str(name or ""))).stem.lower()
        if not want:
            return False
        found: list = []
        proto = self.ct.WINFUNCTYPE(self.wt.BOOL, self.wt.HWND, self.wt.LPARAM)

        def each(hwnd, _lparam):
            if self.user32.IsWindowVisible(hwnd) and self.user32.GetWindowTextLengthW(hwnd) > 0:
                proc = self._proc_name(hwnd)
                if proc and (proc == want or want in proc or proc in want):
                    found.append(hwnd)
                    return False
            return True
        self.user32.EnumWindows(proto(each), 0)
        if not found:
            return False
        hwnd = found[0]
        self.user32.ShowWindow(hwnd, 9)              # SW_RESTORE: un-minimise
        self.user32.BringWindowToTop(hwnd)
        if self.user32.SetForegroundWindow(hwnd):
            return True
        # Windows only lets the foreground process change the foreground window; a lone Alt tap lifts that lock.
        self.user32.keybd_event(VK["alt"], 0, 0, 0)
        self.user32.keybd_event(VK["alt"], 0, 2, 0)
        return bool(self.user32.SetForegroundWindow(hwnd))

    def apps(self) -> list:
        out = []
        proto = self.ct.WINFUNCTYPE(self.wt.BOOL, self.wt.HWND, self.wt.LPARAM)

        def each(hwnd, _lparam):
            if self.user32.IsWindowVisible(hwnd) and self.user32.GetWindowTextLengthW(hwnd) > 0:
                out.append("%s - %s" % (self._proc_name(hwnd), self._title(hwnd)[:80]))
            return True
        self.user32.EnumWindows(proto(each), 0)
        return sorted(set(out))[:60]

    def open_app(self, name: str) -> str:
        raw = str(name or "").strip()
        exe = WIN_APPS.get(raw.lower(), raw)
        path = Path(os.path.expandvars(exe))
        if path.is_file() and path.suffix.lower() in (".exe", ".lnk"):
            os.startfile(str(path))   # noqa: S606 - an existing program the owner approved
            return str(path)
        found = shutil.which(exe) or shutil.which(exe + ".exe")
        if not found:
            raise RuntimeError("cannot find the program %r - give its .exe name (e.g. notepad) or full path" % raw)
        subprocess.Popen([found], close_fds=True)   # noqa: S603 - argument list, no shell
        return found

    # ---- accessibility tree (UI Automation)
    def _load_uia(self):
        if self._uia is not None or self._uia_error:
            return self._uia
        try:
            import comtypes.client  # pylint: disable=import-outside-toplevel
            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen import UIAutomationClient as UIA  # pylint: disable=import-outside-toplevel
            self._uia = (comtypes.client.CreateObject(UIA.CUIAutomation._reg_clsid_, interface=UIA.IUIAutomation), UIA)
        except Exception as exc:  # noqa: BLE001
            self._uia_error = "pip install comtypes (%s)" % type(exc).__name__
        return self._uia

    def elements(self, limit: int = 400) -> list:
        loaded = self._load_uia()
        hwnd = self.user32.GetForegroundWindow()
        if not loaded or not hwnd:
            return []
        uia, UIA = loaded
        root = uia.ElementFromHandle(hwnd)
        walker = uia.ControlViewWalker
        out, deadline = [], time.time() + 4.0
        stack = [(root, 0)]
        while stack and len(out) < limit and time.time() < deadline:
            node, depth = stack.pop()
            try:
                ctype = int(node.CurrentControlType)
                rect = node.CurrentBoundingRectangle
                name = str(node.CurrentName or "")
                offscreen = bool(node.CurrentIsOffscreen)
                enabled = bool(node.CurrentIsEnabled)
            except Exception:  # noqa: BLE001 - an element that went away
                continue
            w, h = rect.right - rect.left, rect.bottom - rect.top
            if depth > 0 and not offscreen and w > 0 and h > 0:
                value = ""
                if ctype in (50004, 50030):
                    try:
                        pat = node.GetCurrentPattern(10002)    # ValuePattern
                        value = str(pat.QueryInterface(UIA.IUIAutomationValuePattern).CurrentValue or "")[:200]
                    except Exception:  # noqa: BLE001
                        value = ""
                role = UIA_TYPES.get(ctype, "custom")
                if name or value or ctype in UIA_INTERACTIVE:
                    out.append({"role": role, "name": name[:120], "value": value, "x": rect.left, "y": rect.top,
                                "w": w, "h": h, "enabled": enabled, "interactive": ctype in UIA_INTERACTIVE})
            if depth < 30:
                try:
                    child = walker.GetFirstChildElement(node)
                    kids = []
                    while child is not None and len(kids) < 300:
                        kids.append(child)
                        child = walker.GetNextSiblingElement(child)
                    stack.extend((k, depth + 1) for k in reversed(kids))
                except Exception:  # noqa: BLE001
                    pass
        return out


# ============================================================================ macOS
MAC_KEYS = {"enter": 36, "tab": 48, "space": 49, "backspace": 51, "esc": 53, "delete": 117, "left": 123, "right": 124,
            "down": 125, "up": 126, "home": 115, "end": 119, "pageup": 116, "pagedown": 121, "cmd": 55, "shift": 56,
            "capslock": 57, "alt": 58, "ctrl": 59,
            "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100, "f9": 101, "f10": 109,
            "f11": 103, "f12": 111}
MAC_LETTERS = {"a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12, "w": 13,
               "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "9": 25, "7": 26,
               "8": 28, "0": 29, "o": 31, "u": 32, "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45, "m": 46}
MAC_FLAGS = {"cmd": 0x100000, "shift": 0x20000, "ctrl": 0x40000, "alt": 0x80000, "win": 0x100000}
AX_ROLES = {"AXButton": "button", "AXLink": "link", "AXTextField": "field", "AXTextArea": "field", "AXSearchField": "field",
            "AXSecureTextField": "field", "AXCheckBox": "checkbox", "AXRadioButton": "radio", "AXPopUpButton": "combobox",
            "AXComboBox": "combobox", "AXMenuItem": "menuitem", "AXMenuBarItem": "menuitem", "AXMenuButton": "button",
            "AXTab": "tab", "AXRow": "listitem", "AXCell": "cell", "AXSlider": "slider", "AXIncrementor": "spinner",
            "AXDisclosureTriangle": "button", "AXStaticText": "text", "AXImage": "image", "AXWebArea": "document",
            "AXGroup": "group", "AXWindow": "window", "AXToolbar": "toolbar", "AXScrollBar": "scrollbar"}


class MacBackend(Backend):
    name = "macos"

    def __init__(self) -> None:
        import ctypes  # pylint: disable=import-outside-toplevel
        self.ct = ctypes
        self.cg = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        self.cf = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")

        class CGPoint(ctypes.Structure):
            _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

        class CGSize(ctypes.Structure):
            _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]

        class CGRect(ctypes.Structure):
            _fields_ = [("origin", CGPoint), ("size", CGSize)]
        self.CGPoint, self.CGSize, self.CGRect = CGPoint, CGSize, CGRect
        vp, cg, cf = ctypes.c_void_p, self.cg, self.cf
        cg.CGEventCreateMouseEvent.restype = vp
        cg.CGEventCreateMouseEvent.argtypes = [vp, ctypes.c_uint32, CGPoint, ctypes.c_uint32]
        cg.CGEventCreateKeyboardEvent.restype = vp
        cg.CGEventCreateKeyboardEvent.argtypes = [vp, ctypes.c_uint16, ctypes.c_bool]
        cg.CGEventCreateScrollWheelEvent2.restype = vp
        cg.CGEventCreateScrollWheelEvent2.argtypes = [vp, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int32,
                                                      ctypes.c_int32, ctypes.c_int32]
        cg.CGEventPost.argtypes = [ctypes.c_uint32, vp]
        cg.CGEventSetFlags.argtypes = [vp, ctypes.c_uint64]
        cg.CGEventSetIntegerValueField.argtypes = [vp, ctypes.c_uint32, ctypes.c_int64]
        cg.CGEventKeyboardSetUnicodeString.argtypes = [vp, ctypes.c_ulong, ctypes.POINTER(ctypes.c_uint16)]
        cg.CGEventCreate.restype = vp
        cg.CGEventCreate.argtypes = [vp]
        cg.CGEventGetLocation.restype = CGPoint
        cg.CGEventGetLocation.argtypes = [vp]
        cg.CGMainDisplayID.restype = ctypes.c_uint32
        cg.CGDisplayBounds.restype = CGRect
        cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
        cg.CGEventSourceKeyState.restype = ctypes.c_bool
        cg.CGEventSourceKeyState.argtypes = [ctypes.c_int32, ctypes.c_uint16]
        cg.CGEventSourceFlagsState.restype = ctypes.c_uint64
        cg.CGEventSourceFlagsState.argtypes = [ctypes.c_int32]
        cg.AXIsProcessTrusted.restype = ctypes.c_bool
        cg.AXUIElementCreateSystemWide.restype = vp
        cg.AXUIElementCreateApplication.restype = vp
        cg.AXUIElementCreateApplication.argtypes = [ctypes.c_int]
        cg.AXUIElementCopyAttributeValue.restype = ctypes.c_int32
        cg.AXUIElementCopyAttributeValue.argtypes = [vp, vp, ctypes.POINTER(vp)]
        cg.AXUIElementGetPid.argtypes = [vp, ctypes.POINTER(ctypes.c_int)]
        cg.AXUIElementSetMessagingTimeout.argtypes = [vp, ctypes.c_float]
        cg.AXValueGetValue.restype = ctypes.c_bool
        cg.AXValueGetValue.argtypes = [vp, ctypes.c_uint32, vp]
        cg.AXValueGetTypeID.restype = ctypes.c_ulong
        cf.CFRelease.argtypes = [vp]
        cf.CFGetTypeID.restype = ctypes.c_ulong
        cf.CFGetTypeID.argtypes = [vp]
        cf.CFStringGetTypeID.restype = ctypes.c_ulong
        cf.CFArrayGetTypeID.restype = ctypes.c_ulong
        cf.CFBooleanGetTypeID.restype = ctypes.c_ulong
        cf.CFBooleanGetValue.restype = ctypes.c_bool
        cf.CFBooleanGetValue.argtypes = [vp]
        cf.CFStringCreateWithCString.restype = vp
        cf.CFStringCreateWithCString.argtypes = [vp, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFStringGetLength.restype = ctypes.c_long
        cf.CFStringGetLength.argtypes = [vp]
        cf.CFStringGetCString.restype = ctypes.c_bool
        cf.CFStringGetCString.argtypes = [vp, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
        cf.CFArrayGetCount.restype = ctypes.c_long
        cf.CFArrayGetCount.argtypes = [vp]
        cf.CFArrayGetValueAtIndex.restype = vp
        cf.CFArrayGetValueAtIndex.argtypes = [vp, ctypes.c_long]
        self._strings: dict = {}
        bounds = cg.CGDisplayBounds(cg.CGMainDisplayID())
        self.points = (int(bounds.size.width), int(bounds.size.height))
        self.scale = 1.0

    def available(self) -> tuple:
        if not self.cg.AXIsProcessTrusted():
            return True, ("macOS: Quartz events (the accessibility tree needs Accessibility permission for the app "
                          "running LOKI: System Settings > Privacy & Security > Accessibility)")
        return True, "macOS: Quartz events + AXUIElement"

    def _cfstr(self, text: str):
        if text not in self._strings:
            self._strings[text] = self.cf.CFStringCreateWithCString(None, text.encode(), 0x08000100)
        return self._strings[text]

    def _pystr(self, ref) -> str:
        n = self.cf.CFStringGetLength(ref)
        buf = self.ct.create_string_buffer(n * 4 + 1)
        return buf.value.decode("utf-8", "replace") if self.cf.CFStringGetCString(ref, buf, n * 4 + 1, 0x08000100) else ""

    def _attr(self, element, name: str):
        value = self.ct.c_void_p()
        err = self.cg.AXUIElementCopyAttributeValue(element, self._cfstr(name), self.ct.byref(value))
        return value.value if err == 0 else None

    def _text_attr(self, element, name: str) -> str:
        ref = self._attr(element, name)
        if not ref:
            return ""
        try:
            return self._pystr(ref) if self.cf.CFGetTypeID(ref) == self.cf.CFStringGetTypeID() else ""
        finally:
            self.cf.CFRelease(ref)

    def _geometry(self, element) -> tuple:
        pos, size = self.CGPoint(), self.CGSize()
        for name, kind, target in (("AXPosition", 1, pos), ("AXSize", 2, size)):
            ref = self._attr(element, name)
            if not ref:
                return None
            try:
                self.cg.AXValueGetValue(ref, kind, self.ct.byref(target))
            finally:
                self.cf.CFRelease(ref)
        return pos.x, pos.y, size.width, size.height

    def _app(self):
        system = self.cg.AXUIElementCreateSystemWide()
        try:
            return self._attr(system, "AXFocusedApplication")
        finally:
            self.cf.CFRelease(system)

    def frontmost(self) -> dict:
        app = self._app()
        if not app:
            # No Accessibility permission: System Events still names the front process and its pid.
            out = subprocess.run(["/usr/bin/osascript", "-e", 'tell application "System Events" to get {name, unix id} '
                                  'of first application process whose frontmost is true'], capture_output=True, text=True, timeout=5)
            name, _sep, pid = (out.stdout or "").strip().rpartition(",")
            if not name:
                name, pid = pid, ""
            return {"app": name.strip().lower(), "title": "", "pid": int(pid) if pid.strip().isdigit() else 0}
        try:
            name = self._text_attr(app, "AXTitle")
            pid = self.ct.c_int(0)
            self.cg.AXUIElementGetPid(app, self.ct.byref(pid))
            window = self._attr(app, "AXFocusedWindow")
            title = ""
            if window:
                title = self._text_attr(window, "AXTitle")
                self.cf.CFRelease(window)
            return {"app": name.lower(), "title": title, "pid": int(pid.value)}
        finally:
            self.cf.CFRelease(app)

    def elements(self, limit: int = 400) -> list:
        if not self.cg.AXIsProcessTrusted():
            return []
        app = self._app()
        if not app:
            return []
        self.cg.AXUIElementSetMessagingTimeout(app, 1.0)
        out, deadline = [], time.time() + 4.0
        window = self._attr(app, "AXFocusedWindow")
        roots = [r for r in (window,) if r]
        menubar = self._attr(app, "AXMenuBar")
        if menubar:
            roots.append(menubar)
        stack = [(r, 0) for r in reversed(roots)]
        owned = list(roots)
        try:
            while stack and len(out) < limit and time.time() < deadline:
                node, depth = stack.pop()
                role_raw = self._text_attr(node, "AXRole")
                role = AX_ROLES.get(role_raw, role_raw.replace("AX", "").lower() or "custom")
                name = self._text_attr(node, "AXTitle") or self._text_attr(node, "AXDescription")
                value = self._text_attr(node, "AXValue") if role_raw != "AXSecureTextField" else ""
                geo = self._geometry(node)
                interactive = role in INTERACTIVE_ROLES
                if depth > 0 and geo and geo[2] > 0 and geo[3] > 0 and (name or value or interactive) \
                        and not (role_raw.startswith("AXMenuItem") and depth > 3):
                    out.append({"role": role, "name": name[:120], "value": value[:200], "x": int(geo[0]), "y": int(geo[1]),
                                "w": int(geo[2]), "h": int(geo[3]), "enabled": True, "interactive": interactive})
                if depth >= 30:
                    continue
                kids = self._attr(node, "AXChildren")
                if not kids:
                    continue
                owned.append(kids)
                if self.cf.CFGetTypeID(kids) == self.cf.CFArrayGetTypeID():
                    count = min(self.cf.CFArrayGetCount(kids), 300)
                    for i in reversed(range(count)):
                        stack.append((self.cf.CFArrayGetValueAtIndex(kids, i), depth + 1))
        finally:
            for ref in owned:
                self.cf.CFRelease(ref)
            self.cf.CFRelease(app)
        return out

    def screen_size(self) -> tuple:
        return self.points

    def screenshot(self) -> bytes:
        fd, path = tempfile.mkstemp(suffix=".png", prefix="loki-screen-")
        os.close(fd)
        try:
            proc = subprocess.run(["/usr/sbin/screencapture", "-x", "-t", "png", path], capture_output=True, timeout=20)
            data = Path(path).read_bytes() if proc.returncode == 0 else b""
        finally:
            Path(path).unlink(missing_ok=True)
        if not data:
            raise RuntimeError("screencapture failed - give the app running LOKI Screen Recording permission "
                               "(System Settings > Privacy & Security > Screen Recording)")
        width, _h = png_size(data)
        self.scale = (width / self.points[0]) if self.points[0] else 1.0
        return data

    def _post(self, event) -> None:
        self.cg.CGEventPost(0, event)
        self.cf.CFRelease(event)

    def click(self, x: int, y: int, button: str = "left", count: int = 1) -> None:
        down, up, btn = {"right": (3, 4, 1), "middle": (25, 26, 2)}.get(button, (1, 2, 0))
        point = self.CGPoint(float(x), float(y))
        self._post(self.cg.CGEventCreateMouseEvent(None, 5, point, 0))      # move there first
        for i in range(max(1, int(count))):
            for kind in (down, up):
                ev = self.cg.CGEventCreateMouseEvent(None, kind, point, btn)
                self.cg.CGEventSetIntegerValueField(ev, 1, i + 1)            # kCGMouseEventClickState
                self._post(ev)
            time.sleep(0.03)

    def scroll(self, x: int, y: int, clicks: int) -> None:
        self._post(self.cg.CGEventCreateMouseEvent(None, 5, self.CGPoint(float(x), float(y)), 0))
        self._post(self.cg.CGEventCreateScrollWheelEvent2(None, 1, 1, int(clicks), 0, 0))   # line units

    def type_text(self, text: str) -> None:
        units = struct.unpack("<%dH" % (len(text.encode("utf-16-le")) // 2), text.encode("utf-16-le"))
        for i in range(0, len(units), 16):
            chunk = units[i:i + 16]
            arr = (self.ct.c_uint16 * len(chunk))(*chunk)
            for down in (True, False):
                ev = self.cg.CGEventCreateKeyboardEvent(None, 0, down)
                self.cg.CGEventKeyboardSetUnicodeString(ev, len(chunk), arr)
                self._post(ev)
            time.sleep(0.01)

    def key(self, combo: str) -> None:
        mods, key = parse_keys(combo)
        code = MAC_KEYS.get(key, MAC_LETTERS.get(key))
        if code is None:
            raise ValueError("unknown key %r" % key)
        flags = 0
        for m in mods:
            flags |= MAC_FLAGS[m]
        for down in (True, False):
            ev = self.cg.CGEventCreateKeyboardEvent(None, code, down)
            if flags:
                self.cg.CGEventSetFlags(ev, flags)
            self._post(ev)

    def cursor(self) -> tuple:
        ev = self.cg.CGEventCreate(None)
        try:
            p = self.cg.CGEventGetLocation(ev)
            return int(p.x), int(p.y)
        finally:
            self.cf.CFRelease(ev)

    def kill_pressed(self) -> bool:
        flags = self.cg.CGEventSourceFlagsState(1)
        return bool(self.cg.CGEventSourceKeyState(1, 53) and flags & MAC_FLAGS["ctrl"] and flags & MAC_FLAGS["alt"])

    def open_app(self, name: str) -> str:
        raw = str(name or "").strip()
        proc = subprocess.run(["/usr/bin/open", "-a", raw], capture_output=True, text=True, timeout=20)
        if proc.returncode != 0:
            raise RuntimeError("cannot open %r (%s)" % (raw, (proc.stderr or "").strip()[:160]))
        return raw

    def activate(self, name: str) -> bool:
        # `reopen` gives an app with no window its default one (TextEdit, Notes - what clicking the Dock icon
        # does); `activate` brings it to the front. The name is an AppleScript string literal, escaped.
        app = str(name or "").strip().replace("\\", "\\\\").replace('"', '\\"')
        if not app:
            return False
        proc = subprocess.run(["/usr/bin/osascript", "-e", 'tell application "%s" to reopen' % app,
                               "-e", 'tell application "%s" to activate' % app], capture_output=True, text=True, timeout=15)
        return proc.returncode == 0

    def apps(self) -> list:
        proc = subprocess.run(["/usr/bin/osascript", "-e", 'tell application "System Events" to get name of every '
                               'application process whose background only is false'], capture_output=True, text=True, timeout=10)
        return sorted(a.strip() for a in (proc.stdout or "").split(",") if a.strip())


# ============================================================================ Linux (xdotool)
class LinuxBackend(Backend):
    name = "linux"

    def available(self) -> tuple:
        if not os.environ.get("DISPLAY"):
            return False, "no desktop session (DISPLAY is not set)"
        if not shutil.which("xdotool"):
            return False, "install xdotool"
        return True, "Linux: xdotool (no accessibility tree; vision only)"

    def _x(self, *args: str) -> str:
        proc = subprocess.run(["xdotool", *args], capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            raise RuntimeError("xdotool %s failed: %s" % (args[0], proc.stderr.strip()[:120]))
        return proc.stdout.strip()

    def screen_size(self) -> tuple:
        parts = self._x("getdisplaygeometry").split()
        return int(parts[0]), int(parts[1])

    def screenshot(self) -> bytes:
        for argv in (["import", "-window", "root", "png:-"], ["grim", "-"]):
            if shutil.which(argv[0]):
                proc = subprocess.run(argv, capture_output=True, timeout=20)
                if proc.returncode == 0 and proc.stdout[:4] == b"\x89PNG":
                    return proc.stdout
        raise RuntimeError("no screenshot tool (install imagemagick)")

    def frontmost(self) -> dict:
        try:
            title = self._x("getactivewindow", "getwindowname")
        except RuntimeError:
            title = ""
        try:
            pid = int(self._x("getactivewindow", "getwindowpid") or 0)
        except (RuntimeError, ValueError):
            pid = 0
        return {"app": title.split(" - ")[-1].lower() if title else "", "title": title, "pid": pid}

    def activate(self, name: str) -> bool:
        try:
            self._x("search", "--onlyvisible", "--class", str(name or "").strip(), "windowactivate")
            return True
        except RuntimeError:
            return False

    def click(self, x: int, y: int, button: str = "left", count: int = 1) -> None:
        self._x("mousemove", str(int(x)), str(int(y)), "click", "--repeat", str(max(1, int(count))),
                {"right": "3", "middle": "2"}.get(button, "1"))

    def scroll(self, x: int, y: int, clicks: int) -> None:
        self._x("mousemove", str(int(x)), str(int(y)), "click", "--repeat", str(abs(int(clicks)) or 1),
                "4" if int(clicks) > 0 else "5")

    def type_text(self, text: str) -> None:
        self._x("type", "--delay", "8", "--", text)

    def key(self, combo: str) -> None:
        mods, key = parse_keys(combo)
        names = {"enter": "Return", "esc": "Escape", "backspace": "BackSpace", "pageup": "Prior", "pagedown": "Next",
                 "up": "Up", "down": "Down", "left": "Left", "right": "Right", "home": "Home", "end": "End",
                 "delete": "Delete", "tab": "Tab", "space": "space"}
        mod_names = {"ctrl": "ctrl", "alt": "alt", "shift": "shift", "cmd": "super", "win": "super"}
        self._x("key", "+".join([mod_names[m] for m in mods] + [names.get(key, key)]))

    def cursor(self) -> tuple:
        out = dict(p.split("=") for p in self._x("getmouselocation", "--shell").split() if "=" in p)
        return int(out.get("X", -1)), int(out.get("Y", -1))

    def open_app(self, name: str) -> str:
        exe = shutil.which(str(name or "").strip().lower())
        if not exe:
            raise RuntimeError("cannot find %r" % name)
        subprocess.Popen([exe], close_fds=True)   # noqa: S603
        return exe


# ============================================================================ tests
class FakeBackend(Backend):
    """A pretend desktop for the tests: an app, a tree, a recorder of every action."""
    name = "fake"

    def __init__(self, app: str = "notepad", title: str = "Untitled - Notepad", elements: list | None = None) -> None:
        self.app, self.title = app, title
        self.tree = list(elements if elements is not None else [
            {"role": "menuitem", "name": "File", "value": "", "x": 0, "y": 30, "w": 40, "h": 20, "enabled": True, "interactive": True},
            {"role": "field", "name": "Text editor", "value": "", "x": 0, "y": 60, "w": 800, "h": 500, "enabled": True, "interactive": True},
            {"role": "button", "name": "Close", "value": "", "x": 760, "y": 0, "w": 40, "h": 30, "enabled": True, "interactive": True},
        ])
        self.actions: list = []
        self.pos = (400, 300)
        self.kill = False
        self.opened: list = []
        self.pid = 4_194_401          # above Linux's pid_max: never a real process
        self.comes_forward = True    # False: an opened app stays behind (like TextEdit with no window)
        self.activated: list = []

    def available(self) -> tuple:
        return True, "fake desktop"

    def screen_size(self) -> tuple:
        return 800, 600

    def screenshot(self) -> bytes:
        return encode_png(8, 6, bytes(8 * 6 * 3))

    def elements(self, limit: int = 400) -> list:
        return [dict(e) for e in self.tree[:limit]]

    def frontmost(self) -> dict:
        return {"app": self.app, "title": self.title, "pid": self.pid}

    def click(self, x, y, button="left", count=1):
        self.pos = (x, y)
        self.actions.append(("click", int(x), int(y), button, count))

    def type_text(self, text):
        self.actions.append(("type", text))
        for e in self.tree:
            if e["role"] == "field":
                e["value"] = (e.get("value") or "") + text
                break

    def key(self, combo):
        parse_keys(combo)
        self.actions.append(("key", combo))

    def scroll(self, x, y, clicks):
        self.actions.append(("scroll", int(x), int(y), int(clicks)))

    def cursor(self):
        return self.pos

    def open_app(self, name):
        self.opened.append(name)
        if self.comes_forward:
            self.app, self.title, self.pid = str(name).lower(), str(name), 4_195_000 + len(self.opened)
        return name

    def activate(self, name):
        self.activated.append(name)
        if self.comes_forward is None:      # None: comes forward only when activated
            self.app, self.title, self.pid = str(name).lower(), str(name), 4_196_000
            return True
        return False

    def apps(self):
        return [self.app]

    def kill_pressed(self):
        return self.kill


def detect() -> Backend:
    """The backend for this machine (a Backend that says why when nothing works)."""
    try:
        if sys.platform == "win32":
            return WindowsBackend()
        if sys.platform == "darwin":
            return MacBackend()
        return LinuxBackend()
    except Exception as exc:  # noqa: BLE001 - e.g. a missing system library
        backend = Backend()
        backend.available = lambda: (False, "computer use cannot start here: %s" % exc)   # type: ignore[method-assign]
        return backend
