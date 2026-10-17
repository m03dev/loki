"""LOKI World MMO - the game state any client uses (the in-app world, the Godot client).

The game is made of LOKI's real work, never invented:
    quests    = background jobs (accept one = start a job; finished = turn it in for XP)
    monsters  = jobs that failed (defeat one for XP and a lesson scroll; or retry it on a
                stronger model, which starts the job again)
    loot      = what LOKI made (pictures, videos, sounds, games: creations.py)
    NPCs      = the agents of GET /world, with a class from their role and a level from the
                jobs that role finished
    skills    = the hotbar: combat skills (the client plays them out) and LOKI actions
                (make a picture, research, build, ...) that start real jobs
    profile   = the player's name, class, XP and stats on this machine
The contract for clients is docs/MMO_API.md. Progress is kept in <data>/mmo/profile.json
(harness_data, never committed). Everything here is a pure function of (profile, jobs,
creations, agents) except Profile, which owns that one file.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

VERSION = 1
CLASSES = {
    "Warrior": {"color": "#d9604f", "about": "Front line. Strikes hard, shrugs off hits.", "hp": 1.2, "power": 1.0},
    "Mage": {"color": "#8b7bff", "about": "Bolts from afar; the arcane does the work.", "hp": 0.9, "power": 1.2},
    "Archer": {"color": "#55b85c", "about": "Quick and precise at range.", "hp": 1.0, "power": 1.1},
    "Shaman": {"color": "#2ec4b6", "about": "Mends wounds; spirits answer.", "hp": 1.05, "power": 0.95},
}
NPC_CLASSES = [
    (r"^loki$|conductor", "Trickster", "#2ee6d6"), (r"research|hermes", "Sage", "#3fa9ff"),
    (r"architect", "Arcanist", "#b46cff"), (r"browser", "Scout", "#4d7cff"), (r"test", "Alchemist", "#ffc23d"),
    (r"review", "Paladin", "#ff7a45"), (r"build|loki agent|claude|codex|opencode|openhands|agent", "Smith", "#36e07a"),
]
MONSTERS = [   # what a failure looks like, from its error text
    (r"time ?out|timed out|deadline", "Timeout Wraith", "wraith"),
    (r"rate.?limit|429|quota|too many requests", "Rate-Limit Slime", "slime"),
    (r"syntax|parse|json|decode|unexpected token", "Syntax Golem", "golem"),
    (r"permission|denied|policy|forbidden|approval|blocked", "Gatekeeper Goblin", "goblin"),
    (r"network|connect|unreachable|dns|refused|ssl|certificate", "Netwisp", "wisp"),
    (r"api key|provider|model|unauthori[sz]ed|401", "Model Mimic", "mimic"),
    (r"test|assert|fail", "Bug Beetle", "beetle"),
]
RARITY = {"image": "rare", "video": "epic", "audio": "uncommon", "sketch": "common", "game": "legendary"}
QUEST_STATES = {"queued": "active", "starting": "active", "working": "active", "blocked": "active",
                "done": "complete", "failed": "failed", "cancelled": "cancelled"}

# The hotbar. kind: "combat" (needs a monster target, the client plays it out), "self" (on you),
# "loki" (a LOKI action: POST /mmo/skill starts a real background job), "travel".
SKILLS = [
    {"slot": 1, "id": "strike", "name": "Strike", "kind": "combat", "cd_s": 1.1, "energy": 0, "cast_s": 0, "range": 2.2, "dmg": [10, 16]},
    {"slot": 2, "id": "bolt", "name": "Bolt", "kind": "combat", "cd_s": 2.5, "energy": 18, "cast_s": 0.7, "range": 9, "dmg": [15, 24]},
    {"slot": 3, "id": "mend", "name": "Mend", "kind": "self", "cd_s": 10, "energy": 25, "cast_s": 1.0, "heal": [30, 40]},
    {"slot": 4, "id": "image", "name": "Make a picture", "kind": "loki", "cd_s": 8, "energy": 0, "cast_s": 1.5, "ask": "a picture of..."},
    {"slot": 5, "id": "research", "name": "Research", "kind": "loki", "cd_s": 8, "energy": 0, "cast_s": 1.5, "ask": "find out about..."},
    {"slot": 6, "id": "build", "name": "Build", "kind": "loki", "cd_s": 8, "energy": 0, "cast_s": 1.5, "ask": "build or change..."},
    {"slot": 7, "id": "video", "name": "Make a video", "kind": "loki", "cd_s": 8, "energy": 0, "cast_s": 1.5, "ask": "a video of..."},
    {"slot": 8, "id": "game", "name": "Make a game", "kind": "loki", "cd_s": 8, "energy": 0, "cast_s": 1.5, "ask": "a game where..."},
    {"slot": 9, "id": "hearth", "name": "Hearth", "kind": "travel", "cd_s": 30, "energy": 0, "cast_s": 2.5},
]
LOKI_ACTIONS = {s["id"] for s in SKILLS if s["kind"] == "loki"}
MAX_TEXT = 2000
MONSTER_DAYS = 7
MONSTERS_MAX = 6


def _clean(value: Any, limit: int) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(value or "")).strip()[:limit]


def xp_to_next(level: int) -> int:
    return int(round(80 * math.pow(level, 1.55)))


def level_of(xp: float) -> dict:
    lvl, left = 1, max(0, int(xp or 0))
    while lvl < 99 and left >= xp_to_next(lvl):
        left -= xp_to_next(lvl)
        lvl += 1
    return {"level": lvl, "xp_into": left, "xp_need": xp_to_next(lvl)}


def npc_class(role: str) -> dict:
    r = str(role or "").lower()
    for pattern, name, color in NPC_CLASSES:
        if re.search(pattern, r):
            return {"name": name, "color": color}
    return {"name": "Adventurer", "color": "#9aa0aa"}


def role_of(job: dict) -> str:
    """The same role events.world() gives the job's agent (so NPC levels match the agents)."""
    title = str(job.get("title") or "")
    if title.startswith("Team ") and "·" in title:
        return title.split("·", 1)[1].split(":", 1)[0].strip()
    if job.get("agent_id") and ":" in title:
        return title.split(":", 1)[0].strip()[:40]
    agent = str(job.get("agent") or "")
    return "Loki agent" if agent == "loki" else agent or "agent"


