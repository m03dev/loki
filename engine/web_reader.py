"""Read a web page natively: fetch it and turn it into clean markdown - no add-on needed.

Ported from Scrapling's non-browser core (D4Vinci/Scrapling: the static Fetcher's browser-like
headers and convincing referer, Convertor._extract_content(main_content_only=True),
_strip_noise_tags, _sanitize_for_ai, get_all_text), BSD-3-Clause - see
engine/licenses/Scrapling-BSD-3-Clause.txt. Scrapling itself needs lxml, cssselect, curl_cffi,
browserforge and markdownify; this port uses only the standard library (urllib + html.parser),
so LOKI can read pages on any machine. The Scrapling add-on (engine/runners/scrape.py) stays
the upgrade for JavaScript pages, stealth and crawling.

What it keeps from Scrapling:

  * main content only: the <body> (or its <main>/<article> when that holds the real text)
  * noise tags dropped: script, style, noscript, svg, iframe, template, head
  * the prompt-injection sanitizer: elements hidden with display:none / visibility:hidden /
    opacity:0 / font-size:0 / height:0 / width:0, aria-hidden="true" and <template> are dropped,
    and zero-width and control characters are removed - text a human cannot see never reaches
    the model
  * browser-like request headers with a referer that looks like a search click
"""
from __future__ import annotations

import gzip
import re
import sys
import urllib.parse
import urllib.request
import zlib
from html import unescape
from html.parser import HTMLParser

MAX_BYTES = 3 * 1024 * 1024
MAX_CHARS = 20000
TIMEOUT_S = 25
NOISE = {"script", "style", "noscript", "svg", "iframe", "template", "head", "canvas", "object", "embed"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source",
        "track", "wbr"}
BLOCK = {"p", "div", "section", "article", "main", "header", "footer", "nav", "aside", "form", "table",
         "ul", "ol", "dl", "figure", "figcaption", "address", "details", "summary", "hr"}
_HIDDEN_STYLE = re.compile(r"(display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(?![.\d])|"
                           r"font-size\s*:\s*0(?![.\d])|height\s*:\s*0(?![.\d])|width\s*:\s*0(?![.\d]))", re.I)
