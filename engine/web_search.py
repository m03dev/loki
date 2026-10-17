"""Web search and cited research, built into LOKI - no add-on, no key.

Ported into LOKI (session 27 harvest) from Vane (formerly Perplexica, github.com/ItzCrazyKns/Vane),
MIT License, Copyright (c) 2026 ItzCrazyKns - see engine/licenses/Vane-MIT.txt:
  - src/lib/searxng.ts: the SearxNG JSON client (`/search?format=json&q=...`, engines and
    categories as comma lists, 10 s timeout), used when LOKI_SEARXNG_URL points at a SearxNG.
  - the focus modes of src/lib/agents/search/researcher/actions/search: web, academic
    (engines arxiv, google scholar, pubmed), discussion (engines reddit).
  - src/lib/prompts/search/writer.ts: the citation rules - every sentence cites its source
    with [n], several sources as [1][2], say plainly when nothing relevant was found.
  - the researcher's "mistakes to avoid" (do not verify existence, stop after 2-3 empty
    searches, targeted queries, at most 3 per call).
Without SearxNG LOKI uses keyless public endpoints: DuckDuckGo's HTML page for the web,
arXiv's Atom API for academic mode, Wikipedia's search API as the last fallback.

`research()` is Vane's pipeline in one call: search -> read the best pages natively
(web_reader) -> keep only the relevant parts (content_filter.focus, crawl4ai's BM25) ->
numbered sources + the writer's citation rules, ready for the model to answer from.
Standard library only; every network call goes through `opener` so tests run offline.
"""
from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

try:
    import web_reader
    import content_filter
except ImportError:  # pragma: no cover
    from engine import web_reader, content_filter  # type: ignore

TIMEOUT_S = 12
MAX_RESULTS = 8
MODES = ("web", "academic", "discussion", "news")
SEARXNG_ENGINES = {"academic": ["arxiv", "google scholar", "pubmed"], "discussion": ["reddit"]}
SEARXNG_CATEGORIES = {"news": ["news"]}

WRITER_RULES = """How to answer from these sources (Vane's citation rules):
- Answer the question directly, then add the detail that matters. Use markdown headings only for a long answer.
- Cite every fact with [number] for the source it came from, at the end of the sentence, e.g. "It was released in 2024[2]." Use [1][3] when several sources say it.
- Use ONLY what the sources say for facts; if they do not cover something, say so plainly instead of guessing.
- If nothing relevant was found, say so and suggest a better search.
- End with a short "Sources" list: [n] title - url."""

SEARCH_TIPS = ("Search tips: targeted queries (the thing's exact name, plus one qualifier); do not search just "
               "to verify something exists; if 2-3 searches find nothing, say it probably does not exist.")


def searxng_url() -> str:
    return str(os.getenv("LOKI_SEARXNG_URL", "")).strip().rstrip("/")


def _get(url: str, opener=None, headers: dict | None = None, timeout: float = TIMEOUT_S) -> str:
    req = urllib.request.Request(url, headers=headers or web_reader.headers(url))
    open_fn = opener or urllib.request.urlopen
    with open_fn(req, timeout=timeout) as resp:
        body = resp.read(3 * 1024 * 1024)
        info = getattr(resp, "headers", {}) or {}
        ctype = info.get("Content-Type", "") if hasattr(info, "get") else ""
        cenc = info.get("Content-Encoding", "") if hasattr(info, "get") else ""
    return web_reader._decode(body, ctype, cenc)   # noqa: SLF001 - same package, shared decoder


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", str(text or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