def quest_kind(job: dict) -> str:
    text = str(job.get("prompt") or job.get("title") or "")
    for prefix, kind in (("Make an image", "image"), ("Make a short video", "video"), ("Make a small game", "game"),
                         ("Research:", "research"), ("Retry:", "retry"), ("Team ", "team")):
        if text.startswith(prefix) or str(job.get("title") or "").startswith(prefix):
            return kind
    return "task"


def _hash(text: str) -> int:
    return int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:8], 16)


def action_prompt(skill: str, text: str) -> str:
    """The prompt a LOKI-action skill sends (the same words Settings > Creations uses)."""
    what = _clean(text, MAX_TEXT)
    if not what:
        raise ValueError("say what to make or do")
    if skill == "image":
        return "Make an image of " + what + ". Save it in images/ and say where it is."
    if skill == "video":
        return "Make a short video of: " + what + ". Save it in videos/ and say where it is."
    if skill == "game":
        return ("Make a small game with LOKI's Pixel Engine (read game_engine_guide first): " + what +
                ". Save it as games/<short-name>/game.js so it shows in Play.")
    if skill == "research":
        return ("Research: " + what + ". Find good sources, write what you learned to research/<short-name>.md "
                "with the links, and give me a short summary.")
    if skill == "build":
        return what
    raise ValueError("%s is not a LOKI action" % skill)


def job_spec(skill: str, text: str) -> dict:
    """POST /jobs body for a LOKI-action skill: the built-in agent, an isolated worktree."""
    return {"backend": "local", "agent": "loki", "prompt": action_prompt(skill, text), "isolate": True, "timeout_s": 1800}


