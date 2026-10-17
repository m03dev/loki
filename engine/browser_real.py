"""A real Chromium for `browse_page`, through Playwright when it is installed - pages that need JavaScript.

Small models do not do pixels or CSS selectors, so this browser shows a page exactly like the text browser
(engine/text_browser.py, browser-use / page-agent format): the page's text with its interactive elements
NUMBERED, `[12]<button type=submit>Search />`, `*[i]` for elements new since the last view. The numbers are
written into the live page (data-loki-idx), so `click index=12` clicks that element - the idea of Playwright
MCP's accessibility-snapshot refs (github.com/microsoft/playwright-mcp, Apache-2.0; no code copied).

Safety: a fresh, private browser profile per session (none of the owner's cookies or logins), headless unless
LOKI_BROWSER_HEADED=1, downloads off, requests to this computer or the local network blocked at the network
layer (the same rule as every LOKI fetch), and anything that would SEND something - clicking a submit button
of a POST form, typing into a password field, pressing Enter in a POST form - asks the owner first and is
refused in a background job.

Playwright's sync API lives in ONE worker thread (its objects belong to the thread that made them); the
agent's async loop hands work to it with asyncio.to_thread.
"""
from __future__ import annotations

import os
import queue
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

PAGE_LINES = 120
MAX_SESSIONS = 3
NAV_TIMEOUT_MS = 30000

SNAPSHOT_JS = r"""
() => {
  const INTER = new Set(['a','button','input','select','textarea','summary','details']);
  const ROLES = new Set(['button','link','menuitem','option','radio','checkbox','tab','textbox','combobox','slider',
                         'spinbutton','search','searchbox','listbox','switch','treeitem']);
  const ATTRS = ['type','name','placeholder','aria-label','title','role','href','alt','value','checked'];
  const BLOCK = new Set(['p','div','section','article','main','header','footer','nav','aside','form','table','tr','ul',
                         'ol','li','h1','h2','h3','h4','h5','h6','pre','blockquote','br','hr','dl','dt','dd','label','td','th']);
  const SKIP = new Set(['script','style','noscript','svg','template','canvas','iframe','object','embed','head']);
  document.querySelectorAll('[data-loki-idx]').forEach(e => e.removeAttribute('data-loki-idx'));
  let idx = 0, buf = '';
  const lines = [];
  const visible = (el) => {
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 || r.height > 0 || el.getClientRects().length > 0;
  };
  const interactive = (el, tag) => {
    if (INTER.has(tag)) {
      if (tag === 'a') return el.hasAttribute('href') || el.hasAttribute('onclick');
      if (tag === 'input' && (el.type || '').toLowerCase() === 'hidden') return false;
      return !el.disabled;
    }
    const role = (el.getAttribute('role') || '').toLowerCase();
    if (ROLES.has(role)) return true;
    if (el.hasAttribute('onclick') || el.getAttribute('contenteditable') === 'true') return true;
    const ti = el.getAttribute('tabindex');
    return ti !== null && ti !== '-1' && tag !== 'div' ? true : false;
  };
  const flush = () => { const t = buf.replace(/\s+/g, ' ').trim(); if (t) lines.push(t.slice(0, 300)); buf = ''; };
  const risk = (el, tag) => {
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'input' && type === 'password') return 'password';
    const form = el.form || el.closest('form');
    if (!form) return '';
    const method = (form.getAttribute('method') || 'get').toLowerCase();
    if (method !== 'post') return '';
    if ((tag === 'button' && type !== 'button' && type !== 'reset') || (tag === 'input' && (type === 'submit' || type === 'image'))) return 'post';
    if (tag === 'input' || tag === 'textarea') return 'postfield';
    return '';
  };
  const walk = (node) => {
    if (node.nodeType === 3) { buf += node.textContent; return; }
    if (node.nodeType !== 1) return;
    const el = node, tag = el.tagName.toLowerCase();
    if (SKIP.has(tag) || el.getAttribute('aria-hidden') === 'true') return;
    if (!visible(el)) return;
    if (interactive(el, tag)) {
      flush();
      idx += 1;
      el.setAttribute('data-loki-idx', String(idx));
      const attrs = {};
      for (const a of ATTRS) { const v = el.getAttribute(a); if (v !== null && v !== '') attrs[a] = v; }
      if ((tag === 'input' || tag === 'textarea') && (el.type || '').toLowerCase() !== 'password' && el.value) attrs.value = el.value;
      if ((el.type || '').toLowerCase() === 'password') delete attrs.value;
      if (tag === 'a' && el.href) attrs.href = el.href;
      if (tag === 'select') {
        attrs.options = Array.from(el.options).slice(0, 6).map(o => (o.text || o.value).trim().slice(0, 20)).join('|') + (el.options.length > 6 ? '|...' : '');
        if (el.selectedIndex >= 0) attrs.selected = (el.options[el.selectedIndex].text || '').trim();
      }
      if ((tag === 'input') && (el.type === 'checkbox' || el.type === 'radio')) { if (el.checked) attrs.checked = 'checked'; else delete attrs.checked; }
      const text = (tag === 'select' || tag === 'input') ? '' : (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 80);
      lines.push({i: idx, tag, attrs, text, risk: risk(el, tag), key: tag + '|' + (attrs.href || attrs.name || text)});
      return;
    }
    const block = BLOCK.has(tag);
    if (block) flush();
    for (const c of el.childNodes) walk(c);
    if (el.shadowRoot) for (const c of el.shadowRoot.childNodes) walk(c);
    if (block) flush();
  };
  if (document.body) walk(document.body);
  flush();
  return {title: document.title, url: location.href, lines: lines.slice(0, 2000)};
}
"""


