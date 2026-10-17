"""A text browser for agents: open a page, see its links and form fields NUMBERED, click,
type, submit, go back - over plain HTTP, no browser, no JavaScript, nothing to install.

Ported into LOKI (session 27 harvest) from two browser agents, both MIT:
  - browser-use (github.com/browser-use/browser-use, Copyright (c) 2024 Gregor Zunic):
    dom/serializer/clickable_elements.py ClickableElementDetector.is_interactive (interactive
    tags, ARIA roles, onclick/tabindex, search-widget class/id hints, label/span wrappers of
    form controls, aria-hidden/disabled excluded), dom/views.py DEFAULT_INCLUDE_ATTRIBUTES,
    and the serializer's `[index]<tag attrs>text />` lines;
  - page-agent (github.com/alibaba/page-agent, Copyright (c) 2026 SimonLuvRamen):
    page-controller dom/index.ts (attribute values capped, duplicate attribute values and
    attributes repeating the text dropped, `*[i]` for elements new since the last view) and
    PageController.getBrowserState's header/footer ("Current Page: [title](url)", "[Start of
    page]" / "... N more lines below - scroll ..." / "[End of page]").
See engine/licenses/browser-use-MIT.txt and engine/licenses/page-agent-MIT.txt.

What it is for: a small local model can fill a search box, follow a result, page through a
listing or submit a simple form on a server-rendered site, step by step, with exact element
numbers instead of guessing selectors. Sites that need JavaScript still need the Browser Use
add-on (`conductor browse`); this says so when a page has no readable content.
"""
from __future__ import annotations

import http.cookiejar
import re
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

try:
    import web_reader
except ImportError:  # pragma: no cover
    from engine import web_reader  # type: ignore

# browser-use DEFAULT_INCLUDE_ATTRIBUTES (the ones a static page can carry)
INCLUDE_ATTRIBUTES = ["title", "type", "checked", "id", "name", "role", "value", "placeholder", "alt", "aria-label",
                      "aria-expanded", "aria-checked", "pattern", "min", "max", "minlength", "maxlength", "step",
                      "accept", "multiple", "inputmode", "autocomplete", "required", "selected", "href"]
INTERACTIVE_TAGS = {"button", "input", "select", "textarea", "a", "details", "summary", "option", "optgroup"}
INTERACTIVE_ROLES = {"button", "link", "menuitem", "option", "radio", "checkbox", "tab", "textbox", "combobox",
                     "slider", "spinbutton", "search", "searchbox", "listbox"}
INTERACTIVE_ATTRS = {"onclick", "onmousedown", "onmouseup", "onkeydown", "onkeyup", "tabindex"}
SEARCH_HINTS = ("search", "magnify", "glass", "lookup", "find", "query", "searchbox")
SKIP = {"script", "style", "noscript", "svg", "template", "canvas", "iframe", "object", "embed"}
BLOCK = {"p", "div", "section", "article", "main", "header", "footer", "nav", "aside", "form", "table", "tr", "ul",
         "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote", "br", "hr", "dl", "dt", "dd",
         "fieldset", "figure", "figcaption", "label"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
PAGE_LINES = 120
ATTR_CAP = 40
MAX_SESSIONS = 4
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)


def _cap(text: str, n: int = ATTR_CAP) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= n else text[: n - 3] + "..."


def is_interactive(tag: str, attrs: dict, wraps_control: bool = False) -> bool:
    """browser-use ClickableElementDetector.is_interactive, for attributes a static page has."""
    if tag in ("html", "body"):
        return False
    if attrs.get("aria-hidden") == "true" or "disabled" in attrs or attrs.get("aria-disabled") == "true":
        return False
    if tag == "label":
        return False if attrs.get("for") else wraps_control
    if tag == "input" and attrs.get("type", "").lower() == "hidden":
        return False
    if tag == "a":
        return bool(attrs.get("href")) and not attrs.get("href", "").startswith("javascript:")
    if tag in INTERACTIVE_TAGS:
        return True
    if any(a in attrs for a in INTERACTIVE_ATTRS):
        return True
    if attrs.get("role") in INTERACTIVE_ROLES:
        return True
    hay = (attrs.get("class", "") + " " + attrs.get("id", "")).lower()
    return any(h in hay for h in SEARCH_HINTS) and tag in ("button", "span", "div", "i")