# ------------------------------------------------------------------ the saved profile
class Profile:
    """<data>/mmo/profile.json, read and written under one lock (atomic replace)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock = threading.RLock()
        self.data = self._load()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        data.setdefault("version", VERSION)
        data["name"] = _clean(data.get("name"), 24) or "Mohamed"
        data["cls"] = data.get("cls") if data.get("cls") in CLASSES else ""
        data["xp"] = int(data.get("xp") or 0)
        for key in ("turned_in", "slain", "seen_creations", "done_seen"):
            if not isinstance(data.get(key), dict):
                data[key] = {}
        if not isinstance(data.get("scrolls"), list):
            data["scrolls"] = []
        stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
        data["stats"] = {k: int(stats.get(k) or 0) for k in ("quests", "kills", "deaths", "casts", "loot", "retries")}
        data.setdefault("init", False)
        return data

    def save(self) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)


_PROFILES: dict = {}
_PROFILES_LOCK = threading.Lock()


def profile_for(data_dir: Path) -> Profile:
    path = Path(data_dir) / "mmo" / "profile.json"
    with _PROFILES_LOCK:
        if str(path) not in _PROFILES:
            _PROFILES[str(path)] = Profile(path)
        return _PROFILES[str(path)]


# ------------------------------------------------------------------ building the state
def _player_class(prof: dict, self_os: str) -> str:
    if prof.get("cls") in CLASSES:
        return prof["cls"]
    return "Mage" if re.search(r"darwin|mac", self_os or "", re.I) else "Warrior" if re.search(r"win", self_os or "", re.I) else "Shaman"


def first_run(prof: Profile, jobs: list, creations: list) -> dict | None:
    """The first time: the owner's past work counts. Done jobs are already turned in (as XP),
    old failures are already beaten (only the newest few become monsters), everything made so
    far is already in the bags."""
    with prof.lock:
        d = prof.data
        if d.get("init"):
            return None
        done = [j for j in jobs if j.get("status") == "done"]
        failed = sorted([j for j in jobs if j.get("status") == "failed"], key=lambda j: float(j.get("finished") or 0), reverse=True)
        now = time.time()
        for j in done:
            d["turned_in"][str(j["id"])] = now
            d["done_seen"][str(j["id"])] = role_of(j)
        for j in failed[3:]:
            d["slain"][str(j["id"])] = now
        for c in creations:
            d["seen_creations"][str(c.get("path"))] = now
        grant = 60 * len(done) + 15 * len(creations)
        d["xp"] += grant
        d["stats"]["quests"] += len(done)
        d["init"] = True
        prof.save()
        return {"xp": grant, "quests": len(done), "creations": len(creations), **level_of(d["xp"])}


def quest_xp(job: dict) -> int:
    started, finished = float(job.get("started") or job.get("created") or 0), float(job.get("finished") or 0)
    minutes = max(0.0, (finished - started) / 60.0) if finished and started else 0.0
    return int(100 + 20 * min(10.0, minutes))


def quests(prof: dict, jobs: list) -> list:
    out = []
    for j in sorted(jobs, key=lambda j: float(j.get("created") or 0), reverse=True)[:60]:
        jid = str(j.get("id"))
        status = QUEST_STATES.get(str(j.get("status") or ""), "active")
        if status == "complete" and jid in prof["turned_in"]:
            status = "turned_in"
        if status == "failed" and jid in prof["slain"]:
            status = "beaten"
        job_status = str(j.get("status") or "")
        objective = {"queued": "Waiting for a free agent", "starting": "Starting", "working": "%s is on it" % role_of(j),
                     "blocked": "Needs you: answer it in LOKI", "done": "Done - turn it in", "failed": "Failed - a monster appeared",
                     "cancelled": "Cancelled"}.get(job_status, job_status)
        out.append({"id": jid, "title": _clean(j.get("title"), 120), "kind": quest_kind(j), "status": status,
                    "job_status": job_status, "objective": objective, "role": role_of(j), "giver": "LOKI",
                    "created": float(j.get("created") or 0), "started": float(j.get("started") or 0),
                    "finished": float(j.get("finished") or 0), "xp": quest_xp(j)})
    return out


def monster_for(job: dict, player_level: int, self_name: str) -> dict:
    jid = str(job.get("id"))
    error = _clean(job.get("error") or job.get("note") or job.get("output"), 300)
    name, kind = "Error Gremlin", "gremlin"
    for pattern, n, k in MONSTERS:
        if re.search(pattern, error, re.I):
            name, kind = n, k
            break
    h = _hash(jid)
    level = max(1, player_level + (h % 3) - 1)
    ang = (h % 3600) / 3600.0 * math.tau
    radius = 0.62 + ((h >> 12) % 100) / 500.0          # 0.62 - 0.82 of the island's radius
    return {"id": jid, "job_id": jid, "name": name, "kind": kind, "level": level, "hp_max": 40 + level * 18,
            "dmg": [3 + level, 6 + int(level * 1.5)], "attack_every_s": 2.0, "aggro_radius": 4.5, "leash": 9.0,
            "speed": 2.2, "xp": 40 + 10 * level, "error": error, "title": _clean(job.get("title"), 120),
            "finished": float(job.get("finished") or 0),
            "spawn": {"zone": self_name, "u": round(math.cos(ang) * radius, 4), "v": round(math.sin(ang) * radius, 4)}}


def monsters(prof: dict, jobs: list, player_level: int, self_name: str, now: float) -> list:
    failed = [j for j in jobs if j.get("status") == "failed" and str(j.get("id")) not in prof["slain"]
              and now - float(j.get("finished") or now) <= MONSTER_DAYS * 86400]
    failed.sort(key=lambda j: float(j.get("finished") or 0), reverse=True)
    return [monster_for(j, player_level, self_name) for j in failed[:MONSTERS_MAX]]


def npcs(prof: dict, jobs: list, agents: list) -> list:
    """The /world agents with a class and a level: 100 XP per job their role ever finished."""
    counts: dict = {}
    for j in jobs:
        if j.get("status") == "done":
            prof["done_seen"].setdefault(str(j["id"]), role_of(j))
    for role in prof["done_seen"].values():
        counts[role] = counts.get(role, 0) + 1
    total = sum(counts.values())
    out = []
    for a in agents or []:
        role = "LOKI" if a.get("id") == "loki" else str(a.get("name") or "")
        done = total if a.get("id") == "loki" else counts.get(role, 0)
        lv = level_of(done * 100)
        state = str(a.get("state") or "")
        out.append({"id": a.get("id"), "name": a.get("name"), "role": a.get("role"), "class": npc_class(role if role != "LOKI" else "loki"),
                    "level": lv["level"], "jobs_done": done, "state": state, "station": a.get("station"), "task": a.get("task", ""),
                    "machine": a.get("machine", ""), "last_message": a.get("last_message", ""),
                    "quest_giver": a.get("id") == "loki",
                    # bars for nameplates: health = not failed; energy = how busy (both from the real state)
                    "hp": 0.15 if state == "failed" else 1.0,
                    "energy": {"working": 1.0, "waiting": 0.4, "blocked": 0.15, "done": 1.0}.get(state, 0.6)})
    return out


def loot(prof: dict, creations: list) -> dict:
    items = []
    for c in creations:
        path = str(c.get("path") or "")
        items.append({"id": path, "title": c.get("title", ""), "kind": c.get("kind", ""), "show": c.get("show", ""),
                      "rarity": RARITY.get(str(c.get("show") or ""), "common"), "url": "/creations/" + path, "t": c.get("t", 0),
                      "new": path not in prof["seen_creations"]})
    return {"items": items, "scrolls": prof["scrolls"][-40:]}


def build_state(prof: Profile, jobs: list, creations: list, agents: list, self_info: dict,
                machines: list | None = None, presence_part: dict | None = None, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    welcome = first_run(prof, jobs, creations)
    with prof.lock:
        d = prof.data
        seen_before = len(d["done_seen"])
        lv = level_of(d["xp"])
        cls = _player_class(d, str(self_info.get("os") or ""))
        power = CLASSES[cls]
        self_name = str(self_info.get("name") or "this computer")
        state = {
            "ok": True, "version": VERSION, "time": now,
            "profile": {"name": d["name"], "cls": cls, "color": CLASSES[cls]["color"], "xp": d["xp"], **lv,
                        "hp_max": int((90 + lv["level"] * 12) * power["hp"]), "en_max": 100, "power": power["power"],
                        "stats": dict(d["stats"]), "machine": self_name},
            "classes": CLASSES,
            "skills": SKILLS,
            "quests": quests(d, jobs),
            "monsters": monsters(d, jobs, lv["level"], self_name, now),
            "npcs": npcs(d, jobs, agents),
            "loot": loot(d, creations),
            "zones": {"self": self_info, "machines": [{"name": m.get("name"), "ok": bool(m.get("ok")), "os": m.get("os", "")}
                                                      for m in (machines or [])]},
            "presence": presence_part or {"players": [], "chat": [], "cursor": 0},
        }
        if len(d["done_seen"]) != seen_before:   # NPCs levelled: keep it even after the jobs list is cleared
            prof.save()
    if welcome:
        state["welcome"] = welcome
    return state


# ------------------------------------------------------------------ actions
def set_profile(prof: Profile, data: dict) -> dict:
    with prof.lock:
        if "name" in data:
            name = _clean(data.get("name"), 24)
            if not name:
                raise ValueError("a name cannot be empty")
            prof.data["name"] = name
        if "cls" in data:
            if data.get("cls") not in CLASSES:
                raise ValueError("class must be one of %s" % ", ".join(CLASSES))
            prof.data["cls"] = data["cls"]
        prof.save()
        return {"name": prof.data["name"], "cls": prof.data["cls"]}


def _grant(prof: Profile, xp: int) -> dict:
    before = level_of(prof.data["xp"])["level"]
    prof.data["xp"] += max(0, int(xp))
    after = level_of(prof.data["xp"])
    return {"xp": int(xp), "total_xp": prof.data["xp"], **after, "level_up": after["level"] > before}


def turn_in(prof: Profile, jobs: list, creations: list, job_id: str = "", every: bool = False) -> dict:
    """Turn in finished quests: XP, and the creations made while the job ran as loot."""
    done = [j for j in jobs if j.get("status") == "done" and str(j.get("id")) not in prof.data["turned_in"]
            and (every or str(j.get("id")) == job_id)]
    if not done:
        raise ValueError("no finished quest to turn in" if every else "that quest is not finished (or was turned in)")
    with prof.lock:
        xp, items, now = 0, [], time.time()
        for j in done:
            jid = str(j["id"])
            prof.data["turned_in"][jid] = now
            prof.data["stats"]["quests"] += 1
            xp += quest_xp(j)
            start, end = float(j.get("started") or j.get("created") or 0) - 5, float(j.get("finished") or now) + 120
            for c in creations:
                if start <= float(c.get("t") or 0) <= end:
                    path = str(c.get("path"))
                    items.append({"id": path, "title": c.get("title", ""), "show": c.get("show", ""),
                                  "rarity": RARITY.get(str(c.get("show") or ""), "common"), "url": "/creations/" + path})
                    prof.data["seen_creations"][path] = now
        prof.data["stats"]["loot"] += len(items)
        reward = _grant(prof, xp)
        prof.save()
    return {"turned_in": [str(j["id"]) for j in done], "loot": items, **reward}


def defeat(prof: Profile, jobs: list, job_id: str, retried: bool = False) -> dict:
    """A failure monster is beaten (once): XP and a lesson scroll with what went wrong."""
    job = next((j for j in jobs if str(j.get("id")) == job_id and j.get("status") == "failed"), None)
    if job is None:
        raise ValueError("no such monster (that job did not fail)")
    with prof.lock:
        if job_id in prof.data["slain"]:
            raise ValueError("that monster was already beaten")
        mon = monster_for(job, level_of(prof.data["xp"])["level"], "")
        prof.data["slain"][job_id] = time.time()
        prof.data["stats"]["kills"] += 1
        if retried:
            prof.data["stats"]["retries"] += 1
        scroll = {"id": "scroll:" + job_id, "title": "Lesson: " + (mon["title"] or "a failed job")[:60], "rarity": "uncommon",
                  "text": mon["error"] or "It failed without saying why.", "job_id": job_id}
        prof.data["scrolls"].append(scroll)
        del prof.data["scrolls"][:-200]
        reward = _grant(prof, mon["xp"])
        prof.save()
    return {"monster": mon["name"], "loot": [scroll], "retry": {"id": job_id, "path": "/mmo/monster/retry"}, **reward}


def note(prof: Profile, data: dict) -> dict:
    """Small facts the client reports: a death, loot looked at."""
    with prof.lock:
        if data.get("death"):
            prof.data["stats"]["deaths"] += 1
        seen = data.get("seen")
        if isinstance(seen, list):
            for path in seen[:500]:
                prof.data["seen_creations"][_clean(path, 300)] = time.time()
        prof.save()
        return {"stats": dict(prof.data["stats"])}


def cast_recorded(prof: Profile) -> None:
    with prof.lock:
        prof.data["stats"]["casts"] += 1
        prof.save()


# ------------------------------------------------------------------ the bridge's /mmo routes
def _context(state: Any) -> tuple:
    """(profile, raw jobs, creations, agents, self info, machines) from the running engine."""
    import platform  # pylint: disable=import-outside-toplevel
    agent = state.agent
    prof = profile_for(Path(getattr(agent, "DATA_DIR", "") or "."))
    jobs = [dict(j) for j in (state.jobs.store.all() if state.jobs is not None else [])]
    try:
        import creations  # pylint: disable=import-outside-toplevel
        made = creations.list_creations(Path(getattr(agent, "WORKSPACE", ".")), limit=400)
    except Exception:  # noqa: BLE001
        made = []
    try:
        import events  # pylint: disable=import-outside-toplevel
        runner = getattr(agent, "TEAMS", None)
        busy = bool(getattr(state, "chat_lock", None) is not None and state.chat_lock.locked())
        agents = events.world(jobs, runner.all() if runner else [], busy,
                              dict(getattr(agent, "LAST_TRIAGE", {}) or {})).get("agents", [])
    except Exception:  # noqa: BLE001
        agents = []
    try:
        import peers  # pylint: disable=import-outside-toplevel
        self_info = {"name": peers.my_name(), "os": platform.system()}
    except Exception:  # noqa: BLE001
        self_info = {"name": "this computer", "os": platform.system()}
    try:
        import peer_link  # pylint: disable=import-outside-toplevel
        machines = peer_link.world_machines()
    except Exception:  # noqa: BLE001
        machines = []
    return prof, jobs, made, agents, self_info, machines


def route(state: Any, method: str, path: str, data: dict, job_action: Any) -> tuple:
    """GET /mmo/state; POST /mmo/profile | /mmo/skill | /mmo/quest/accept | /mmo/quest/turnin |
    /mmo/monster/defeat | /mmo/monster/retry | /mmo/note. Returns (status, payload).
    job_action is the bridge's own POST /jobs (policy included), so nothing here starts work
    any other way than the app's Creations box does."""
    prof, jobs, made, agents, self_info, machines = _context(state)
    try:
        if method == "GET" and path == "/mmo/state":
            import presence  # pylint: disable=import-outside-toplevel
            return 200, build_state(prof, jobs, made, agents, self_info, machines, presence.world_part())
        if method != "POST":
            return 404, {"ok": False, "error": "Unknown endpoint."}
        if path == "/mmo/profile":
            return 200, {"ok": True, **set_profile(prof, data)}
        if path in ("/mmo/skill", "/mmo/quest/accept"):
            skill = str(data.get("skill") or data.get("kind") or "")
            if skill not in LOKI_ACTIONS:
                return 400, {"ok": False, "error": "%r is not a LOKI action (those are: %s); combat skills are played out by the client"
                             % (skill, ", ".join(sorted(LOKI_ACTIONS)))}
            status, out = job_action(state, "/jobs", job_spec(skill, str(data.get("text") or "")))
            if status == 200:
                cast_recorded(prof)
                out = {"ok": True, "quest": {"id": out.get("id"), "kind": skill, "status": "active"}}
            return status, out
        if path == "/mmo/quest/turnin":
            return 200, {"ok": True, **turn_in(prof, jobs, made, str(data.get("id") or ""), bool(data.get("all")))}
        if path == "/mmo/monster/defeat":
            return 200, {"ok": True, **defeat(prof, jobs, str(data.get("id") or ""))}
        if path == "/mmo/monster/retry":
            import presence  # pylint: disable=import-outside-toplevel
            job_id = str(data.get("id") or "")
            job = next((j for j in jobs if str(j.get("id")) == job_id), None)
            spec = presence.retry_spec(job, str(data.get("model") or ""))
            status, out = job_action(state, "/jobs", spec)
            if status != 200:
                return status, out
            reward = (defeat(prof, jobs, job_id, retried=True)   # the job already started: never fail after it
                      if job and job.get("status") == "failed" and job_id not in prof.data["slain"] else {})
            return 200, {"ok": True, "job": {"id": out.get("id")}, **reward}
        if path == "/mmo/note":
            return 200, {"ok": True, **note(prof, data)}
    except ValueError as exc:
        return 400, {"ok": False, "error": str(exc)}
    return 404, {"ok": False, "error": "Unknown endpoint."}