# --------------------------------------------------------------------------- engines
def search_searxng(query: str, mode: str = "web", opener=None, base: str = "") -> list:
    """Vane's searxng.ts: GET {base}/search?format=json&q=...&engines=a,b."""
    base = (base or searxng_url()).rstrip("/")
    params = {"format": "json", "q": query}
    if SEARXNG_ENGINES.get(mode):
        params["engines"] = ",".join(SEARXNG_ENGINES[mode])
    if SEARXNG_CATEGORIES.get(mode):
        params["categories"] = ",".join(SEARXNG_CATEGORIES[mode])
    data = json.loads(_get(base + "/search?" + urllib.parse.urlencode(params), opener,
                           headers={"Accept": "application/json", "User-Agent": web_reader.user_agent()}))
    out = []
    for r in data.get("results") or []:
        if r.get("url"):
            out.append({"title": _clean(r.get("title", "")), "url": r["url"],
                        "snippet": _clean(r.get("content", ""))[:400], "engine": "searxng:" + str(r.get("engine", ""))})
    return out


_DDG_RESULT = re.compile(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
_DDG_SNIPPET = re.compile(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|td|div)>', re.S | re.I)


def _ddg_target(href: str) -> str:
    href = html.unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
        return target
    return href


def parse_duckduckgo(page: str) -> list:
    links = _DDG_RESULT.findall(page)
    snippets = _DDG_SNIPPET.findall(page)
    out = []
    for i, (href, title) in enumerate(links):
        url = _ddg_target(href)
        if not url.startswith("http") or "duckduckgo.com/y.js" in url:   # ads
            continue
        out.append({"title": _clean(title), "url": url,
                    "snippet": _clean(snippets[i])[:400] if i < len(snippets) else "", "engine": "duckduckgo"})
    return out


def search_duckduckgo(query: str, opener=None) -> list:
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    return parse_duckduckgo(_get(url, opener))


def parse_arxiv(atom: str) -> list:
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(atom.encode("utf-8"))
    out = []
    for entry in root.findall("a:entry", ns):
        title = _clean(entry.findtext("a:title", "", ns))
        link = entry.findtext("a:id", "", ns)
        summary = _clean(entry.findtext("a:summary", "", ns))
        authors = ", ".join(_clean(a.findtext("a:name", "", ns)) for a in entry.findall("a:author", ns)[:3])
        published = (entry.findtext("a:published", "", ns) or "")[:10]
        if link:
            out.append({"title": title, "url": link, "engine": "arxiv",
                        "snippet": ("%s (%s) - %s" % (authors, published, summary))[:400]})
    return out


def search_arxiv(query: str, opener=None, max_results: int = MAX_RESULTS) -> list:
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"search_query": "all:" + query, "start": 0, "max_results": max_results, "sortBy": "relevance"})
    return parse_arxiv(_get(url, opener))


