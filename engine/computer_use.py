"""LOKI's `computer` tool: drive the desktop of THIS machine (the PC or the Mac) for apps without an API.

How it sees: the accessibility tree first (Windows UI Automation, macOS AXUIElement - cheap, exact,
works with text-only models): the focused window's controls come back NUMBERED,
    [3] button "Save" @(412,88)      [7] field "Search" value="cats" @(120,40)
and `find` ranks them for a description. Only when the tree has nothing usable does it fall back to
VISION: a screenshot and a vision model asked for the target's coordinates (`look` asks it to describe
the screen). Approach and sources: docs/integrations/COMPUTER_USE.md.

Safety, in this order, for every call:
  1. the `computer-use` add-on must be ON (capability with the high-risk permission computer:host;
     engine/policy.py refuses the tool otherwise and it is not even offered to the model);
  2. never from a background job unless the owner allowed it (LOKI_COMPUTER_IN_JOBS=1);
  3. the KILL SWITCH: Ctrl+Alt+Esc (both machines), the mouse pushed into the top-left corner, or the
     Stop button in Settings > Tools: every later action is refused until the owner re-arms it there;
  4. apps on the never-list (password managers, keychains; LOKI_COMPUTER_NEVER) are refused;
  5. owner approval PER APP: the first action in an app asks "LOKI wants to control <app>" (the approval
     prompt in the window); a yes holds for that app until LOKI restarts. LOKI_COMPUTER_APPS lists apps
     the owner pre-approved in Settings;
  6. LOKI never clicks, types, presses keys or scrolls into ITS OWN window (the engine, its parent - the app
     window - or LOKI_APP_PID): `open_app` brings the app to the front and checks it is there before the
     model may type, so "open TextEdit and type hello" can never end up typing into LOKI's chat box;
  7. every action is logged (harness_data/computer_log.jsonl: time, app, action, target; typed text only as
     its length and first characters, never a password field's).
"""
from __future__ import annotations

import asyncio
import difflib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

import computer_backends as cb

NEVER_DEFAULT = ("1password", "bitwarden", "lastpass", "keepass", "keepassxc", "dashlane", "keychain access",
                 "keychain", "passwords", "credential manager")
MAX_LINES = 60
TYPE_CHUNK = 24
INPUT_ACTIONS = {"click", "double_click", "right_click", "type", "write", "input", "key", "keys", "press", "hotkey",
                 "scroll"}
SELF_NAMES = {"loki", "loki studio"}
FRONT_WAIT_S = 4.0


def own_pids() -> set:
    """LOKI's own processes: the engine, the app window that started it, and LOKI_APP_PID when set."""
    pids = {os.getpid()}
    try:
        pids.add(os.getppid())
    except (AttributeError, OSError):
        pass
    raw = os.getenv("LOKI_APP_PID", "")
    if raw.strip().isdigit():
        pids.add(int(raw))
    return {p for p in pids if p and p > 1}


def is_self(front: dict) -> bool:
    """True when the front window is LOKI's own (never something to click or type into)."""
    pid = front.get("pid") or 0
    if pid and pid in own_pids():
        return True
    return str(front.get("app") or "").strip().lower() in SELF_NAMES


