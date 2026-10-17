"""Internet reach without the add-on: GitHub, RSS/Atom feeds, YouTube, Reddit and JavaScript
pages, each read the way that works best for it - plus a strict "is this URL public?" check.

Ported into LOKI (session 27 harvest) from Agent Reach (github.com/Panniantong/Agent-Reach),
MIT License, Copyright (c) 2025 Agent Eyes - see engine/licenses/Agent-Reach-MIT.txt:
  - utils/url.py normalize_public_http_url / host_matches: only http(s), no userinfo, no
    `%` zone ids, blocked internal names (localhost, *.internal, *.lan, metadata.google.internal
    ...), dotless names refused, and IPv4 literals parsed the LEGACY way too (`127.1`,
    `2130706433`, `0x7f.0.0.1` are loopback) and refused unless globally routable; hosts
    matched exactly or as a real subdomain (never `x.com.evil.test`).
  - channels/*: the per-site routing (can_handle) - GitHub, RSS/Atom, YouTube, Reddit, and the
    "any page" channel through Jina Reader (r.jina.ai renders JavaScript pages to markdown) with
    its anti-bot/CAPTCHA page detection (_is_antibot_page).
  - channels/reddit.py's finding: anonymous .json is blocked (403) - LOKI says so honestly and
    reads the page through Jina instead.
The Agent Reach add-on (its CLIs, logged-in channels: X, Xiaohongshu, Bilibili...) stays the
upgrade; this is what works with nothing installed. Network calls go through `opener`.
"""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

try:
    import web_reader
except ImportError:  # pragma: no cover
    from engine import web_reader  # type: ignore

BLOCKED_HOSTS = {"home.arpa", "instance-data", "internal", "ip6-localhost", "ip6-loopback", "lan", "local",
                 "localdomain", "localhost", "metadata.google.internal"}
BLOCKED_SUFFIXES = (".home.arpa", ".internal", ".lan", ".local", ".localdomain", ".localhost")
MAX_BYTES = 5 * 1024 * 1024
TIMEOUT_S = 30
JINA = "https://r.jina.ai/"


# --------------------------------------------------------------------------- URL safety (Agent Reach)
def literal_ip(host: str):
    """An IP literal, including legacy IPv4 spellings inet_aton accepts (127.1, 2130706433)."""
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    if not re.fullmatch(r"[0-9a-fA-Fx.]+", host or ""):
        return None
    try:
        return ipaddress.IPv4Address(socket.inet_aton(host))
    except OSError:
        return None


def public_url_problem(url: str, allow: set | None = None) -> str:
    """"" when `url` is clearly a public http(s) URL, else why not (Agent Reach's rules)."""
    candidate = str(url or "").strip()
    if not candidate or "\\" in candidate or any(c.isspace() or ord(c) < 0x20 or ord(c) == 0x7F for c in candidate):
        return "not a clean URL"
    if "://" not in candidate:
        candidate = "https://" + candidate
    try:
        parsed = urllib.parse.urlsplit(candidate)
        host = (parsed.hostname or "").lower().rstrip(".")
        _ = parsed.port
    except (TypeError, ValueError):
        return "malformed address"
    if allow and host in allow:
        return ""
    if parsed.scheme.lower() not in ("http", "https"):
        return "only http(s) pages"
    if not host:
        return "no host"
    if parsed.username is not None or parsed.password is not None:
        return "a user name/password in the URL"
    if "%" in host:
        return "a zone id in the host"
    if host in BLOCKED_HOSTS or host.endswith(BLOCKED_SUFFIXES):
        return "%s is a local/internal name" % host
    ip = literal_ip(host)
    if ip is None and "." not in host:
        return "%s is not a public domain name" % host
    if ip is not None and not ip.is_global:
        return "%s is a private/loopback address" % host
    return ""