def search_wikipedia(query: str, opener=None, lang: str = "en") -> list:
    url = "https://%s.wikipedia.org/w/api.php?%s" % (lang, urllib.parse.urlencode(
        {"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 6}))
    data = json.loads(_get(url, opener, headers={"User-Agent": "LOKI/1.0 (personal agent)"}))
    out = []
    for r in (data.get("query") or {}).get("search") or []:
        title = r.get("title", "")
        out.append({"title": title, "engine": "wikipedia", "snippet": _clean(r.get("snippet", ""))[:400],
                    "url": "https://%s.wikipedia.org/wiki/%s" % (lang, urllib.parse.quote(title.replace(" ", "_")))})
    return out


def _dedupe(results: list, limit: int) -> list:
    seen, out = set(), []
    for r in results:
        key = re.sub(r"^https?://(www\.)?", "", r.get("url", "")).rstrip("/").lower()
        if key and key not in seen:
            seen.add(key)
            out.append(r)
        if len(out) >= limit:
            break
    return out


def search(query: str, mode: str = "web", max_results: int = MAX_RESULTS, opener=None) -> dict:
    """{"results": [{title, url, snippet, engine}], "engine": "...", "errors": [...]}."""
    query = str(query or "").strip()
    mode = mode if mode in MODES else "web"
    if not query:
        return {"results": [], "engine": "", "errors": ["empty query"]}
    errors, plan = [], []
    if searxng_url():
        plan.append(("searxng", lambda: search_searxng(query, mode, opener)))
    if mode == "academic":
        plan.append(("arxiv", lambda: search_arxiv(query, opener, max_results)))
    q = (query + " site:reddit.com") if mode == "discussion" and "site:" not in query else \
        (query + " news") if mode == "news" else query
    plan.append(("duckduckgo", lambda: search_duckduckgo(q, opener)))
    plan.append(("wikipedia", lambda: search_wikipedia(query, opener)))
    for name, run in plan:
        try:
            results = _dedupe(run(), max(1, int(max_results)))
        except Exception as exc:  # noqa: BLE001 - try the next engine
            errors.append("%s: %s" % (name, str(exc)[:120]))
            continue
        if results:
            return {"results": results, "engine": name, "errors": errors}
        errors.append("%s: no results" % name)
    return {"results": [], "engine": "", "errors": errors}


def format_results(query: str, found: dict) -> str:
    results = found.get("results") or []
    if not results:
        why = "; ".join(found.get("errors") or []) or "no results"
        return 'error: no search results for "%s" (%s). %s' % (query, why, SEARCH_TIPS)
    lines = ['%d results for "%s" (%s):' % (len(results), query, found.get("engine"))]
    for i, r in enumerate(results, 1):
        lines.append("[%d] %s\n    %s%s" % (i, r.get("title") or r["url"], r["url"],
                                           ("\n    " + r["snippet"]) if r.get("snippet") else ""))
    lines.append("Read a result with read_web(url, query=...) to keep only the part you need.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- research (Vane's pipeline)
def research(question: str, mode: str = "web", pages: int = 3, opener=None, read=None,
             per_source_chars: int = 2500, queries: list | None = None) -> str:
    """Search, read the best pages, keep the relevant parts, number the sources.

    `read(url) -> markdown or "error: ..."` reads one page (LOKI passes its own read_web so
    private hosts stay refused); the default reads natively with web_reader."""
    question = str(question or "").strip()
    if not question:
        return "error: give a question to research"
    pages = max(1, min(int(pages or 3), 6))
    reader = read or (lambda url: web_reader.read(url, max_chars=40000, opener=opener))
    started = time.monotonic()
    all_results, engines, errors = [], [], []
    for q in ([question] + [x for x in (queries or []) if str(x).strip()][:2]):
        found = search(q, mode=mode, max_results=MAX_RESULTS, opener=opener)
        all_results.extend(found.get("results") or [])
        if found.get("engine"):
            engines.append(found["engine"])
        errors.extend(found.get("errors") or [])
    results = _dedupe(all_results, MAX_RESULTS * 2)
    if not results:
        return 'error: no search results for "%s" (%s). %s' % (question, "; ".join(errors) or "no results", SEARCH_TIPS)
    sources = []
    for r in results:
        if len(sources) >= pages:
            break
        text = reader(r["url"])
        if not text or str(text).startswith("error"):
            continue
        part = content_filter.focus(str(text), question, max_chars=per_source_chars) or str(text)[:per_source_chars]
        sources.append({"title": r.get("title") or r["url"], "url": r["url"], "text": part.strip()})
    # snippets of the results we did not read still help (and are cheap)
    extra = [r for r in results if r["url"] not in {s["url"] for s in sources}][:5]
    blocks = []
    for i, s in enumerate(sources, 1):
        blocks.append("[%d] %s - %s\n%s" % (i, s["title"], s["url"], s["text"]))
    for j, r in enumerate(extra, len(sources) + 1):
        if r.get("snippet"):
            blocks.append("[%d] %s - %s (search snippet only)\n%s" % (j, r.get("title") or r["url"], r["url"], r["snippet"]))
    if not blocks:
        return 'error: found results for "%s" but could not read any of them' % question
    return ("Research for: %s\n(%d page(s) read, %d snippet(s); engines: %s; %.1fs)\n\n<sources>\n%s\n</sources>\n\n%s"
            % (question, len(sources), len(blocks) - len(sources), ", ".join(dict.fromkeys(engines)) or "-",
               time.monotonic() - started, "\n\n".join(blocks), WRITER_RULES))