def _norm_app(name: str) -> str:
    n = str(name or "").strip().lower()
    for suffix in (".exe", ".app"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
    return n.replace(" ", "")


def same_app(wanted: str, front_app: str) -> bool:
    """Loose match of the app the model opened and the one in front ('TextEdit' ~ 'textedit', 'Notepad' ~ 'notepad')."""
    a, b = _norm_app(wanted), _norm_app(front_app)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    alias = {"calculator": "calc", "fileexplorer": "explorer", "wordpad": "write"}
    if alias.get(a) == b or alias.get(b) == a:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def _csv(name: str, default: tuple = ()) -> set:
    raw = os.getenv(name)
    items = default if raw is None else tuple(raw.split(","))
    return {i.strip().lower() for i in items if i.strip()}


class Computer:
    def __init__(self, backend: cb.Backend | None = None, data_dir: Path | None = None,
                 approve: Callable | None = None, vision: Callable | None = None, workspace: Path | None = None) -> None:
        self._backend = backend
        self.data_dir = Path(data_dir or os.getenv("LOKI_DATA") or ".")
        self.workspace = Path(workspace or os.getenv("LOKI_WORKSPACE") or self.data_dir / "workspace")
        self.approve = approve            # async (kind, detail, decidable) -> bool
        self.vision = vision              # async (png_bytes, prompt) -> str
        self.armed = True
        self.tripped_reason = ""
        self.approved: set = set()
        self.last: list = []              # the numbered elements of the last look at the tree
        self.last_app = ""
        self.watching = False
        self.last_action_t = 0.0

    # ------------------------------------------------------------------ state
    @property
    def backend(self) -> cb.Backend:
        if self._backend is None:
            self._backend = cb.detect()
        return self._backend

    def log_path(self) -> Path:
        return self.data_dir / "computer_log.jsonl"

    def log(self, action: str, app: str, target: str = "", ok: bool = True, note: str = "") -> None:
        entry = {"t": round(time.time(), 3), "action": action, "app": app, "target": str(target)[:160], "ok": ok}
        if note:
            entry["note"] = str(note)[:200]
        try:
            self.log_path().parent.mkdir(parents=True, exist_ok=True)
            with self.log_path().open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except OSError:
            pass

    def recent(self, n: int = 30) -> list:
        try:
            lines = self.log_path().read_text(encoding="utf-8").splitlines()[-n:]
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def trip(self, reason: str) -> None:
        if self.armed:
            self.armed = False
            self.tripped_reason = reason
            self.log("kill-switch", self.last_app, reason, ok=False)
            try:
                import events  # pylint: disable=import-outside-toplevel
                events.emit("computer.stopped", "LOKI", {"reason": reason})
            except Exception:  # noqa: BLE001
                pass

    def arm(self) -> None:
        self.armed, self.tripped_reason = True, ""
        self.log("re-armed", "", "owner")

    def forget_approvals(self) -> None:
        self.approved.clear()

    def state(self) -> dict:
        ok, detail = self.backend.available()
        return {"armed": self.armed, "tripped": self.tripped_reason, "backend": self.backend.name, "available": ok,
                "detail": detail, "approved_apps": sorted(self.approved), "preapproved": sorted(_csv("LOKI_COMPUTER_APPS")),
                "never": sorted(_csv("LOKI_COMPUTER_NEVER", NEVER_DEFAULT)), "in_jobs": os.getenv("LOKI_COMPUTER_IN_JOBS") == "1",
                "kill_hotkey": "Ctrl+Alt+Esc (or push the mouse into the top-left corner)", "log": self.recent(15)}

    def _watch(self) -> None:
        """Poll the kill hotkey while computer use is active (stops after 10 idle minutes)."""
        if self.watching:
            return
        self.watching = True

        started = time.time()

        def loop() -> None:
            try:
                while self.armed and time.time() - max(self.last_action_t, started) < 600:
                    try:
                        if self.backend.kill_pressed():
                            self.trip("kill hotkey pressed")
                            break
                    except Exception:  # noqa: BLE001
                        break
                    time.sleep(0.1)
            finally:
                self.watching = False
        threading.Thread(target=loop, daemon=True, name="loki-computer-kill").start()

    # ------------------------------------------------------------------ gates
    def _gate(self) -> str:
        if os.getenv("LOKI_JOB_ID") and os.getenv("LOKI_COMPUTER_IN_JOBS") != "1":
            return ("DENIED: computer use never runs in a background job (nobody is watching). Ask the owner, or "
                    "they can allow it in Settings > Tools > Computer use.")
        if not self.armed:
            return ("DENIED: the computer-use kill switch is on (%s). The owner re-arms it in Settings > Tools > "
                    "Computer use. Do not retry." % (self.tripped_reason or "stopped"))
        ok, detail = self.backend.available()
        if not ok:
            return "error: computer use is not available on this machine: %s" % detail
        try:
            x, y = self.backend.cursor()
            if (x, y) != (-1, -1) and x <= 1 and y <= 1:
                self.trip("mouse pushed into the top-left corner")
                return "DENIED: the owner stopped computer use (mouse in the corner). Do not retry."
        except Exception:  # noqa: BLE001
            pass
        self._watch()
        return ""

    async def _allow_app(self, app: str, action: str, detail: str) -> str:
        app = (app or "the desktop").strip().lower()
        self.last_app = app
        never = _csv("LOKI_COMPUTER_NEVER", NEVER_DEFAULT)
        if any(n and (n == app or n in app) for n in never):
            self.log(action, app, detail, ok=False, note="never-list")
            return "DENIED: LOKI never controls %s (a password manager / keychain is on the never-list)." % app
        if app in self.approved or app in _csv("LOKI_COMPUTER_APPS"):
            return ""
        if self.approve is None:
            return "DENIED: nobody can approve controlling %s here." % app
        yes = await self.approve("computer", "LOKI wants to control %s on this computer (first action: %s). "
                                             "Allow for this app until LOKI restarts?" % (app, detail), False)
        if not yes:
            self.log(action, app, detail, ok=False, note="owner said no")
            return "DENIED: the owner did not allow controlling %s. Do NOT ask again; reply 'BLOCKED: <reason>'." % app
        self.approved.add(app)
        self.log("approved", app, action)
        return ""

    async def _bring_forward(self, name: str) -> dict:
        """After open_app: wait for the app to be in front; if it is not, activate it (and give it a window)."""
        front: dict = {}
        activated = False
        deadline = time.time() + FRONT_WAIT_S
        while True:
            await asyncio.sleep(0.5)
            try:
                front = self.backend.frontmost() or {}
            except Exception:  # noqa: BLE001
                front = {}
            if same_app(name, front.get("app") or ""):
                return front
            if not activated:
                activated = True
                try:
                    self.backend.activate(name)
                except Exception:  # noqa: BLE001
                    pass
                continue
            if time.time() >= deadline:
                return front

    # ------------------------------------------------------------------ the tree
    def _read_tree(self) -> list:
        try:
            raw = self.backend.elements()
        except Exception as exc:  # noqa: BLE001
            raw = []
            self.log("elements", self.last_app, "", ok=False, note=str(exc))
        items = [e for e in raw if e.get("w", 0) > 0 and e.get("h", 0) > 0]
        # interactive first, then the rest in reading order (top-to-bottom, left-to-right)
        items.sort(key=lambda e: (not e.get("interactive"), int(e.get("y", 0)) // 12, int(e.get("x", 0))))
        for i, e in enumerate(items, 1):
            e["i"] = i
        self.last = items
        return items

    @staticmethod
    def render(el: dict) -> str:
        cx, cy = int(el["x"] + el["w"] / 2), int(el["y"] + el["h"] / 2)
        line = '[%d] %s "%s"' % (el["i"], el.get("role", "?"), str(el.get("name", ""))[:80])
        if el.get("value"):
            line += ' value="%s"' % str(el["value"])[:60].replace("\n", " ")
        if not el.get("enabled", True):
            line += " (disabled)"
        return line + " @(%d,%d)" % (cx, cy)

    def elements_text(self, app: dict, items: list) -> str:
        head = "App: %s - %s\n" % (app.get("app") or "?", app.get("title") or "")
        if not items:
            return head + ("(no accessibility tree for this window - use action='look' to see it, or click text='...' "
                           "which falls back to vision)")
        lines = [self.render(e) for e in items[:MAX_LINES]]
        more = "\n... %d more (use find text='...')" % (len(items) - MAX_LINES) if len(items) > MAX_LINES else ""
        return head + "%d elements:\n%s%s\nNext: click index=N, type index=N text='...', key keys='ctrl+s'." % (
            len(items), "\n".join(lines), more)

    @staticmethod
    def score(el: dict, text: str, role: str = "") -> float:
        want = str(text or "").strip().lower()
        name = str(el.get("name", "")).lower()
        value = str(el.get("value", "")).lower()
        s = 0.0
        if want:
            if name == want:
                s = 100
            elif name.startswith(want):
                s = 80
            elif want in name:
                s = 65
            elif want and want in value:
                s = 45
            else:
                s = 50 * difflib.SequenceMatcher(None, want, name).ratio()
                if s < 30:
                    s = 0
        else:
            s = 10
        if role:
            s = s + 20 if el.get("role") == role.lower() else s - 25
        if el.get("interactive"):
            s += 5
        if not el.get("enabled", True):
            s -= 10
        return s

    def find(self, text: str, role: str = "", refresh: bool = True) -> list:
        items = self._read_tree() if refresh or not self.last else self.last
        ranked = sorted(((self.score(e, text, role), e) for e in items), key=lambda t: -t[0])
        return [e for s, e in ranked if s >= 30][:5]

    # ------------------------------------------------------------------ vision fallback
    async def locate(self, target: str) -> tuple | None:
        """Ask a vision model where `target` is on a fresh screenshot. Returns input coordinates or None."""
        if self.vision is None:
            return None
        png = self.backend.screenshot()
        width, height = cb.png_size(png)
        prompt = ("This is a %dx%d screenshot. Find: %s. Reply with ONLY a JSON object {\"x\": <int>, \"y\": <int>} - "
                  "the pixel at the CENTER of it - or {\"x\": -1, \"y\": -1} if it is not visible." % (width, height, target))
        try:
            answer = await self.vision(png, prompt)
        except Exception as exc:  # noqa: BLE001
            self.log("vision", self.last_app, target, ok=False, note=str(exc))
            return None
        m = re.search(r'"?x"?\s*[:=]\s*(-?\d+(?:\.\d+)?)\D+?"?y"?\s*[:=]\s*(-?\d+(?:\.\d+)?)', str(answer or ""))
        if not m:
            m = re.search(r"\(?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)?", str(answer or ""))
        if not m:
            return None
        x, y = float(m.group(1)), float(m.group(2))
        if x < 0 or y < 0 or (width and x > width) or (height and y > height):
            return None
        scale = getattr(self.backend, "scale", 1.0) or 1.0
        return int(x / scale), int(y / scale)

    def _el(self, index) -> dict | str:
        try:
            i = int(index)
        except (TypeError, ValueError):
            return "error: give index=N from the last elements list"
        if not self.last:
            self._read_tree()
        for e in self.last:
            if e.get("i") == i:
                return e
        return "error: there is no element [%s] (1-%d) - call action='elements' again, the window may have changed" % (index, len(self.last))

    async def _target(self, index=None, text: str = "", role: str = "", x=None, y=None) -> tuple:
        """(x, y, label) for an index, a text/role description (tree, then vision) or raw coordinates."""
        if index not in (None, "", 0, "0"):
            el = self._el(index)
            if isinstance(el, str):
                return None, None, el
            return int(el["x"] + el["w"] / 2), int(el["y"] + el["h"] / 2), self.render(el)
        if text or role:
            hits = self.find(text, role)
            if hits:
                el = hits[0]
                return int(el["x"] + el["w"] / 2), int(el["y"] + el["h"] / 2), self.render(el)
            spot = await self.locate(("the %s " % role if role else "") + (text or ""))
            if spot:
                return spot[0], spot[1], "%r found by vision @(%d,%d)" % (text or role, spot[0], spot[1])
            return None, None, ("error: nothing matches %r%s. Try action='elements' or 'look'." %
                                (text or role, "" if self.vision else " and no vision model is set (LOKI_VISION_MODEL)"))
        if x is not None and y is not None and str(x) != "" and str(y) != "":
            try:
                return int(float(x)), int(float(y)), "@(%s,%s)" % (x, y)
            except ValueError:
                pass
        return None, None, "error: say what to act on: index=N (from elements), text='Save', or x=..., y=..."

    # ------------------------------------------------------------------ the tool
    async def act(self, action: str = "elements", index=None, text: str = "", role: str = "", x=None, y=None,
                  keys: str = "", direction: str = "down", amount: int = 3, app: str = "", seconds: float = 1.0,
                  question: str = "") -> str:
        action = str(action or "elements").strip().lower().replace("-", "_")
        gate = self._gate()
        if gate:
            return gate
        try:
            front = self.backend.frontmost()
        except Exception:  # noqa: BLE001
            front = {"app": "", "title": ""}
        if action in ("open_app", "open", "launch"):
            name = str(app or text or "").strip()
            if not name:
                return "error: open_app needs app='Notepad' (Windows) or app='TextEdit' (Mac)"
            denied = await self._allow_app(name, action, "open " + name)
            if denied:
                return denied
            self.last_action_t = time.time()
            try:
                where = self.backend.open_app(name)
            except Exception as exc:  # noqa: BLE001
                self.log(action, name.lower(), name, ok=False, note=str(exc))
                return "error: %s" % exc
            self.log(action, name.lower(), where)
            front = await self._bring_forward(name)
            if not same_app(name, front.get("app") or ""):
                shown = front.get("app") or "nothing"
                if is_self(front):
                    shown = "LOKI's own window"
                self.log("front", name.lower(), "not in front", ok=False, note=shown)
                return ("opened %s, but it is NOT in front (in front: %s) - do not type or click yet. Try "
                        "action='open_app' app='%s' once more, or action='apps' to see its windows; if it stays "
                        "behind, reply 'BLOCKED: %s did not come to the front'." % (name, shown, name, name))
            return "opened %s (it is in front). Next: action='elements' to see its controls." % name
        if action == "apps":
            self.log("apps", front.get("app") or "", "list windows")
            try:
                return "open windows:\n" + "\n".join(self.backend.apps()[:60])
            except Exception as exc:  # noqa: BLE001
                return "error: %s" % exc
        if action == "wait":
            secs = max(0.1, min(float(seconds or 1), 10.0))
            await asyncio.sleep(secs)
            return "waited %.1f s" % secs
        app_name = front.get("app") or ""
        if action in INPUT_ACTIONS and is_self(front):
            self.log(action, app_name or "loki", "refused", ok=False, note="LOKI's own window is in front")
            return ("DENIED: LOKI's own window is in front - LOKI never clicks, types or presses keys into itself. "
                    "Bring the target app forward first (action='open_app' app='<the app>'), then check with "
                    "action='elements'.")
        denied = await self._allow_app(app_name, action, (text or keys or str(index or "") or action)[:80])
        if denied:
            return denied
        self.last_action_t = time.time()
        return await self._act(action, front, index, text, role, x, y, keys, direction, amount, question)

    async def _act(self, action, front, index, text, role, x, y, keys, direction, amount, question) -> str:
        app = front.get("app") or "the desktop"
        b = self.backend
        try:
            if action in ("elements", "tree", "view", "state"):
                items = self._read_tree()
                self.log("elements", app, "%d elements" % len(items))
                return self.elements_text(front, items)
            if action == "find":
                if not (text or role):
                    return "error: find needs text='...' (and optionally role='button')"
                hits = self.find(text, role)
                self.log("find", app, text or role)
                if not hits:
                    return "nothing in %s matches %r - try action='look'" % (app, text or role)
                return "best matches:\n" + "\n".join(self.render(e) for e in hits) + "\nNext: click index=N"
            if action in ("screenshot", "capture"):
                png = b.screenshot()
                folder = self.workspace / "screens"
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / ("computer-%s.png" % time.strftime("%Y%m%d-%H%M%S"))
                path.write_bytes(png)
                w, h = cb.png_size(png)
                self.log("screenshot", app, path.name)
                return "screenshot saved: screens/%s (%dx%d). Ask about it with view_image filename='screens/%s', or action='look'." % (
                    path.name, w, h, path.name)
            if action in ("look", "describe"):
                if self.vision is None:
                    return "error: no vision model for screenshots (set LOKI_VISION_MODEL, e.g. qwen2.5vl:7b in Ollama, or a vision provider)"
                png = b.screenshot()
                self.log("look", app, question or "describe")
                answer = await self.vision(png, question or "Describe this screen: the app, what is open, the main "
                                                            "buttons and fields with their labels, and any dialog or error.")
                return "Screen of %s (vision):\n%s" % (app, str(answer or "").strip()[:4000])
            if action in ("click", "double_click", "right_click"):
                cx, cy, label = await self._target(index, text, role, x, y)
                if cx is None:
                    return label
                b.click(cx, cy, "right" if action == "right_click" else "left", 2 if action == "double_click" else 1)
                self.log(action, app, label)
                await asyncio.sleep(0.4)
                return "%s %s in %s. Next: action='elements' to see the result." % (action.replace("_", " "), label, app)
            if action in ("type", "write", "input"):
                if not str(text or ""):
                    return "error: type needs text='...'"
                label = "the focused field"
                if index not in (None, "", 0, "0"):
                    cx, cy, label = await self._target(index=index)
                    if cx is None:
                        return label
                    b.click(cx, cy)
                    await asyncio.sleep(0.2)
                secret_field = "password" in label.lower() or "secure" in label.lower()
                for i in range(0, len(text), TYPE_CHUNK):
                    if not self.armed:
                        return "STOPPED: the kill switch was pressed while typing (%d of %d characters typed)." % (i, len(text))
                    b.type_text(text[i:i + TYPE_CHUNK])
                    if b.kill_pressed():
                        self.trip("kill hotkey pressed")
                self.log("type", app, label, note="%d chars%s" % (len(text), "" if secret_field else ": " + text[:20]))
                return "typed %d characters into %s in %s." % (len(text), label, app)
            if action in ("key", "keys", "press", "hotkey"):
                combo = str(keys or text or "").strip()
                mods, key = cb.parse_keys(combo)
                if set(mods) >= {"ctrl", "alt"} and key in ("delete", "del"):
                    return "DENIED: LOKI does not press Ctrl+Alt+Delete."
                b.key(combo)
                self.log("key", app, combo)
                await asyncio.sleep(0.3)
                return "pressed %s in %s." % (combo, app)
            if action == "scroll":
                cx, cy = (None, None)
                if index not in (None, "", 0, "0") or text:
                    cx, cy, _label = await self._target(index, text, role)
                if cx is None:
                    w, h = b.screen_size()
                    cx, cy = (w // 2 or 400), (h // 2 or 300)
                clicks = max(1, min(int(amount or 3), 30))
                b.scroll(cx, cy, clicks if str(direction).lower().startswith("u") else -clicks)
                self.log("scroll", app, "%s %d" % (direction, clicks))
                return "scrolled %s %d in %s." % (direction, clicks, app)
        except ValueError as exc:
            return "error: %s" % exc
        except Exception as exc:  # noqa: BLE001
            self.log(action, app, "", ok=False, note=str(exc))
            return "error: %s failed: %s" % (action, str(exc)[:200])
        return ("error: unknown action %r. Use: elements, find, click, double_click, right_click, type, key, scroll, "
                "open_app, apps, screenshot, look, wait" % action)


COMPUTER: Computer | None = None


def default(data_dir: Path | None = None, approve: Callable | None = None, vision: Callable | None = None,
            workspace: Path | None = None) -> Computer:
    global COMPUTER
    if COMPUTER is None:
        COMPUTER = Computer(data_dir=data_dir, approve=approve, vision=vision, workspace=workspace)
    else:
        if approve is not None:
            COMPUTER.approve = approve
        if vision is not None:
            COMPUTER.vision = vision
    return COMPUTER


def handle(computer: Any, route: str, data: dict) -> tuple:
    """POST /computer/stop | /computer/arm | /computer/forget; GET /computer -> state."""
    if computer is None:
        return 503, {"ok": False, "error": "computer use is not loaded"}
    if route == "/computer/stop":
        computer.trip("stopped from Settings")
    elif route == "/computer/arm":
        computer.arm()
    elif route == "/computer/forget":
        computer.forget_approvals()
    elif route != "/computer":
        return 404, {"ok": False, "error": "unknown computer endpoint"}
    return 200, {"ok": True, **computer.state()}