class Element:
    def __init__(self, index: int, tag: str, attrs: dict, form: int):
        self.index, self.tag, self.attrs, self.form = index, tag, attrs, form
        self.text = ""
        self.options: list = []        # select: [(value, label, selected)]
        self.value = attrs.get("value", "")

    def kind(self) -> str:
        if self.tag == "a":
            return "link"
        if self.tag in ("input", "textarea", "select"):
            t = self.attrs.get("type", "text").lower() if self.tag == "input" else self.tag
            if t in ("submit", "image"):
                return "submit"
            if t in ("button", "reset"):
                return "button"
            return "field"
        if self.tag == "button":
            return "submit" if self.attrs.get("type", "submit").lower() == "submit" and self.form >= 0 else "button"
        return "other"


class _Parser(HTMLParser):
    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.lines: list = []        # str (text) or Element
        self.elements: list = []
        self.forms: list = []        # {"action", "method"}
        self.title = ""
        self._buf: list = []
        self._skip = 0
        self._hidden_stack: list = []
        self._open: list = []        # interactive elements collecting text
        self._form = -1
        self._in_title = False
        self._in_option = None
        self._heading = ""

    # text buffering -------------------------------------------------------------
    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        self._buf = []
        if text:
            self.lines.append(("#" * int(self._heading[1]) + " " + text) if self._heading else text)

    def handle_starttag(self, tag, attrs_list):
        attrs = {k.lower(): (v or "") for k, v in attrs_list}
        if tag in SKIP:
            if tag not in VOID:
                self._skip += 1
            return
        hidden = "hidden" in attrs or attrs.get("aria-hidden") == "true" or bool(_HIDDEN_STYLE.search(attrs.get("style", "")))
        if tag not in VOID:
            self._hidden_stack.append(hidden)
        if self._skip or any(self._hidden_stack) or (hidden and tag in VOID):
            return
        if tag == "title":
            self._in_title = True
            return
        if tag == "form":
            self.forms.append({"action": urllib.parse.urljoin(self.base, attrs.get("action", "") or self.base),
                               "method": (attrs.get("method") or "get").lower()})
            self._form = len(self.forms) - 1
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._flush()
            self._heading = tag
        elif tag in BLOCK:
            self._flush()
        if tag == "option" and self.elements and self.elements[-1].tag == "select":
            sel = self.elements[-1]
            self._in_option = [attrs.get("value"), "", "selected" in attrs]
            sel.options.append(self._in_option)
            return
        if tag == "img" and attrs.get("alt") and not self._open:
            self._buf.append(" [image: %s] " % _cap(attrs["alt"], 60))
        if is_interactive(tag, attrs):
            self._flush()
            el = Element(len(self.elements) + 1, tag, attrs, self._form if tag in ("input", "select", "textarea", "button") else -1)
            if tag == "a":
                el.attrs["href"] = urllib.parse.urljoin(self.base, attrs.get("href", ""))
            if tag == "input" and attrs.get("type", "").lower() in ("checkbox", "radio"):
                el.value = attrs.get("value", "on")
            self.elements.append(el)
            self.lines.append(el)
            if tag not in VOID:
                self._open.append(el)

    def handle_endtag(self, tag):
        if tag in SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if tag in VOID:
            return
        if self._hidden_stack:
            self._hidden_stack.pop()
        if tag == "title":
            self._in_title = False
            return
        if tag == "option" and self._in_option is not None:
            if self._in_option[0] is None:
                self._in_option[0] = self._in_option[1].strip()
            self._in_option = None
            return
        if self._open and self._open[-1].tag == tag:
            el = self._open.pop()
            el.text = _cap(el.text, 80)
            if el.tag == "textarea":
                el.value = el.text
            return
        if tag == "form":
            self._form = -1
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._flush()
            self._heading = ""
        elif tag in BLOCK:
            self._flush()

    def handle_data(self, data):
        if self._skip or any(self._hidden_stack):
            return
        if self._in_title:
            self.title += data
            return
        if self._in_option is not None:
            self._in_option[1] += data
            return
        if self._open:
            self._open[-1].text += data
            return
        self._buf.append(data)

    def close(self):
        super().close()
        self._flush()
        for el in self._open:
            el.text = _cap(el.text, 80)
        self.title = re.sub(r"\s+", " ", self.title).strip()


def _short_href(href: str, page_url: str) -> str:
    """A same-site link shows only its path (fewer tokens); other sites keep the host."""
    a, b = urllib.parse.urlparse(href), urllib.parse.urlparse(page_url or "")
    if a.netloc and a.netloc == b.netloc:
        return (a.path or "/") + (("?" + a.query) if a.query else "")
    return href