def host_matches(url: str, *domains: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        _ = parsed.port
    except (TypeError, ValueError):
        return False
    if parsed.scheme.lower() not in ("http", "https") or not host or parsed.username or parsed.password:
        return False
    return any(host == d or host.endswith("." + d) for d in (x.lower().strip(".") for x in domains))


# --------------------------------------------------------------------------- http
def _get(url: str, opener=None, headers: dict | None = None, timeout: float = TIMEOUT_S) -> tuple:
    req = urllib.request.Request(url, headers=headers or web_reader.headers(url))
    open_fn = opener or urllib.request.urlopen
    with open_fn(req, timeout=timeout) as resp:
        body = resp.read(MAX_BYTES + 1)
        info = getattr(resp, "headers", {}) or {}
        ctype = info.get("Content-Type", "") if hasattr(info, "get") else ""
        cenc = info.get("Content-Encoding", "") if hasattr(info, "get") else ""
    if len(body) > MAX_BYTES:
        raise ValueError("response is over %d bytes" % MAX_BYTES)
    return web_reader._decode(body, ctype, cenc), ctype   # noqa: SLF001


def is_antibot_page(text: str) -> bool:
    """Agent Reach web.py _is_antibot_page: a Jina/Cloudflare challenge, not the content."""
    sample = (text or "")[:4096].casefold()
    jina_captcha = "warning:" in sample and "requiring captcha" in sample
    challenge = any(m in sample for m in ("title: just a moment...", "## performing security verification",
                                          "title: attention required! | cloudflare"))
    cf_block = "title: attention required! | cloudflare" in sample and ("ray id" in sample or "/cdn-cgi/challenge-platform/" in sample)
    return (jina_captcha and challenge) or cf_block


def jina_allowed() -> bool:
    """Jina Reader sends the URL to r.jina.ai; LOKI_JINA=0 keeps every read on this machine."""
    import os  # pylint: disable=import-outside-toplevel
    return str(os.getenv("LOKI_JINA", "1")).strip().lower() not in ("0", "off", "false", "no")


def read_jina(url: str, opener=None) -> str:
    """Any page (JavaScript too) as markdown through Jina Reader."""
    if not jina_allowed():
        return "error: Jina Reader is off (LOKI_JINA=0)"
    text, _ = _get(JINA + url, opener, headers={"User-Agent": web_reader.user_agent(), "Accept": "text/plain"})
    if is_antibot_page(text):
        return "error: the site answered with an anti-bot check, not the page (needs a real browser: conductor role='browse')"
    return web_reader.sanitize_text(text)


# --------------------------------------------------------------------------- channels
def parse_feed(xml_text: str, limit: int = 15) -> dict:
    """RSS 2.0 / RSS 1.0 (RDF) / Atom -> {"title", "items": [{title, link, date, summary}]}."""
    root = ET.fromstring(xml_text.strip().encode("utf-8"))

    def local(tag: str) -> str:
        return tag.split("}")[-1].lower()

    def child(node, *names):
        for c in node:
            if local(c.tag) in names:
                return c
        return None

    def text(node, *names) -> str:
        c = child(node, *names)
        if c is None:
            return ""
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", "".join(c.itertext()))).strip()
    title = ""
    channel = child(root, "channel")
    if channel is not None:
        title = text(channel, "title")
    elif local(root.tag) == "feed":
        title = text(root, "title")
    items = []
    for node in root.iter():
        if local(node.tag) not in ("item", "entry"):
            continue
        link = text(node, "link")
        link_el = child(node, "link")
        if not link and link_el is not None:
            link = link_el.get("href", "")
        items.append({"title": text(node, "title"), "link": link,
                      "date": text(node, "pubdate", "published", "updated", "date"),
                      "summary": text(node, "description", "summary", "content")[:300]})
        if len(items) >= limit:
            break
    return {"title": title, "items": items}


def looks_like_feed(url: str, ctype: str = "", body: str = "") -> bool:
    low = url.lower()
    if any(x in low for x in ("/feed", "/rss", ".rss", "atom.xml", "/atom", "feed.xml", "rss.xml")):
        return True
    if any(x in (ctype or "").lower() for x in ("rss", "atom")):
        return True
    head = (body or "")[:500].lower()
    return "<rss" in head or "<feed" in head or "<rdf:rdf" in head


def read_feed(url: str, opener=None, limit: int = 15) -> str:
    text, _ = _get(url, opener)
    feed = parse_feed(text, limit)
    if not feed["items"]:
        return "error: %s is not a feed with items" % url
    lines = ["Feed: %s (%s) - %d newest item(s)" % (feed["title"] or url, url, len(feed["items"]))]
    for i, it in enumerate(feed["items"], 1):
        lines.append("%d. %s%s\n   %s%s" % (i, it["title"] or "(untitled)", (" - " + it["date"]) if it["date"] else "",
                                             it["link"], ("\n   " + it["summary"]) if it["summary"] else ""))
    return "\n".join(lines)


_GH = re.compile(r"^https?://(?:www\.)?github\.com/([^/]+)/([^/#?]+)(?:/(issues|pull|blob|tree|releases)(?:/([^#?]+))?)?")


def read_github(url: str, opener=None) -> str:
    """A repo (facts + README), an issue/PR (body + first comments) or a file (raw), via the
    public API - no gh CLI, no token (60 requests an hour)."""
    m = _GH.match(url)
    if not m:
        return ""
    owner, repo, kind, rest = m.group(1), m.group(2).removesuffix(".git"), m.group(3), m.group(4) or ""
    api = "https://api.github.com/repos/%s/%s" % (owner, repo)
    hdr = {"Accept": "application/vnd.github+json", "User-Agent": "LOKI-agent"}
    if kind == "blob" and "/" in rest:
        ref, path = rest.split("/", 1)
        text, _ = _get("https://raw.githubusercontent.com/%s/%s/%s/%s" % (owner, repo, ref, path), opener, headers=hdr)
        return "# %s/%s: %s (%s)\n\n%s" % (owner, repo, path, ref, text[:40000])
    if kind in ("issues", "pull") and rest.split("/")[0].isdigit():
        num = rest.split("/")[0]
        issue = json.loads(_get("%s/issues/%s" % (api, num), opener, headers=hdr)[0])
        out = ["# %s/%s #%s: %s" % (owner, repo, num, issue.get("title", "")),
               "%s by %s, %s, %d comment(s)" % ("PR" if issue.get("pull_request") else "Issue",
                                                 (issue.get("user") or {}).get("login", "?"), issue.get("state", "?"),
                                                 issue.get("comments", 0)),
               "", web_reader.sanitize_text(issue.get("body") or "")[:8000]]
        if issue.get("comments"):
            try:
                comments = json.loads(_get("%s/issues/%s/comments?per_page=10" % (api, num), opener, headers=hdr)[0])
                for c in comments[:10]:
                    out.append("\n--- %s:\n%s" % ((c.get("user") or {}).get("login", "?"),
                                                 web_reader.sanitize_text(c.get("body") or "")[:2000]))
            except Exception:  # noqa: BLE001
                pass
        return "\n".join(out)
    info = json.loads(_get(api, opener, headers=hdr)[0])
    out = ["# %s" % info.get("full_name", owner + "/" + repo),
           info.get("description") or "",
           "stars %s, forks %s, open issues %s, language %s, licence %s, default branch %s, last push %s" % (
               info.get("stargazers_count"), info.get("forks_count"), info.get("open_issues_count"),
               info.get("language"), ((info.get("license") or {}).get("spdx_id")), info.get("default_branch"),
               (info.get("pushed_at") or "")[:10]),
           "homepage: %s" % info["homepage"] if info.get("homepage") else ""]
    try:
        readme, _ = _get("%s/readme" % api, opener, headers=dict(hdr, Accept="application/vnd.github.raw"))
        out += ["", "## README", readme[:20000]]
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(x for x in out if x is not None)


def read_youtube(url: str, opener=None) -> str:
    """Title and channel through YouTube's oEmbed; the transcript needs yt-dlp (media add-on)."""
    data = json.loads(_get("https://www.youtube.com/oembed?" + urllib.parse.urlencode({"url": url, "format": "json"}),
                           opener)[0])
    return ("# %s\nchannel: %s (%s)\n%s\n\nFor the transcript or the audio use conductor role='media' "
            "(the media add-on, yt-dlp)." % (data.get("title", "?"), data.get("author_name", "?"),
                                             data.get("author_url", ""), url))


def route(url: str) -> str:
    """Which channel reads `url` (Agent Reach can_handle order)."""
    if host_matches(url, "github.com"):
        return "github"
    if host_matches(url, "youtube.com", "youtu.be"):
        return "youtube"
    if host_matches(url, "reddit.com", "redd.it"):
        return "reddit"
    if host_matches(url, "x.com", "twitter.com", "instagram.com", "facebook.com", "linkedin.com", "tiktok.com"):
        return "login"
    if looks_like_feed(url):
        return "rss"
    return "web"


def reach(url: str, opener=None, native_read=None) -> str:
    """Read `url` with the best channel. native_read(url) is LOKI's own reader (tried first for web)."""
    problem = public_url_problem(url)
    if problem:
        return "error: %s - reach only reads public pages (%s)" % (url, problem)
    channel = route(url)
    try:
        if channel == "github":
            text = read_github(url, opener)
            if text:
                return text + "\n\n[read by LOKI via the GitHub API]"
        if channel == "youtube":
            return read_youtube(url, opener)
        if channel == "rss":
            return read_feed(url, opener)
        if channel == "login":
            jina = read_jina(url, opener)
            if not jina.startswith("error"):
                return jina + "\n\n[read through Jina Reader; logged-in views need the Agent Reach add-on]"
            return ("error: %s needs a logged-in session - turn on the Agent Reach add-on (conductor role='reach')"
                    % url)
        if channel == "reddit":
            jina = read_jina(url, opener)
            return jina + ("\n\n[Reddit blocks anonymous API reads; read through Jina Reader]"
                           if not jina.startswith("error") else "")
    except Exception as exc:  # noqa: BLE001 - fall through to the generic readers
        failed = "%s channel failed (%s); " % (channel, str(exc)[:100])
    else:
        failed = ""
    if native_read is not None:
        text = native_read(url)
        if text and not str(text).startswith("error") and "no readable text without JavaScript" not in str(text):
            if looks_like_feed(url, body=str(text)):
                try:
                    return read_feed(url, opener)
                except Exception:  # noqa: BLE001
                    pass
            return str(text)
    try:
        text = read_jina(url, opener)
    except Exception as exc:  # noqa: BLE001
        return "error: %scould not read %s (%s)" % (failed, url, str(exc)[:120])
    if text.startswith("error"):
        return text
    return text + "\n\n[read through Jina Reader (renders JavaScript pages)]"
