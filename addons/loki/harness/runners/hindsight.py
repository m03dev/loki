"""Hindsight memory (MIT, vectorize-io) through its Python client. stdin/stdout JSON.

    {"op": "retain" | "recall" | "reflect", "base_url": "http://localhost:8888",
     "bank": "loki", "content": "...", "query": "..."}
"""
import json
import sys


def main():
    job = json.loads(sys.stdin.read() or "{}")
    try:
        from hindsight_client import Hindsight
    except ImportError as exc:
        print(json.dumps({"ok": False, "error": "hindsight-client is not installed in Loki's environment (%s)" % exc}))
        return
    try:
        client = Hindsight(base_url=job.get("base_url") or "http://localhost:8888")
        bank, op = job.get("bank") or "loki", job.get("op")
        if op == "retain":
            result = client.retain(bank_id=bank, content=str(job.get("content", "")))
        elif op == "recall":
            result = client.recall(bank_id=bank, query=str(job.get("query", "")))
        elif op == "reflect":
            result = client.reflect(bank_id=bank, query=str(job.get("query", "")))
        else:
            raise ValueError("op must be retain, recall or reflect")
        if hasattr(result, "model_dump"):
            result = result.model_dump()
        print(json.dumps({"ok": True, "result": result}, default=str))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}))


if __name__ == "__main__":
    main()