def render_element(el: Element, new: bool = False, page_url: str = "") -> str:
    """page-agent / browser-use line: [i]<tag attr=value ...>text />"""
    attrs = {}
    for key in INCLUDE_ATTRIBUTES:
        if key in el.attrs and str(el.attrs[key]).strip() != "":
            attrs[key] = el.attrs[key]
    if "href" in attrs:
        attrs["href"] = _short_href(attrs["href"], page_url)
    if el.tag in ("input", "textarea") and el.value and el.attrs.get("type", "").lower() not in ("password",):
        attrs["value"] = el.value
    if el.attrs.get("type", "").lower() == "password":
        attrs.pop("value", None)
    if el.tag == "select":
        chosen = next((o for o in el.options if o[2]), el.options[0] if el.options else None)
        if el.value:
            chosen = next((o for o in el.options if o[0] == el.value), chosen)
        attrs["options"] = "|".join(_cap(o[1] or o[0], 20) for o in el.options[:6]) + ("|..." if len(el.options) > 6 else "")
        if chosen:
            attrs["selected"] = chosen[1].strip() or chosen[0]
    # page-agent: drop duplicate long values, a role equal to the tag, attributes repeating the text
    seen = {}
    for key in list(attrs):
        value = str(attrs[key])
        if len(value) > 5 and value in seen:
            del attrs[key]
        else:
            seen[value] = key
    if attrs.get("role") == el.tag:
        del attrs["role"]
    for key in ("aria-label", "placeholder", "title"):
        if key in attrs and str(attrs[key]).strip().lower() == el.text.strip().lower():
            del attrs[key]
    attr_text = " ".join("%s=%s" % (k, _cap(v)) for k, v in attrs.items())
    line = "%s[%d]<%s" % ("*" if new else "", el.index, el.tag)
    if attr_text:
        line += " " + attr_text
    if el.text:
        line += (">" if attr_text else " >") + el.text
    return line + " />"


class Page:
    def __init__(self, url: str, html_text: str, status: int = 200):
        self.url = url
        self.status = status
        parser = _Parser(url)
        try:
            parser.feed(html_text or "")
            parser.close()
        except Exception:  # noqa: BLE001 - broken HTML still shows what parsed
            pass
        self.title = parser.title
        self.lines = parser.lines
        self.elements = parser.elements
        self.forms = parser.forms
        self._raw_hidden: list = []
        _collect_hidden(self, html_text)

    def rendered(self, previous: set | None = None) -> list:
        prev = previous or set()
        out = []
        for line in self.lines:
            if isinstance(line, Element):
                key = (line.tag, line.attrs.get("href") or line.attrs.get("name") or line.text)
                out.append(render_element(line, new=bool(prev) and key not in prev, page_url=self.url))
            else:
                out.append(line)
        return out

    def keys(self) -> set:
        return {(e.tag, e.attrs.get("href") or e.attrs.get("name") or e.text) for e in self.elements}


