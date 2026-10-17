"""Ask several models the same thing, side by side, and keep score (research round 3: Msty's split
chats, Cherry Studio's multi-model answers, Open WebUI's arena with its Elo leaderboard).

  run(prompt, models, ask)   every model answers at once (asyncio.gather, a per-model time limit);
                             each answer comes back with its time, length and any error. No tools:
                             this is about how a model WRITES, and it must stay cheap and safe.
  Arena.vote(winner, losers) the owner picks the better answer; Elo ratings (K=32, start 1000)
                             per model, plus wins/losses, kept in DATA_DIR/arena.json. Routing can
                             read it later; nothing decides on its own from one vote.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Awaitable, Callable

MAX_MODELS = 4
START = 1000.0
K = 32.0
_LOCK = threading.Lock()


async def run(prompt: str, models: list, ask: Callable[[str, str], Awaitable[str]],
              timeout_s: float = 120.0) -> dict:
    prompt = str(prompt or "").strip()
    names = []
    for m in models or []:
        m = str(m or "").strip()
        if m and m not in names:
            names.append(m)
    if not prompt:
        return {"ok": False, "error": "write what to ask"}
    if len(names) < 2:
        return {"ok": False, "error": "pick at least two models to compare"}
    names = names[:MAX_MODELS]

    async def one(name: str) -> dict:
        started = time.monotonic()
        try:
            text = await asyncio.wait_for(ask(name, prompt), timeout=timeout_s)
            return {"model": name, "ok": True, "text": str(text or "").strip(),
                    "seconds": round(time.monotonic() - started, 2), "chars": len(str(text or ""))}
        except asyncio.TimeoutError:
            return {"model": name, "ok": False, "error": "no answer within %d s" % timeout_s,
                    "seconds": round(time.monotonic() - started, 2)}
        except Exception as exc:  # noqa: BLE001 - one model failing must not hide the others
            return {"model": name, "ok": False, "error": ("%s: %s" % (type(exc).__name__, exc))[:300],
                    "seconds": round(time.monotonic() - started, 2)}

    answers = await asyncio.gather(*(one(n) for n in names))
    return {"ok": any(a["ok"] for a in answers), "prompt": prompt, "answers": list(answers),
            **({} if any(a["ok"] for a in answers) else {"error": "no model answered"})}


def expected(a: float, b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((b - a) / 400.0))


class Arena:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def vote(self, winner: str, losers: list, prompt: str = "") -> dict:
        winner = str(winner or "").strip()
        losers = [str(x).strip() for x in losers or [] if str(x).strip() and str(x).strip() != winner]
        if not winner or not losers:
            return {"ok": False, "error": "a vote needs the better model and at least one other"}
        with _LOCK:
            data = self._load()
            models = data.setdefault("models", {})
            for name in [winner] + losers:
                models.setdefault(name, {"rating": START, "wins": 0, "losses": 0})
            for loser in losers:          # one pairwise game per other answer (Open WebUI's sibling rule)
                w, l = models[winner], models[loser]
                e = expected(w["rating"], l["rating"])
                w["rating"] = round(w["rating"] + K * (1 - e), 1)
                l["rating"] = round(l["rating"] - K * (1 - e), 1)
                w["wins"] += 1
                l["losses"] += 1
            data.setdefault("votes", []).append({"t": time.time(), "winner": winner, "losers": losers,
                                                 "prompt": str(prompt or "")[:200]})
            data["votes"] = data["votes"][-500:]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=1), encoding="utf-8")
        return {"ok": True, "board": self.board()}

    def board(self) -> list:
        models = self._load().get("models", {})
        rows = [{"model": k, **v, "games": v.get("wins", 0) + v.get("losses", 0)} for k, v in models.items()]
        rows.sort(key=lambda r: -r["rating"])
        return rows
