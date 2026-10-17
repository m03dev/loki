"""Map a website: every page URL it has, without crawling it - LOKI's own Firecrawl `map`.

Ported into LOKI (session 27 harvest) from Firecrawl (github.com/firecrawl/firecrawl,
apps/api/src/lib/map-utils.ts getMapResults, lib/map-cosine.ts performCosineSimilarity,
scraper/crawler/sitemap.ts), AGPL-3.0 - see engine/licenses/Firecrawl-AGPL-3.0.txt. LOKI is
private (docs/THIRD_PARTY.md). Re-written on the standard library:
  - sources: robots.txt `Sitemap:` lines, /sitemap.xml and /sitemap_index.xml (nested
    sitemap indexes followed, .gz unpacked), plus the links on the start page;
  - filters: same domain (subdomains only when asked), and when the start URL has a path,
    only URLs under that path (Firecrawl's filterByPath);
  - `search`: links ranked by Firecrawl's word-vector cosine similarity to the search words;
  - de-duplicated (trailing slash, #fragment, www.) and capped at `limit`.
Every network call goes through `opener`, so tests run offline.
"""
from __future__ import annotations

import gzip
import math
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

try:
    import web_reader
except ImportError:  # pragma: no cover
    from engine import web_reader  # type: ignore

MAX_SITEMAPS = 12
MAX_LIMIT = 5000
TIMEOUT_S = 15
_HREF = re.compile(r"""<a\s[^>]*href\s*=\s*["']([^"'#]+)""", re.I)


def _fetch(url: str, opener=None) -> str:
    req = urllib.request.Request(url, headers=web_reader.headers(url))
    open_fn = opener or urllib.request.urlopen
    with open_fn(req, timeout=TIMEOUT_S) as resp:
        body = resp.read(20 * 1024 * 1024)
        info = getattr(resp, "headers", {}) or {}
        ctype = info.get("Content-Type", "") if hasattr(info, "get") else ""
        cenc = info.get("Content-Encoding", "") if hasattr(info, "get") else ""
    if url.lower().endswith(".gz") or body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
        cenc = ""
    return web_reader._decode(body, ctype, cenc)   # noqa: SLF001


def _host(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or "").lower()


def _base_domain(host: str) -> str:
    parts = host.split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in ("co", "com", "org", "net", "ac", "gov"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def normalize(url: str) -> str:
    p = urllib.parse.urlparse(url)
    path = p.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    host = (p.hostname or "").lower()
    return urllib.parse.urlunparse((p.scheme.lower(), host + ((":%d" % p.port) if p.port else ""), path, "", p.query, ""))


def _key(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", normalize(url)).lower()


def parse_sitemap(xml_text: str) -> tuple:
    """(page urls, nested sitemap urls) from a sitemap or a sitemap index."""
    urls, maps = [], []
    try:
        root = ET.fromstring(xml_text.strip().encode("utf-8"))
    except ET.ParseError:
        # some servers send a plain-text sitemap: one URL per line
        for line in xml_text.splitlines():
            if line.strip().startswith(("http://", "https://")):
                urls.append(line.strip())
        return urls, maps
    tag = root.tag.split("}")[-1].lower()
    for loc in root.iter():
        if loc.tag.split("}")[-1].lower() != "loc" or not (loc.text or "").strip():
            continue
        (maps if tag == "sitemapindex" else urls).append(loc.text.strip())
    return urls, maps


def robots_sitemaps(robots: str) -> list:
    return [line.split(":", 1)[1].strip() for line in robots.splitlines()
            if line.lower().startswith("sitemap:") and ":" in line]


def page_links(page_html: str, base: str) -> list:
    out = []
    for href in _HREF.findall(page_html or ""):
        href = href.strip()
        if href.startswith(("mailto:", "javascript:", "tel:", "data:")):
            continue
        out.append(urllib.parse.urljoin(base, href))
    return out


def cosine_rank(links: list, search: str) -> list:
    """Firecrawl's performCosineSimilarity: each text becomes, per search word, its count of
    that word divided by the text's length; links are sorted by cosine to the search itself."""
    words = [w for w in re.split(r"\W+", search.lower()) if w]
    if not words:
        return links

    def vec(text: str) -> list:
        low = text.lower()
        return [low.count(w) / (len(low) or 1) for w in words]

    def cos(a: list, b: list) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
        return 0.0 if not na or not nb else dot / (na * nb)
    target = vec(search)
    scored = [(cos(vec(link), target), i, link) for i, link in enumerate(links)]
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [link for score, _i, link in scored if score > 0] + [link for score, _i, link in scored if score <= 0]


def map_site(url: str, search: str = "", limit: int = 200, include_subdomains: bool = False,
             opener=None) -> dict:
    """{"ok", "urls": [...], "sources": {...}, "total": n, "error"?}."""
    url = str(url or "").strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urllib.parse.urlparse(url)
    if not parsed.hostname:
        return {"ok": False, "error": "map_site needs a website address"}
    origin = "%s://%s" % (parsed.scheme, parsed.netloc)
    host = _host(url)
    limit = max(1, min(int(limit or 200), MAX_LIMIT))
    found, sources = [], {"sitemap": 0, "page": 0}
    sitemap_urls = []
    try:
        sitemap_urls += robots_sitemaps(_fetch(origin + "/robots.txt", opener))
    except Exception:  # noqa: BLE001 - no robots.txt is normal
        pass
    for fallback in ("/sitemap.xml", "/sitemap_index.xml"):
        if origin + fallback not in sitemap_urls:
            sitemap_urls.append(origin + fallback)
    seen_maps = set()
    queue = list(sitemap_urls)
    while queue and len(seen_maps) < MAX_SITEMAPS:
        sm = queue.pop(0)
        if sm in seen_maps:
            continue
        seen_maps.add(sm)
        try:
            urls, nested = parse_sitemap(_fetch(sm, opener))
        except Exception:  # noqa: BLE001
            continue
        found += urls
        sources["sitemap"] += len(urls)
        queue += [n for n in nested if n not in seen_maps]
    try:
        links = page_links(_fetch(url, opener), url)
        found += links
        sources["page"] += len(links)
    except Exception as exc:  # noqa: BLE001
        if not found:
            return {"ok": False, "error": "could not reach %s (%s)" % (url, str(exc)[:120])}
    base = _base_domain(host)
    path = parsed.path if parsed.path not in ("", "/") else ""
    out, seen = [], set()
    for link in found:
        h = _host(link)
        if not h:
            continue
        same = (h == host or h == "www." + host or "www." + h == host) if not include_subdomains else \
            (h == base or h.endswith("." + base))
        if not same:
            continue
        if path and not urllib.parse.urlparse(link).path.startswith(path.rstrip("/")):
            continue
        k = _key(link)
        if k in seen:
            continue
        seen.add(k)
        out.append(normalize(link))
    if search:
        out = cosine_rank(out, search)
    return {"ok": True, "urls": out[:limit], "total": len(out), "sources": sources}


def format_map(url: str, result: dict, search: str = "") -> str:
    if not result.get("ok"):
        return "error: %s" % result.get("error")
    urls = result.get("urls") or []
    if not urls:
        return "no pages found for %s (no sitemap and no links on the page)" % url
    head = "%d page(s) on %s%s (%d from sitemaps, %d linked from the page)%s:" % (
        result.get("total", len(urls)), _host(url) or url, (" ranked for '%s'" % search) if search else "",
        result["sources"]["sitemap"], result["sources"]["page"],
        (", first %d shown" % len(urls)) if result.get("total", 0) > len(urls) else "")
    return head + "\n" + "\n".join(urls)