def _cap(text: str, n: int = 40) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= n else text[:n - 3] + "..."


def render_line(item: dict, new: bool, page_url: str = "") -> str:
    attrs = dict(item.get("attrs") or {})
    href = attrs.get("href")
    if href and page_url:
        try:
            from urllib.parse import urlparse  # pylint: disable=import-outside-toplevel
            a, b = urlparse(href), urlparse(page_url)
            if a.netloc == b.netloc:
                attrs["href"] = (a.path or "/") + (("?" + a.query) if a.query else "")
        except ValueError:
            pass
    text = item.get("text", "")
    for key in ("aria-label", "title", "placeholder"):
        if key in attrs and attrs[key].strip().lower() == text.strip().lower():
            del attrs[key]
    attr_text = " ".join("%s=%s" % (k, _cap(v)) for k, v in attrs.items())
    line = "%s[%d]<%s" % ("*" if new else "", item["i"], item["tag"])
    if attr_text:
        line += " " + attr_text
    if text:
        line += (">" if attr_text else " >") + text
    return line + " />"


class _Worker:
    """One thread that owns Playwright; work goes in as callables."""

    def __init__(self, launcher: Callable | None = None) -> None:
        self.q: queue.Queue = queue.Queue()
        self.launcher = launcher
        self.thread = threading.Thread(target=self._loop, daemon=True, name="loki-chromium")
        self.state: dict = {}
        self.thread.start()

    def _loop(self) -> None:
        while True:
            fn, box, done = self.q.get()
            try:
                box["value"] = fn(self.state)
            except Exception as exc:  # noqa: BLE001
                box["error"] = exc
            done.set()

    def run(self, fn: Callable, timeout: float = 90.0):
        box: dict = {}
        done = threading.Event()
        self.q.put((fn, box, done))
        if not done.wait(timeout):
            raise TimeoutError("the browser did not answer in %d s" % timeout)
        if "error" in box:
            raise box["error"]
        return box.get("value")


