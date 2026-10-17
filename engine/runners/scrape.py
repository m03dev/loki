"""Scrape one page as markdown, or crawl a site into the workspace, with Scrapling. stdin/stdout JSON.

    {"url": "https://example.com/docs", "crawl": false, "max_pages": 20, "dynamic": false,
     "out_dir": "<workspace>/scraped/<domain>", "max_chars": 20000}

Scrapling (github.com/D4Vinci/Scrapling, BSD-3-Clause), installed with
`python tools/setup_extras.py scrapling` (pip "scrapling[rag]" + `scrapling install` for the
browsers). One page: Fetcher (plain HTTP), or DynamicFetcher (a real browser) for pages that
need JavaScript. Crawl: a SiteToMarkdownSpider limited to the start URL's domain and
max_pages, writing one markdown file per page plus pages.jsonl.

Never the stealth fetcher or any Cloudflare/bot-check solving: LOKI reads what a site
serves openly. When Scrapling is not installed this prints {"ok": false, "missing": true}
so the conductor can fall back to the web_read runner and say how to install it.
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

MAX_PAGES = 200


def _markdown(page, main_only=True):
    method = getattr(page, "markdown", None)
    if callable(method):
        try:
            return str(method(main_content_only=main_only))
        except TypeError:
            return str(method())
    if isinstance(method, str):
        return method
    for attr in ("get_all_text", "text"):
        value = getattr(page, attr, None)
        if callable(value):
            try:
                return str(value(ignore_tags=("script", "style")))
            except TypeError:
                return str(value())
        if isinstance(value, str) and value:
            return value
    return str(page)


def domain_of(url):
    return (urlparse(url).hostname or "site").lower()


def safe_name(text, limit=80):
    return (re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-.") or "index")[:limit]


def one_page(url, dynamic=False):
    if dynamic:
        from scrapling.fetchers import DynamicFetcher  # BSD-3-Clause; needs `scrapling install`
        page = DynamicFetcher.fetch(url)
    else:
        from scrapling.fetchers import Fetcher  # BSD-3-Clause
        page = Fetcher.get(url)
    return _markdown(page)


def crawl(url, out_dir, max_pages):
    from scrapling.spiders import SiteToMarkdownSpider  # BSD-3-Clause
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    host = domain_of(url)
    spider_cls = type("LokiSiteSpider", (SiteToMarkdownSpider,), {
        "name": "loki-" + safe_name(host, 40), "start_urls": [url],
        "allowed_domains": [host], "output_dir": str(out), "max_pages": int(max_pages)})
    result = spider_cls().start()
    items = getattr(result, "items", None)
    jsonl = out / "pages.jsonl"
    count = 0
    if items is not None and hasattr(items, "to_jsonl"):
        items.to_jsonl(str(jsonl))
        try:
            count = len(items)
        except TypeError:
            count = 0
    files = sorted(str(p) for p in out.rglob("*.md"))
    return {"out_dir": str(out), "jsonl": str(jsonl) if jsonl.is_file() else "", "pages": count or len(files),
            "files": files[:50]}


def main():
    job = json.loads(sys.stdin.read() or "{}")
    url = str(job.get("url", "")).strip()
    limit = int(job.get("max_chars", 20000) or 20000)
    try:
        if urlparse(url).scheme not in ("http", "https"):
            raise ValueError("scrape needs an http(s) url")
        if job.get("crawl"):
            pages = max(1, min(int(job.get("max_pages") or 20), MAX_PAGES))
            print(json.dumps({"ok": True, "crawl": True, **crawl(url, job["out_dir"], pages)}))
        else:
            text = one_page(url, bool(job.get("dynamic")))
            print(json.dumps({"ok": True, "text": text[:limit], "truncated": len(text) > limit}))
    except ImportError as exc:
        print(json.dumps({"ok": False, "missing": True,
                          "error": "Scrapling is not installed in LOKI's environment (%s)" % exc}))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}))


if __name__ == "__main__":
    main()