class Session:
    def __init__(self, opener=None, allow=None):
        self.jar = http.cookiejar.CookieJar()
        self._opener = opener or urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar)).open
        self.allow = allow or (lambda url: True)
        self.history: list = []
        self.page: Page | None = None
        self.offset = 0
        self._previous_keys: set = set()
        self.used = time.time()

    # http -------------------------------------------------------------------------
    def _load(self, url: str, data: bytes | None = None) -> str:
        if not self.allow(url):
            return "error: %s is on this computer or the local network; the text browser only opens public pages" % url
        req = urllib.request.Request(url, data=data, headers=web_reader.headers(url))
        if data is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with self._opener(req, timeout=web_reader.TIMEOUT_S) as resp:
                body = resp.read(web_reader.MAX_BYTES)
                info = getattr(resp, "headers", {}) or {}
                ctype = info.get("Content-Type", "") if hasattr(info, "get") else ""
                cenc = info.get("Content-Encoding", "") if hasattr(info, "get") else ""
                final = getattr(resp, "url", "") or url
                status = getattr(resp, "status", 200) or 200
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", None)
            return "error: could not open %s (%s)" % (url, ("HTTP %s" % code) if code else str(exc)[:120])
        text = web_reader._decode(body, ctype, cenc)   # noqa: SLF001
        if self.page is not None:
            self.history.append(self.page.url)
            self._previous_keys = self.page.keys()
        else:
            self._previous_keys = set()
        self.page = Page(final, text, status)
        self.offset = 0
        self.used = time.time()
        return ""

    def view(self) -> str:
        """page-agent's browser state: header, a window of the page, footer."""
        page = self.page
        if page is None:
            return "error: no page open - use action='open' with a url"
        rows = page.rendered(self._previous_keys)
        total = len(rows)
        start = min(self.offset, max(0, total - 1))
        window = rows[start:start + PAGE_LINES]
        header = "Current Page: [%s](%s)\n%d interactive elements; lines %d-%d of %d" % (
            page.title or page.url, page.url, len(page.elements), start + 1 if total else 0, start + len(window), total)
        above = "[Start of page]" if start == 0 else "... %d lines above - action='scroll' with direction='up' ..." % start
        below_n = total - (start + len(window))
        below = "[End of page]" if below_n <= 0 else "... %d more lines below - action='scroll' to see more ..." % below_n
        body = "\n".join(window)
        if not page.elements and len("".join(r for r in rows if isinstance(r, str))) < 80:
            body += ("\n(This page shows almost nothing without JavaScript. Try read_web, or the Browser Use "
                     "add-on: conductor role='browse'.)")
        hint = ("Use: click index=N (follow a link / press a button), type index=N text=..., select index=N "
                "text=option, submit index=N, scroll, back, find text=..., open url=... "
                "*[N] marks elements that are new since the last page.")
        return "%s\n\n%s\n%s\n%s\n\n%s" % (header, above, body, below, hint)

    # actions ----------------------------------------------------------------------
    def _el(self, index) -> Element | str:
        if self.page is None:
            return "error: no page open"
        try:
            i = int(index)
        except (TypeError, ValueError):
            return "error: give the element's number (index)"
        if not 1 <= i <= len(self.page.elements):
            return "error: there is no element [%s] on this page (1-%d)" % (index, len(self.page.elements))
        return self.page.elements[i - 1]

    def open(self, url: str) -> str:
        url = str(url or "").strip()
        if not url:
            return "error: give a url"
        if not re.match(r"^https?://", url):
            url = "https://" + url
        return self._load(url) or self.view()

    def click(self, index) -> str:
        el = self._el(index)
        if isinstance(el, str):
            return el
        if el.tag == "a":
            return self._load(el.attrs["href"]) or self.view()
        if el.kind() == "submit" or (el.tag == "button" and el.form >= 0):
            return self.submit(index)
        if el.tag == "input" and el.attrs.get("type", "").lower() in ("checkbox", "radio"):
            if el.attrs.get("type", "").lower() == "radio":
                for other in self.page.elements:
                    if other.form == el.form and other.attrs.get("name") == el.attrs.get("name"):
                        other.attrs.pop("checked", None)
                el.attrs["checked"] = "checked"
            elif "checked" in el.attrs:
                el.attrs.pop("checked")
            else:
                el.attrs["checked"] = "checked"
            return "[%d] is now %s\n%s" % (el.index, "checked" if "checked" in el.attrs else "unchecked", render_element(el))
        return ("error: [%d] needs JavaScript to do anything (a static page cannot run it). Use the Browser Use "
                "add-on (conductor role='browse') for this site." % el.index)

    def type(self, index, text: str) -> str:
        el = self._el(index)
        if isinstance(el, str):
            return el
        if el.kind() != "field" or el.tag == "select":
            return "error: [%d] is not a text field (use select for a <select>)" % el.index
        el.value = str(text or "")
        return "typed into [%d]: %s\nNext: submit index=%d (or click the form's button)." % (el.index, render_element(el), el.index)

    def select(self, index, text: str) -> str:
        el = self._el(index)
        if isinstance(el, str):
            return el
        if el.tag != "select":
            return "error: [%d] is not a <select>" % el.index
        want = str(text or "").strip().lower()
        for value, label, _sel in el.options:
            if want in (str(value).lower(), label.strip().lower()):
                el.value = value
                return "selected %r in [%d]" % (label.strip() or value, el.index)
        return "error: [%d] has no option %r (options: %s)" % (el.index, text, ", ".join(o[1].strip() or o[0] for o in el.options[:20]))

    def submit(self, index) -> str:
        el = self._el(index)
        if isinstance(el, str):
            return el
        if el.form < 0:
            return "error: [%d] is not inside a form" % el.index
        form = self.page.forms[el.form]
        fields = []
        for other in self.page.elements:
            if other.form != el.form or not other.attrs.get("name"):
                continue
            t = other.attrs.get("type", "").lower()
            if other.kind() in ("submit", "button") and other is not el:
                continue
            if t in ("checkbox", "radio") and "checked" not in other.attrs:
                continue
            if other.tag == "select":
                value = other.value or next((o[0] for o in other.options if o[2]), other.options[0][0] if other.options else "")
                fields.append((other.attrs["name"], value))
            else:
                fields.append((other.attrs["name"], other.value))
        # hidden inputs are not elements but forms need them (tokens, page state)
        hidden = self._hidden_fields(el.form)
        fields = hidden + fields
        query = urllib.parse.urlencode(fields)
        if form["method"] == "post":
            if not post_allowed():
                return ("error: this form POSTs (it changes something on the site: a sign-up, an order, a "
                        "message). The text browser only submits search-style GET forms. Ask the user, then use "
                        "the Browser Use add-on (conductor role='browse', it asks first) - or set LOKI_BROWSE_POST=1.")
            return self._load(form["action"], data=query.encode("utf-8")) or self.view()
        sep = "&" if "?" in form["action"] else "?"
        action = form["action"].split("#")[0]
        if "?" in action:
            action = action.split("?")[0]
            sep = "?"
        return self._load(action + sep + query) or self.view()

    def _hidden_fields(self, form_index: int) -> list:
        return [(n, v) for f, n, v in self.page._raw_hidden if f == form_index]  # noqa: SLF001

    def scroll(self, direction: str = "down") -> str:
        if self.page is None:
            return "error: no page open"
        step = PAGE_LINES - 10
        self.offset = max(0, self.offset - step) if str(direction).lower().startswith("u") else self.offset + step
        return self.view()

    def back(self) -> str:
        if not self.history:
            return "error: nothing to go back to"
        url = self.history.pop()
        current, self.page = self.page, None
        msg = self._load(url)
        if msg:
            self.page = current
            return msg
        if self.history and self.history[-1] == url:
            self.history.pop()
        return self.view()

    def find(self, text: str) -> str:
        if self.page is None:
            return "error: no page open"
        want = str(text or "").lower()
        if not want:
            return "error: give text to find"
        rows = self.page.rendered()
        hits = [i for i, r in enumerate(rows) if want in r.lower()]
        if not hits:
            return "%r is not on this page" % text
        self.offset = max(0, hits[0] - 5)
        return "found %r on %d line(s); showing from the first:\n\n%s" % (text, len(hits), self.view())