class ChromiumBrowser:
    def __init__(self, allow: Callable[[str], bool] | None = None, headed: bool | None = None,
                 launcher: Callable | None = None, workspace: Path | None = None) -> None:
        self.allow = allow or (lambda url: True)
        self.headed = (os.getenv("LOKI_BROWSER_HEADED") == "1") if headed is None else headed
        self.launcher = launcher        # tests: a function(state) that puts a fake "browser" in state
        self.workspace = Path(workspace or os.getenv("LOKI_WORKSPACE") or ".")
        self._worker: _Worker | None = None
        self.sessions: dict = {}         # name -> {"page", "context", "snap", "prev", "offset", "used"}
        self._available: tuple | None = None

    # ------------------------------------------------------------------ setup
    def available(self, refresh: bool = False) -> tuple:
        if self._available is not None and not refresh:
            return self._available
        if self.launcher is not None:
            self._available = (True, "test browser")
            return self._available
        try:
            import playwright.sync_api  # noqa: F401  pylint: disable=import-outside-toplevel,unused-import
        except ImportError:
            self._available = (False, "Playwright is not installed (Settings > Add-ons > Chromium browser, or "
                                      "pip install playwright && python -m playwright install chromium)")
            return self._available
        try:
            path = self.worker().run(lambda st: self._ensure(st).chromium.executable_path, timeout=60)
            ok = bool(path) and Path(path).exists()
            self._available = (ok, "Chromium ready" if ok else "run: python -m playwright install chromium")
        except Exception as exc:  # noqa: BLE001
            self._available = (False, "Chromium could not start: %s" % str(exc)[:160])
        return self._available

    def worker(self) -> _Worker:
        if self._worker is None:
            self._worker = _Worker()
        return self._worker

    def _ensure(self, st: dict):
        if "pw" not in st:
            from playwright.sync_api import sync_playwright  # pylint: disable=import-outside-toplevel
            st["pw"] = sync_playwright().start()
        return st["pw"]

    def _browser(self, st: dict):
        if self.launcher is not None:
            if "browser" not in st:
                st["browser"] = self.launcher(st)
            return st["browser"]
        if "browser" not in st or not st["browser"].is_connected():
            st["browser"] = self._ensure(st).chromium.launch(
                headless=not (self.headed or os.getenv("LOKI_BROWSER_HEADED") == "1"))
        return st["browser"]

    def _session(self, st: dict, name: str) -> dict:
        name = str(name or "default")[:40]
        sess = self.sessions.get(name)
        if sess is not None:
            sess["used"] = time.time()
            return sess
        if len(self.sessions) >= MAX_SESSIONS:
            oldest = min(self.sessions, key=lambda k: self.sessions[k]["used"])
            try:
                self.sessions.pop(oldest)["context"].close()
            except Exception:  # noqa: BLE001
                pass
        context = self._browser(st).new_context(accept_downloads=False, java_script_enabled=True,
                                                viewport={"width": 1280, "height": 900})
        allow = self.allow

        def guard(route, request) -> None:
            url = request.url
            if url.startswith(("http://", "https://")) and not allow(url):
                route.abort()
            else:
                route.continue_()
        try:
            context.route("**/*", guard)
        except Exception:  # noqa: BLE001 - a fake context in the tests
            pass
        page = context.new_page()
        sess = {"context": context, "page": page, "snap": None, "prev": set(), "offset": 0, "used": time.time()}
        self.sessions[name] = sess
        return sess

    # ------------------------------------------------------------------ view
    def _snap(self, sess: dict) -> dict:
        page = sess["page"]
        try:
            page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        snap = page.evaluate(SNAPSHOT_JS)
        if sess.get("snap") is not None:
            sess["prev"] = {l["key"] for l in sess["snap"]["lines"] if isinstance(l, dict)}
        sess["snap"] = snap
        sess["offset"] = 0
        return snap

    def view(self, sess: dict) -> str:
        snap = sess.get("snap")
        if not snap:
            return "error: no page open - use action='open' with a url"
        prev = sess.get("prev") or set()
        rows = [render_line(l, bool(prev) and l["key"] not in prev, snap.get("url", "")) if isinstance(l, dict) else l
                for l in snap["lines"]]
        total = len(rows)
        start = min(sess.get("offset", 0), max(0, total - 1))
        window = rows[start:start + PAGE_LINES]
        n_el = sum(1 for l in snap["lines"] if isinstance(l, dict))
        header = "Current Page (Chromium): [%s](%s)\n%d interactive elements; lines %d-%d of %d" % (
            snap.get("title") or snap.get("url"), snap.get("url"), n_el, start + 1 if total else 0, start + len(window), total)
        above = "[Start of page]" if start == 0 else "... %d lines above - action='scroll' direction='up' ..." % start
        below_n = total - (start + len(window))
        below = "[End of page]" if below_n <= 0 else "... %d more lines below - action='scroll' to see more ..." % below_n
        hint = ("Use: click index=N, type index=N text=..., select index=N text=option, submit index=N (Enter), "
                "key text='Escape', scroll, back, find text=..., open url=..., screenshot. *[N] = new since the last view.")
        return "%s\n\n%s\n%s\n%s\n\n%s" % (header, above, "\n".join(window), below, hint)

    def _item(self, sess: dict, index) -> dict | str:
        snap = sess.get("snap")
        if not snap:
            return "error: no page open"
        try:
            i = int(index)
        except (TypeError, ValueError):
            return "error: give the element's number (index)"
        for l in snap["lines"]:
            if isinstance(l, dict) and l["i"] == i:
                return l
        return "error: there is no element [%s] on this page - action='view' shows the current numbers" % index

    # ------------------------------------------------------------------ actions
    def risky(self, name: str, action: str, index=None) -> str:
        """Why this step would send something (needs the owner), or ""."""
        sess = self.sessions.get(str(name or "default")[:40])
        if sess is None or not sess.get("snap") or index in (None, ""):
            return ""
        item = self._item(sess, index)
        if isinstance(item, str):
            return ""
        host = re.sub(r"^https?://([^/]+).*$", r"\1", sess["snap"].get("url", ""))
        if action in ("type", "input", "fill") and item.get("risk") == "password":
            return "type a password into %s" % host
        if action in ("click", "submit") and item.get("risk") == "post":
            return "submit a form on %s (it sends something: a sign-up, an order, a message)" % host
        if action == "submit" and item.get("risk") in ("postfield", "password"):
            return "submit a form on %s" % host
        return ""

    def act(self, action: str, url: str = "", index=None, text: str = "", direction: str = "down", name: str = "default") -> str:
        action = str(action or "view").strip().lower()

        def step(st: dict) -> str:
            sess = self._session(st, name)
            page = sess["page"]
            if action in ("open", "goto", "navigate", "visit"):
                target = str(url or "").strip()
                if not target:
                    return "error: give a url"
                if not re.match(r"^https?://", target):
                    target = "https://" + target
                if not self.allow(target):
                    return "error: %s is on this computer or the local network; the browser only opens public pages" % target
                try:
                    page.goto(target, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                except Exception as exc:  # noqa: BLE001
                    return "error: could not open %s (%s)" % (target, str(exc).splitlines()[0][:160])
                self._snap(sess)
                return self.view(sess)
            if action in ("view", "state", "show"):
                if sess.get("snap") is None:
                    return "error: no page open - use action='open' with a url"
                self._snap(sess)
                return self.view(sess)
            if action == "scroll":
                if sess.get("snap") is None:
                    return "error: no page open"
                step_n = PAGE_LINES - 10
                sess["offset"] = max(0, sess["offset"] - step_n) if str(direction).lower().startswith("u") else sess["offset"] + step_n
                return self.view(sess)
            if action == "back":
                try:
                    page.go_back(wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                except Exception as exc:  # noqa: BLE001
                    return "error: could not go back (%s)" % str(exc)[:120]
                self._snap(sess)
                return self.view(sess)
            if action in ("find", "search_page"):
                if sess.get("snap") is None:
                    return "error: no page open"
                want = str(text or "").lower()
                lines = [render_line(l, False) if isinstance(l, dict) else l for l in sess["snap"]["lines"]]
                hits = [i for i, r in enumerate(lines) if want and want in r.lower()]
                if not hits:
                    return "%r is not on this page" % text
                sess["offset"] = max(0, hits[0] - 5)
                return "found %r on %d line(s); showing from the first:\n\n%s" % (text, len(hits), self.view(sess))
            if action in ("key", "press"):
                page.keyboard.press(str(text or "Enter"))
                page.wait_for_timeout(400)
                self._snap(sess)
                return self.view(sess)
            if action == "screenshot":
                folder = self.workspace / "screens"
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / ("browser-%s.png" % time.strftime("%Y%m%d-%H%M%S"))
                page.screenshot(path=str(path))
                return "screenshot saved: screens/%s - ask about it with view_image filename='screens/%s'" % (path.name, path.name)
            item = self._item(sess, index)
            if isinstance(item, str):
                return item
            loc = page.locator('[data-loki-idx="%d"]' % item["i"]).first
            try:
                if action == "click":
                    loc.click(timeout=10000)
                elif action in ("type", "input", "fill"):
                    loc.fill(str(text or ""), timeout=10000)
                    return "typed into [%d]: %s\nNext: submit index=%d (Enter) or click the form's button." % (
                        item["i"], render_line(item, False), item["i"])
                elif action == "select":
                    try:
                        loc.select_option(label=str(text or ""), timeout=10000)
                    except Exception:  # noqa: BLE001
                        loc.select_option(value=str(text or ""), timeout=10000)
                    return "selected %r in [%d]" % (text, item["i"])
                elif action in ("submit", "enter"):
                    loc.press("Enter", timeout=10000)
                else:
                    return ("error: unknown action %r (open, view, click, type, select, submit, key, scroll, back, find, "
                            "screenshot)" % action)
            except Exception as exc:  # noqa: BLE001
                return "error: [%d] could not be used (%s). action='view' to refresh the numbers." % (item["i"], str(exc).splitlines()[0][:160])
            try:
                page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(300)
            self._snap(sess)
            return self.view(sess)

        try:
            return self.worker().run(step) if self.launcher is None else self._run_inline(step)
        except TimeoutError as exc:
            return "error: %s" % exc
        except Exception as exc:  # noqa: BLE001
            return "error: the Chromium browser failed: %s" % str(exc).splitlines()[0][:200]

    def _run_inline(self, step: Callable) -> Any:
        st = getattr(self, "_inline_state", None)
        if st is None:
            st = self._inline_state = {}
        return step(st)

    def close(self) -> None:
        def stop(st: dict) -> None:
            for sess in list(self.sessions.values()):
                try:
                    sess["context"].close()
                except Exception:  # noqa: BLE001
                    pass
            self.sessions.clear()
            if "browser" in st:
                try:
                    st["browser"].close()
                except Exception:  # noqa: BLE001
                    pass
        if self._worker is not None:
            try:
                self._worker.run(stop, timeout=20)
            except Exception:  # noqa: BLE001
                pass


JS_HINTS = ("shows almost nothing without JavaScript", "needs JavaScript")
_ENGINE_OF: dict = {}          # session name -> "text" | "chromium"
BROWSER: ChromiumBrowser | None = None


def default(allow: Callable | None = None, workspace: Path | None = None) -> ChromiumBrowser:
    global BROWSER
    if BROWSER is None:
        BROWSER = ChromiumBrowser(allow=allow, workspace=workspace)
    elif allow is not None:
        BROWSER.allow = allow
    return BROWSER


def mode() -> str:
    """LOKI_BROWSER: auto (text first, Chromium when a page needs JavaScript), text, or chromium."""
    m = str(os.getenv("LOKI_BROWSER", "auto")).strip().lower()
    return m if m in ("auto", "text", "chromium") else "auto"


def choose(name: str, action: str, engine: str = "") -> str:
    """Which engine runs this step for session `name`."""
    engine = str(engine or "").strip().lower()
    if engine in ("text", "chromium"):
        if action in ("open", "goto", "navigate", "visit"):
            _ENGINE_OF[name] = engine
        return engine
    if mode() != "auto":
        return mode()
    if action in ("open", "goto", "navigate", "visit"):
        _ENGINE_OF[name] = "text"
        return "text"
    return _ENGINE_OF.get(name, "text")


def needs_js(result: str) -> bool:
    return any(h in str(result or "") for h in JS_HINTS)


def switch(name: str, engine: str) -> None:
    _ENGINE_OF[name] = engine
