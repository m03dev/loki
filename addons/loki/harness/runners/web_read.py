"""Fetch one web page as markdown/text with crawl4ai or scrapling. stdin/stdout JSON.

    {"backend": "crawl4ai" | "scrapling", "url": "...", "max_chars": 20000}
"""
import asyncio
import json
import sys


def read_crawl4ai(url):
    from crawl4ai import AsyncWebCrawler  # Apache-2.0, needs `crawl4ai-setup` once

    async def go():
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url)
            markdown = getattr(result, "markdown", "") or ""
            # newer versions return a MarkdownGenerationResult
            return str(getattr(markdown, "raw_markdown", markdown) or "")
    return asyncio.run(go())


def read_scrapling(url):
    from scrapling.fetchers import Fetcher  # BSD-3-Clause
    page = Fetcher.get(url)
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


def main():
    job = json.loads(sys.stdin.read() or "{}")
    url, backend = str(job.get("url", "")), str(job.get("backend", ""))
    limit = int(job.get("max_chars", 20000))
    try:
        if backend == "crawl4ai":
            text = read_crawl4ai(url)
        elif backend == "scrapling":
            text = read_scrapling(url)
        else:
            raise ValueError("unknown backend %r" % backend)
        print(json.dumps({"ok": True, "text": text[:limit], "truncated": len(text) > limit}))
    except ImportError as exc:
        print(json.dumps({"ok": False, "error": "%s is not installed in Loki's environment (%s)" % (backend, exc)}))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}))


if __name__ == "__main__":
    main()
