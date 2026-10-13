"""Build the API Vault seed (blueprint section 3.3).

Fetches the apis.guru public catalog, folds in Loki's own model providers, and writes a
compact, offline-searchable index to addons/loki/data/api_vault.json.

    python tools/build_api_vault.py             fetch and rebuild
    python tools/build_api_vault.py --offline   rebuild from the cached payload

Only names, URLs, providers, categories and an auth HINT are stored - never a key.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addons" / "loki" / "harness"))

import api_vault  # noqa: E402

CATALOG_URL = "https://api.apis.guru/v2/list.json"
CACHE = ROOT / "harness_data" / "apis_guru.json"
OUT = ROOT / "addons" / "loki" / "data" / "api_vault.json"


def fetch() -> dict:
    if "--offline" in sys.argv:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    try:
        # apis.guru (Cloudflare) answers 403 to urllib's default User-Agent, so set one.
        request = urllib.request.Request(CATALOG_URL, headers={"User-Agent": "loki-api-vault/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_bytes(raw)
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:  # offline or rate-limited: fall back to the cache
        print(f"catalog fetch failed ({exc}); using the cache")
        return json.loads(CACHE.read_text(encoding="utf-8"))


def loki_providers(vault: dict) -> int:
    """Fold Loki's own model providers into the vault, without their keys."""
    import loki

    added = 0
    for name, config in sorted(loki.MODELS.items()):
        base = str(getattr(config, "base_url", "") or "")
        if not base:
            continue
        auth = "none" if name in ("llm7", "ollama", "ollama-cloud") else "key"
        api_vault.add(vault, name, base, name, ["llm", "ai", "openai-compatible"],
                      auth, "", "loki")
        added += 1
    return added


def main() -> None:
    vault = api_vault.import_apis_guru(fetch())
    providers = loki_providers(vault)
    api_vault.save(OUT, vault)
    stats = api_vault.stats(vault)
    size_kb = OUT.stat().st_size / 1024
    print(f"wrote {OUT}")
    print(f"entries={stats['total']}  loki-providers={providers}  {size_kb:.0f} KiB")
    print(f"by auth: {stats['by_auth']}")


if __name__ == "__main__":
    main()