def _collect_hidden(page: Page, html_text: str) -> None:
    """Hidden <input>s per form (CSRF tokens etc.) - the form needs them on submit."""
    out, form = [], -1
    for m in re.finditer(r"<(/?)(form|input)\b([^>]*)>", html_text or "", re.I):
        closing, tag, rest = m.group(1), m.group(2).lower(), m.group(3)
        if tag == "form":
            form = -1 if closing else form + 1
            continue
        if form < 0 or not re.search(r"""type\s*=\s*["']?hidden""", rest, re.I):
            continue
        name = re.search(r"""name\s*=\s*["']([^"']*)""", rest, re.I)
        value = re.search(r"""value\s*=\s*["']([^"']*)""", rest, re.I)
        if name:
            out.append((form, name.group(1), value.group(1) if value else ""))
    page._raw_hidden = out  # noqa: SLF001


SESSIONS: dict = {}


def post_allowed() -> bool:
    import os  # pylint: disable=import-outside-toplevel
    return str(os.getenv("LOKI_BROWSE_POST", "0")).strip().lower() in ("1", "on", "true", "yes")


def session(name: str = "default", opener=None, allow=None) -> Session:
    name = str(name or "default")[:40]
    if name not in SESSIONS:
        if len(SESSIONS) >= MAX_SESSIONS:
            oldest = min(SESSIONS, key=lambda k: SESSIONS[k].used)
            SESSIONS.pop(oldest, None)
        SESSIONS[name] = Session(opener=opener, allow=allow)
    elif allow is not None:
        SESSIONS[name].allow = allow
    return SESSIONS[name]


def act(action: str, url: str = "", index=None, text: str = "", direction: str = "down", name: str = "default",
        opener=None, allow=None) -> str:
    """One browser step. action: open | view | click | type | select | submit | scroll | back | find."""
    s = session(name, opener=opener, allow=allow)
    action = str(action or "view").strip().lower()
    if action in ("open", "goto", "navigate", "visit"):
        return s.open(url)
    if action in ("view", "state", "show"):
        return s.view()
    if action == "click":
        return s.click(index)
    if action in ("type", "input", "fill"):
        return s.type(index, text)
    if action == "select":
        return s.select(index, text)
    if action in ("submit", "enter"):
        return s.submit(index)
    if action == "scroll":
        return s.scroll(direction or "down")
    if action == "back":
        return s.back()
    if action in ("find", "search_page"):
        return s.find(text)
    return "error: unknown action %r (open, view, click, type, select, submit, scroll, back, find)" % action