_ZWC = re.compile("[​‌‍﻿⁠᠎]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def user_agent() -> str:
    if sys.platform == "darwin":
        os_part = "Macintosh; Intel Mac OS X 10_15_7"
    elif sys.platform == "win32":
        os_part = "Windows NT 10.0; Win64; x64"
    else:
        os_part = "X11; Linux x86_64"
    return "Mozilla/5.0 (%s) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36" % os_part


def convincing_referer(url: str) -> str:
    """Scrapling: make the request look like it came from a search for the site."""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    parts = host.split(".")
    name = parts[-2] if len(parts) >= 2 else host
    return "https://www.google.com/search?q=%s" % urllib.parse.quote(name or host)


def headers(url: str) -> dict:
    return {"User-Agent": user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7",
            "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip, deflate",
            "Referer": convincing_referer(url), "Upgrade-Insecure-Requests": "1"}


def sanitize_text(text: str) -> str:
    return _CONTROL.sub("", _ZWC.sub("", text))


class _Markdown(HTMLParser):
    def __init__(self, base_url: str = "", scope: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.scope = scope            # "" = everything in <body>; else only inside the first <scope>
        self.scope_depth = 0
        self.scope_done = False
        self.out: list = []
        self.stack: list = []         # [(tag, hidden)]
        self.hidden = 0
        self.in_body = False
        self.seen_body = False
        self.pre = 0
        self.lists: list = []         # ["ul"|"ol", counter]
        self.link: list = []          # [href, start index]
        self.title = ""
        self.in_title = False
        self.cell = False

    # -- helpers
    def emit(self, text: str) -> None:
        if self.hidden or self.scope_done:
            return
        if self.scope and not self.scope_depth:
            return
        if not self.in_body and self.seen_body:
            return
        self.out.append(text)

    def block(self) -> None:
        if self.out and not "".join(self.out[-2:]).endswith("\n\n"):
            self.emit("\n\n")

    @staticmethod
    def _is_hidden(tag: str, attrs: dict) -> bool:
        if tag in NOISE:
            return True
        if str(attrs.get("aria-hidden", "")).lower() == "true" or "hidden" in attrs:
            return True
        return bool(_HIDDEN_STYLE.search(str(attrs.get("style") or "")))

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self.in_title = True
        if tag == "body":
            self.in_body = self.seen_body = True
        if tag in VOID:
            if tag == "br":
                self.emit("\n")
            elif tag == "hr":
                self.block()
                self.emit("---")
                self.block()
            elif tag == "img" and a.get("alt"):
                self.emit("![%s](%s)" % (a["alt"].strip(), urllib.parse.urljoin(self.base, a.get("src", ""))))
            return
        hidden = self._is_hidden(tag, a)
        self.stack.append((tag, hidden))
        if hidden:
            self.hidden += 1
            return
        if self.scope and tag == self.scope and not self.scope_done:
            self.scope_depth += 1
        if re.fullmatch(r"h[1-6]", tag):
            self.block()
            self.emit("#" * int(tag[1]) + " ")
        elif tag in ("ul", "ol"):
            self.lists.append([tag, 0])
            self.block()
        elif tag == "li":
            self.emit("\n" + "  " * max(0, len(self.lists) - 1))
            if self.lists and self.lists[-1][0] == "ol":
                self.lists[-1][1] += 1
                self.emit("%d. " % self.lists[-1][1])
            else:
                self.emit("- ")
        elif tag == "pre":
            self.pre += 1
            self.block()
            self.emit("```\n")
        elif tag == "code" and not self.pre:
            self.emit("`")
        elif tag in ("strong", "b"):
            self.emit("**")
        elif tag in ("em", "i"):
            self.emit("*")
        elif tag == "blockquote":
            self.block()
            self.emit("> ")
        elif tag == "a":
            self.link.append([a.get("href", ""), len(self.out)])
        elif tag in ("td", "th"):
            self.emit("| ")
        elif tag == "tr":
            if self.out and not self.out[-1].endswith("\n"):
                self.emit("\n")
        elif tag in BLOCK:
            self.block()

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag == "body":
            self.in_body = False
        if tag in VOID:
            return
        # pop to the matching open tag (HTML in the wild is not always well formed)
        idx = len(self.stack) - 1
        while idx >= 0 and self.stack[idx][0] != tag:
            idx -= 1
        if idx < 0:
            return
        closing = self.stack[idx:]
        del self.stack[idx:]
        was_hidden = any(h for _, h in closing)
        for _, h in closing:
            if h:
                self.hidden -= 1
        if was_hidden:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self.block()
        elif tag in ("ul", "ol"):
            if self.lists:
                self.lists.pop()
            self.block()
        elif tag == "pre":
            self.pre = max(0, self.pre - 1)
            self.emit("\n```")
            self.block()
        elif tag == "code" and not self.pre:
            self.emit("`")
        elif tag in ("strong", "b"):
            self.emit("**")
        elif tag in ("em", "i"):
            self.emit("*")
        elif tag == "a" and self.link:
            href, start = self.link.pop()
            text = "".join(self.out[start:]).strip()
            if href and text and not href.startswith(("javascript:", "#")) and start <= len(self.out):
                del self.out[start:]
                self.emit("[%s](%s)" % (text, urllib.parse.urljoin(self.base, href)))
        elif tag in ("td", "th"):
            self.emit(" ")
        elif tag == "tr":
            self.emit("|\n")
        elif tag in BLOCK or tag in ("blockquote",):
            self.block()
        if self.scope and tag == self.scope and self.scope_depth:
            self.scope_depth -= 1
            if not self.scope_depth:
                self.scope_done = True

    def handle_data(self, data):
        if self.in_title:
            self.title += data
            return
        if self.pre:
            self.emit(sanitize_text(data))
            return
        text = re.sub(r"\s+", " ", sanitize_text(data))
        if self.out and self.out[-1].endswith("\n"):
            text = text.lstrip()
        if text.strip() or (text == " " and self.out and not self.out[-1].endswith((" ", "\n"))):
            self.emit(text)


def _clean(markdown: str) -> str:
    lines = [line.rstrip() for line in markdown.replace("\r", "").split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return text.strip()


def to_markdown(html: str, base_url: str = "") -> dict:
    """{"title", "markdown"} - main content only, hidden text and noise removed."""
    html = str(html or "")
    def run(scope: str) -> _Markdown:
        p = _Markdown(base_url, scope)
        try:
            p.feed(html)
            p.close()
        except Exception:  # noqa: BLE001 - html.parser is lenient; never fail a read on markup
            pass
        return p
    best = None
    for scope in ("main", "article"):
        if re.search(r"<%s[\s>]" % scope, html, re.I):
            p = run(scope)
            text = _clean("".join(p.out))
            if len(text) >= 400:
                best = (p, text)
                break
    if best is None:
        p = run("")
        best = (p, _clean("".join(p.out)))
    parser, text = best
    title = " ".join(unescape(parser.title).split())
    if not parser.title:
        probe = run("")
        title = " ".join(probe.title.split())
    return {"title": title, "markdown": text}


def _decode(body: bytes, content_type: str, encoding: str) -> str:
    enc = (encoding or "").lower()
    if enc == "gzip":
        body = gzip.decompress(body)
    elif enc == "deflate":
        try:
            body = zlib.decompress(body)
        except zlib.error:
            body = zlib.decompress(body, -zlib.MAX_WBITS)
    charset = ""
    m = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    if m:
        charset = m.group(1)
    else:
        m = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", body[:4096], re.I)
        if m:
            charset = m.group(1).decode("ascii", "ignore")
    try:
        return body.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def fetch(url: str, opener=None, timeout: float = TIMEOUT_S) -> dict:
    """{"ok", "status", "url", "content_type", "html"|"error"}."""
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return {"ok": False, "error": "read_web needs an http(s) url"}
    req = urllib.request.Request(parsed.geturl(), headers=headers(parsed.geturl()))
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200) or 200
            info = getattr(resp, "headers", {}) or {}
            ctype = info.get("Content-Type", "") if hasattr(info, "get") else ""
            cenc = info.get("Content-Encoding", "") if hasattr(info, "get") else ""
            body = resp.read(MAX_BYTES + 1)
            final = getattr(resp, "url", "") or parsed.geturl()
    except Exception as exc:  # noqa: BLE001 - HTTPError, URLError, timeouts
        code = getattr(exc, "code", None)
        return {"ok": False, "status": code, "error": ("HTTP %s" % code) if code else "%s: %s" % (type(exc).__name__, exc)}
    truncated = len(body) > MAX_BYTES
    text = _decode(body[:MAX_BYTES], ctype, cenc)
    return {"ok": True, "status": status, "url": final, "content_type": ctype, "html": text, "truncated": truncated}


def read(url: str, max_chars: int = MAX_CHARS, opener=None) -> str:
    """One page as markdown (title first), or "error: ..."."""
    got = fetch(url, opener=opener)
    if not got.get("ok"):
        return "error: could not read %s (%s)" % (url, got.get("error"))
    ctype = (got.get("content_type") or "").lower()
    if "html" in ctype or "<html" in got["html"][:2000].lower() or "<body" in got["html"][:5000].lower():
        page = to_markdown(got["html"], got.get("url") or url)
        text = ("# " + page["title"] + "\n\n" if page["title"] else "") + page["markdown"]
    elif any(k in ctype for k in ("text/", "json", "xml")) or not ctype:
        text = sanitize_text(got["html"])
    else:
        return "error: %s is not a text page (%s)" % (url, ctype or "unknown type")
    if not text.strip():
        return ("error: %s has no readable text without JavaScript - turn on the Scrapling add-on "
                "(scrape with dynamic=true) or crawl4ai for pages like this" % url)
    note = ""
    if len(text) > max_chars:
        text, note = text[:max_chars], "\n[truncated at %d characters]" % max_chars
    return text + note + "\n\n[read natively by LOKI from %s]" % (got.get("url") or url)
