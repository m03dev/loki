"""Shared helpers for the Loki tests."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))

import loki  # noqa: E402


async def run_agent_turn(prompt: str, timeout: int = 240) -> str:
    """Send one prompt through the real agent loop and return its final text."""
    loki.messages[:] = [{"role": "system", "content": loki.SYSTEM_PROMPT.format(memory="")}]
    loki.loki_progress_callback = lambda event, text: None
    loki.messages.append({"role": "user", "content": prompt})
    try:
        return await asyncio.wait_for(loki.agent_turn(), timeout=timeout)
    except Exception as exc:
        return "Traceback: %s: %s" % (type(exc).__name__, exc)
