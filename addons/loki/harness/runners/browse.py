"""Do one task in a real browser with browser-use (MIT). stdin/stdout JSON.

    {"task": "...", "model": "...", "base_url": "...", "api_key": "...", "max_steps": 25}
"""
import asyncio
import json
import sys


def main():
    job = json.loads(sys.stdin.read() or "{}")
    try:
        from browser_use import Agent, ChatOpenAI
    except ImportError as exc:
        print(json.dumps({"ok": False, "error": "browser-use is not installed in Loki's environment (%s)" % exc}))
        return
    kwargs = {"model": job.get("model") or "gpt-4.1-mini"}
    if job.get("base_url"):
        kwargs["base_url"] = job["base_url"]
    if job.get("api_key"):
        kwargs["api_key"] = job["api_key"]

    async def go():
        agent = Agent(task=str(job.get("task", "")), llm=ChatOpenAI(**kwargs))
        history = await agent.run(max_steps=int(job.get("max_steps", 25)))
        return history.final_result()

    try:
        result = asyncio.run(go())
        print(json.dumps({"ok": True, "text": str(result or "(the browser agent returned no result)")}))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}))


if __name__ == "__main__":
    main()
