"""The API Vault (blueprint section 3.3).

The blueprint asks Loki to know which APIs exist - what they do, where their docs are,
whether they need a key and what they cost - so it can propose one and then reach it
through a single adapter. This module is that vault: a flat, searchable index of API
entries, seeded from a real catalog and open to Loki's own providers and integrations.

Pure functions over plain dicts, so they are unit-testable and the file format is ours.
Entry shape (all strings except categories):

    id          stable slug
    name        display name
    url         where to reach it
    provider    who runs it
    categories  list of tags, for filtering
    auth        none | key | oauth | unknown
    docs        link to documentation
    source      where the entry came from (apis.guru, loki, manual, ...)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

FIELDS = ("id", "name", "url", "provider", "categories", "auth", "docs", "source")
AUTH_VALUES = ("none", "key", "oauth", "unknown")


def empty() -> dict:
    return {"version": 1, "entries": []}


def slug(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return cleaned or "api"


def normalize(entry: dict, source: str = "") -> dict:
    name = str(entry.get("name") or entry.get("title") or entry.get("id") or "").strip()
    auth = str(entry.get("auth") or "unknown").strip().lower()
    categories = entry.get("categories") or []
    if isinstance(categories, str):
        categories = [c.strip() for c in categories.split(",") if c.strip()]
    return {
        "id": str(entry.get("id") or slug(name)),
        "name": name,
        "url": str(entry.get("url") or ""),
        "provider": str(entry.get("provider") or ""),
        "categories": [str(c) for c in categories],
        "auth": auth if auth in AUTH_VALUES else "unknown",
        "docs": str(entry.get("docs") or ""),
        "source": str(entry.get("source") or source or "manual"),
    }


def add(data: dict, name: str, url: str = "", provider: str = "", categories=None,
        auth: str = "unknown", docs: str = "", source: str = "manual") -> dict:
    entry = normalize({"name": name, "url": url, "provider": provider,
                       "categories": categories or [], "auth": auth, "docs": docs,
                       "source": source})
    entries = data.setdefault("entries", [])
    for i, existing in enumerate(entries):
        if existing.get("id") == entry["id"]:
            entries[i] = entry
            return entry
    entries.append(entry)
    return entry


def search(data: dict, query: str = "", category: str = "", auth: str = "",
           limit: int = 25) -> list:
    needle = str(query).strip().lower()
    words = [w for w in needle.split() if w]
    hits = []
    for entry in data.get("entries", []):
        if auth and entry.get("auth") != auth:
            continue
        if category and category.lower() not in [c.lower() for c in entry.get("categories", [])]:
            continue
        haystack = " ".join([entry.get("name", ""), entry.get("id", ""),
                             entry.get("url", ""), entry.get("provider", ""),
                             entry.get("docs", "")] + list(entry.get("categories", []))).lower()
        if all(word in haystack for word in words):
            hits.append(entry)
    hits.sort(key=lambda e: (0 if needle and e.get("name", "").lower().startswith(needle) else 1,
                             e.get("name", "").lower()))
    return hits[:max(1, int(limit))]


def stats(data: dict) -> dict:
    entries = data.get("entries", [])
    by_auth: dict = {}
    by_source: dict = {}
    for entry in entries:
        by_auth[entry.get("auth", "unknown")] = by_auth.get(entry.get("auth", "unknown"), 0) + 1
        by_source[entry.get("source", "manual")] = by_source.get(entry.get("source", "manual"), 0) + 1
    return {"total": len(entries), "by_auth": by_auth, "by_source": by_source}


def render(entries, title: str = "") -> str:
    if isinstance(entries, dict):
        entries = entries.get("entries", [])
    lines = []
    if title:
        lines.append(title)
    if not entries:
        lines.append("no matching APIs")
        return chr(10).join(lines)
    for entry in entries:
        auth = entry.get("auth", "unknown")
        mark = {"none": "-", "key": "K", "oauth": "O", "unknown": "?"}.get(auth, "?")
        cats = ", ".join(entry.get("categories", [])[:3])
        lines.append("%s %-28s %-40s %s" % (
            mark, str(entry.get("name", ""))[:28],
            str(entry.get("url", ""))[:40], cats))
    lines.append("")
    lines.append("K = needs a key   O = OAuth   - = no auth   ? = unknown")
    return chr(10).join(lines)


def load(path) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty()
    if not isinstance(payload, dict):
        return empty()
    payload.setdefault("entries", [])
    return payload


def save(path, data: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                      encoding="utf-8")


def import_apis_guru(payload: dict, source: str = "apis.guru", limit: int = 0) -> dict:
    """Normalize an apis.guru list.json payload into a vault.

    apis.guru keys the catalog by API host; each value has versions, and the preferred
    version carries the info block, the origin URL, the provider name, the categories and
    the security schemes. We keep the display name, the reachable URL, the provider, the
    categories and whether a key/oauth is needed - nothing else, to stay compact.
    """
    vault = empty()
    count = 0
    for host, record in (payload or {}).items():
        if not isinstance(record, dict):
            continue
        versions = record.get("versions") or {}
        preferred = record.get("preferred") or (next(iter(versions), ""))
        version = versions.get(preferred) or {}
        info = version.get("info") or {}
        name = str(info.get("title") or host).strip()
        url = ""
        origins = version.get("x-origin") or []
        if origins and isinstance(origins, list) and isinstance(origins[0], dict):
            url = str(origins[0].get("url") or "")
        if not url:
            contact = info.get("contact") or {}
            url = str(contact.get("url") or host)
        auth = "unknown"
        security = version.get("security") or version.get("securityDefinitions") or {}
        specs = version.get("swagger") or version.get("openapi") or {}
        if isinstance(specs, dict):
            security = security or specs.get("security") or specs.get("securityDefinitions") or {}
        if isinstance(security, dict) and security:
            kinds = " ".join(str(k).lower() for k in security.keys())
            if "oauth" in kinds:
                auth = "oauth"
            elif "key" in kinds or "bearer" in kinds or "basic" in kinds:
                auth = "key"
            else:
                auth = "key"
        add(vault, name, url, str(version.get("x-providerName") or ""),
            version.get("x-apisguru-categories") or [], auth, "", source)
        count += 1
        if limit and count >= limit:
            break
    return vault
