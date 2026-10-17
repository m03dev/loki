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
STAT_KEYS = ("quests", "kills", "deaths", "casts", "loot", "retries", "dailies", "visits", "sold", "bought", "chats", "likes")

# ------------------------------------------------------------------ items and gear (session 28)
# Gear drops from beaten failure monsters (seeded by the job id, so the same job always drops the
# same thing), sometimes from turned-in quests, and is sold by the vendor. Paintings are LOKI's own
# pictures: their rarity is how much the owner liked them (Settings > Creations, 0-5 hearts).
GEAR_SLOTS = ("head", "chest", "weapon", "offhand", "trinket", "relic")
RARITIES = ("common", "uncommon", "rare", "epic", "legendary")
RARITY_COLORS = {"common": "#d9d9d9", "uncommon": "#59e566", "rare": "#4d99ff", "epic": "#bf66ff", "legendary": "#ff9926"}
RARITY_MULT = {"common": 1.0, "uncommon": 1.3, "rare": 1.7, "epic": 2.3, "legendary": 3.2}
SELL_BASE = {"common": 5, "uncommon": 12, "rare": 30, "epic": 75, "legendary": 200}
GEAR_BASES = {   # slot -> (name, look): `look` is the model piece a client draws
    "head": (("Hood", "hood"), ("Helm", "helm"), ("Wizard Hat", "wizard"), ("Circlet", "crown"), ("Feathered Cap", "feather")),
    "chest": (("Tunic", "tunic"), ("Robe", "robe"), ("Mail", "mail"), ("Vest", "vest")),
    "weapon": (("Sword", "sword"), ("Staff", "staff"), ("Bow", "bow"), ("Totem", "totem"), ("Hammer", "hammer")),
    "offhand": (("Tome", "book"), ("Buckler", "shield"), ("Lantern", "lantern")),
    "trinket": (("Charm", "charm"), ("Ring", "ring"), ("Amulet", "amulet")),
}
MONSTER_AFFIX = {"wraith": "Timeless", "slime": "Throttled", "golem": "Unparsed", "goblin": "Gatekept", "wisp": "Unreachable",
                 "mimic": "Mimic's", "beetle": "Squashed", "gremlin": "Gremlin's"}
PAINTING_RARITY = ("common", "uncommon", "rare", "epic", "epic", "legendary")   # by hearts 0-5
PAINTING_STATS = {"common": (1, 5), "uncommon": (2, 10), "rare": (3, 18), "epic": (5, 30), "legendary": (8, 50)}  # power %, hp
BAG_MAX = 60
TOMBSTONE_DAYS = 14
GUILD_DEFAULT = "House of LOKI"

# ------------------------------------------------------------------ achievements (Steam ids in game/loki-world/steam/)
# (id, title, what to do, Steam API name, the totals key, the amount)
ACHIEVEMENTS = (
    ("first_quest", "First Quest", "Turn in your first finished job at LOKI.", "ACH_FIRST_QUEST", "quests", 1),
    ("quests_10", "Busy Hands", "Turn in 10 quests.", "ACH_QUESTS_10", "quests", 10),
    ("quests_50", "LOKI's Right Hand", "Turn in 50 quests.", "ACH_QUESTS_50", "quests", 50),
    ("first_kill", "Bug Squasher", "Beat your first failure monster.", "ACH_FIRST_KILL", "kills", 1),
    ("kills_10", "Exterminator", "Beat 10 failure monsters.", "ACH_KILLS_10", "kills", 10),
    ("first_retry", "Second Wind", "Retry a failed job on a stronger model.", "ACH_FIRST_RETRY", "retries", 1),
    ("level_5", "Getting Started", "Reach level 5.", "ACH_LEVEL_5", "level", 5),
    ("level_10", "Seasoned", "Reach level 10.", "ACH_LEVEL_10", "level", 10),
    ("level_25", "Veteran of the Isles", "Reach level 25.", "ACH_LEVEL_25", "level", 25),
    ("first_picture", "First Light", "LOKI made a picture for you.", "ACH_FIRST_PICTURE", "pictures", 1),
    ("pictures_25", "Gallery Wall", "LOKI made 25 pictures for you.", "ACH_PICTURES_25", "pictures", 25),
    ("first_like", "Art Lover", "Like one of LOKI's creations.", "ACH_FIRST_LIKE", "likes", 1),
    ("masterpiece", "Masterpiece", "Love a creation so much it becomes a legendary painting.", "ACH_MASTERPIECE", "legendary", 1),
    ("full_set", "Dressed for It", "Wear something in every gear slot.", "ACH_FULL_SET", "slots", len(GEAR_SLOTS)),
    ("gold_100", "Pocket Money", "Earn 100 gold.", "ACH_GOLD_100", "gold_earned", 100),
    ("gold_1000", "Merchant Prince", "Earn 1000 gold.", "ACH_GOLD_1000", "gold_earned", 1000),
    ("first_sale", "Open for Business", "Sell something to the vendor.", "ACH_FIRST_SALE", "sold", 1),
    ("traveller", "Island Hopper", "Visit another machine's island.", "ACH_TRAVELLER", "visits", 1),
    ("guild_chat", "Hello, Me", "Talk to your other machine in guild chat.", "ACH_GUILD_CHAT", "chats", 1),
    ("daily_1", "Daily Routine", "Finish a daily quest.", "ACH_DAILY_1", "dailies", 1),
    ("daily_20", "Creature of Habit", "Finish 20 daily quests.", "ACH_DAILY_20", "dailies", 20),
)

# ------------------------------------------------------------------ daily quests, from real LOKI use
# (id, title, metric, the amounts it may ask for). Three a day, picked from the date, so every
# machine shows the same ones; progress adds up over the owner's machines.
DAILY_TEMPLATES = (
    ("pictures", "Make {n} pictures today", "pictures", (2, 3)),
    ("job", "Finish a background job", "jobs_done", (1,)),
    ("jobs", "Finish {n} background jobs", "jobs_done", (2, 3)),
    ("research", "Finish a research job", "research_done", (1,)),
    ("turnin", "Turn in {n} quests at LOKI", "turned_in", (1, 2)),
    ("monster", "Beat a failure monster", "kills", (1,)),
    ("visit", "Visit another machine's island", "visits", (1,)),
    ("like", "Like a creation (Settings > Creations)", "likes_given", (1,)),
    ("chat", "Say hello in guild chat (/g)", "guild_chat", (1,)),
)
DAILY_COUNT = 3
DAILY_GOLD = 20
DAILY_XP = 60
DAY_KEEP = 3
SYNC_VERSION = 1


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
        data["guild"] = _clean(data.get("guild"), 32) or GUILD_DEFAULT
        data["xp"] = int(data.get("xp") or 0)
        # turned_in/slain/seen: this machine's jobs and files. bags/equipped/achievements/claimed/
        # lww: the shared profile (synced). counters: the other machines' own counters as last heard.
        for key in ("turned_in", "slain", "seen_creations", "done_seen", "bags", "equipped", "achievements", "claimed",
                    "day_counts", "days", "counters", "lww", "gauges"):
            if not isinstance(data.get(key), dict):
                data[key] = {}
        if not isinstance(data.get("scrolls"), list):
            data["scrolls"] = []
        stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
        data["stats"] = {k: int(stats.get(k) or 0) for k in STAT_KEYS}
        gold = data.get("gold") if isinstance(data.get("gold"), dict) else {}
        data["gold"] = {"earned": int(gold.get("earned") or 0), "spent": int(gold.get("spent") or 0)}
        data["machine"] = _clean(data.get("machine"), 40)
        data["saved_t"] = float(data.get("saved_t") or 0)
        data.setdefault("init", False)
        data.setdefault("init_t", 0.0)
        return data

    def bind(self, machine: str) -> None:
        """This profile belongs to `machine` (peers.my_name()): its own counters go out under that name."""
        name = _clean(machine, 40)
        if name and name != self.data.get("machine"):
            with self.lock:
                self.data["machine"] = name
                self.data["counters"].pop(name, None)

    def save(self) -> None:
        with self.lock:
            self.rev += 1
            self.data["saved_t"] = round(time.time(), 3)
            # this machine's counters get a new time only when they really changed, so two
            # machines that merged each other settle on the same shared version
            own = json.dumps({k: v for k, v in _own_counters(self.data).items() if k != "t"}, sort_keys=True)
            if own != self.data.get("own_key"):
                self.data["own_key"] = own
                self.data["counters_t"] = self.data["saved_t"]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)

    rev = 0
    _v_cache: tuple = (-1, "")

    def sync_version(self) -> str:
        """A short hash of the shared part; cached until the next save (cheap to ask every tick)."""
        with self.lock:
            if self._v_cache[0] != self.rev:
                doc = export_doc(self)
                doc.pop("machine", None)   # who sends it is not part of what is shared
                self._v_cache = (self.rev, hashlib.sha1(json.dumps(doc, sort_keys=True).encode("utf-8")).hexdigest()[:16])
            return self._v_cache[1]


_PROFILES: dict = {}
_PROFILES_LOCK = threading.Lock()


_ACTIVE: dict = {"profile": None}


def profile_for(data_dir: Path) -> Profile:
    path = Path(data_dir) / "mmo" / "profile.json"
    with _PROFILES_LOCK:
        if str(path) not in _PROFILES:
            _PROFILES[str(path)] = Profile(path)
        return _PROFILES[str(path)]


def active_profile() -> Profile | None:
    """The running engine's profile (for the presence hub's sync): the one the last /mmo call
    used, or the engine's data folder when no client has asked yet."""
    if _ACTIVE["profile"] is not None:
        return _ACTIVE["profile"]
    import sys  # pylint: disable=import-outside-toplevel
    loki = sys.modules.get("loki")
    data_dir = getattr(loki, "DATA_DIR", None) if loki is not None else None
    if not data_dir:
        return None
    prof = profile_for(Path(data_dir))
    try:
        import peers  # pylint: disable=import-outside-toplevel
        prof.bind(peers.my_name())
    except Exception:  # noqa: BLE001
        pass
    _ACTIVE["profile"] = prof
    return prof


# ------------------------------------------------------------------ totals over the owner's machines
def _others(d: dict) -> dict:
    me = d.get("machine") or ""
    return {m: c for m, c in d["counters"].items() if m != me and isinstance(c, dict)}


def total_xp(d: dict) -> int:
    """XP is per machine (each machine counts only its own) and adds up: one character, every machine."""
    return int(d["xp"]) + sum(int(c.get("xp") or 0) for c in _others(d).values())


def total_stats(d: dict) -> dict:
    out = dict(d["stats"])
    for c in _others(d).values():
        for k, v in (c.get("stats") or {}).items():
            if k in out:
                out[k] += int(v or 0)
    return out


def gold_totals(d: dict) -> tuple:
    """(earned, spent) over every machine; the purse is earned - spent."""
    earned, spent = d["gold"]["earned"], d["gold"]["spent"]
    for c in _others(d).values():
        g = c.get("gold") or [0, 0]
        earned += int(g[0] or 0)
        spent += int(g[1] or 0)
    return earned, spent


def gold_of(d: dict) -> int:
    earned, spent = gold_totals(d)
    return max(0, earned - spent)


def _gold(prof: Profile, amount: int) -> int:
    prof.data["gold"]["earned"] += max(0, int(amount))
    return int(amount)


def _stat(prof: Profile, key: str, n: int = 1) -> None:
    prof.data["stats"][key] = int(prof.data["stats"].get(key, 0)) + n


# ------------------------------------------------------------------ items
def _num(value: Any, lo: float, hi: float, default: float = 0.0) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(x) or math.isinf(x):
        return default
    return max(lo, min(hi, x))


def roll_rarity(h: int) -> str:
    r = h % 1000
    return "legendary" if r < 15 else "epic" if r < 75 else "rare" if r < 250 else "uncommon" if r < 550 else "common"


def make_item(seed: str, level: int, source: str = "", affix: str = "", rarity: str = "", slot: str = "") -> dict:
    """A piece of gear, the same every time for the same seed (a job id, a vendor day)."""
    h = _hash("item:" + seed)
    slot = slot if slot in GEAR_BASES else tuple(GEAR_BASES)[h % len(GEAR_BASES)]
    bases = GEAR_BASES[slot]
    base, look = bases[(h >> 4) % len(bases)]
    rarity = rarity if rarity in RARITIES else roll_rarity(h >> 8)
    lv = int(_num(level, 1, 99, 1))
    m = RARITY_MULT[rarity]
    stats = {"weapon": {"power": round((2 + lv * 0.6) * m)}, "head": {"hp": round((6 + lv * 2.5) * m)},
             "chest": {"hp": round((10 + lv * 4) * m)}, "offhand": {"en": round((4 + lv) * m), "power": round((1 + lv * 0.3) * m)},
             "trinket": {"power": round((1 + lv * 0.3) * m), "hp": round((4 + lv * 1.5) * m)}}[slot]
    name = ("%s %s" % (affix, base)).strip()
    if rarity == "legendary":
        name += " of LOKI"
    return {"id": "g" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10], "kind": "gear", "name": name[:60], "slot": slot,
            "look": look, "rarity": rarity, "level": lv, "stats": stats, "value": int(SELL_BASE[rarity] * (1 + lv / 10.0)),
            "src": _clean(source, 80), "t": round(time.time(), 3), "ts": round(time.time(), 3)}


def painting_rarity(hearts: int) -> str:
    return PAINTING_RARITY[int(_num(hearts, 0, len(PAINTING_RARITY) - 1))]


def painting_item(creation: dict, hearts: int) -> dict:
    """One of LOKI's pictures as a painting you carry (the relic slot): rarer the more it is loved."""
    path = str(creation.get("path") or "")
    rarity = painting_rarity(hearts)
    power, hp = PAINTING_STATS[rarity]
    return {"id": "painting:" + path, "kind": "painting", "name": ("Painting: " + str(creation.get("title") or path))[:60],
            "slot": "relic", "look": "painting", "rarity": rarity, "level": 1, "stats": {"power": power, "hp": hp},
            "value": 0, "src": "LOKI made it", "hearts": int(_num(hearts, 0, 5)), "path": path,
            "url": "/creations/" + path, "t": float(creation.get("t") or 0), "ts": round(time.time(), 3)}


_ID_RE = re.compile(r"[A-Za-z0-9:_./ -]{1,200}")


def clean_item(raw: Any) -> dict | None:
    """An item as another machine sent it, made safe (types, lengths, ranges). None if it is not one."""
    if not isinstance(raw, dict):
        return None
    iid = str(raw.get("id") or "")
    if not _ID_RE.fullmatch(iid) or ".." in iid:
        return None
    kind = raw.get("kind") if raw.get("kind") in ("gear", "painting") else None
    slot = raw.get("slot") if raw.get("slot") in GEAR_SLOTS else None
    rarity = raw.get("rarity") if raw.get("rarity") in RARITIES else None
    if not kind or not slot or not rarity:
        return None
    stats = raw.get("stats") if isinstance(raw.get("stats"), dict) else {}
    out = {"id": iid, "kind": kind, "name": _clean(raw.get("name"), 60) or "Item", "slot": slot,
           "look": re.sub(r"[^a-z]", "", str(raw.get("look") or ""))[:16], "rarity": rarity,
           "level": int(_num(raw.get("level"), 1, 99, 1)),
           "stats": {k: int(_num(stats.get(k), 0, 2000)) for k in ("power", "hp", "en") if k in stats},
           "value": int(_num(raw.get("value"), 0, 1e6)), "src": _clean(raw.get("src"), 80),
           "t": _num(raw.get("t"), 0, 1e11), "ts": _num(raw.get("ts"), 0, 1e11)}
    if raw.get("gone"):
        out["gone"] = True
    if kind == "painting":
        out["hearts"] = int(_num(raw.get("hearts"), 0, 5))
        out["path"] = _clean(raw.get("path"), 200)
        out["url"] = "/creations/" + out["path"] if out["path"] else ""
    return out


def bag_items(d: dict) -> list:
    """The items you carry (not sold), newest first, each marked when you wear it."""
    worn = {str((e or {}).get("id") or "") for e in d["equipped"].values() if isinstance(e, dict)}
    out = [dict(it, equipped=it["id"] in worn) for it in d["bags"].values() if isinstance(it, dict) and not it.get("gone")]
    out.sort(key=lambda it: float(it.get("t") or 0), reverse=True)
    return out


def _prune_bags(d: dict, now: float) -> None:
    for iid in [k for k, it in d["bags"].items() if it.get("gone") and now - float(it.get("ts") or 0) > TOMBSTONE_DAYS * 86400]:
        del d["bags"][iid]


def add_to_bags(prof: Profile, item: dict) -> dict:
    """Put an item in the bags (once per id). Full bags: the vendor's runner sells it for you."""
    d = prof.data
    if item["id"] in d["bags"]:
        return {"item": d["bags"][item["id"]], "new": False}
    if len(bag_items(d)) >= BAG_MAX:
        _gold(prof, item.get("value", 0))
        _stat(prof, "sold")
        return {"item": item, "new": False, "auto_sold": item.get("value", 0)}
    d["bags"][item["id"]] = item
    return {"item": item, "new": True}


def worn_items(d: dict) -> dict:
    """slot -> the item worn there (a snapshot, so another machine can show it too)."""
    out = {}
    for slot in GEAR_SLOTS:
        e = d["equipped"].get(slot)
        if isinstance(e, dict) and isinstance(e.get("item"), dict):
            out[slot] = e["item"]
    return out


def gear_bonus(d: dict) -> dict:
    bonus = {"power": 0, "hp": 0, "en": 0}
    for it in worn_items(d).values():
        for k, v in (it.get("stats") or {}).items():
            if k in bonus:
                bonus[k] += int(v or 0)
    return bonus


def vendor_stock(day: str, level: int) -> list:
    """Today's stock (the same on every machine): four pieces near your level, priced at 4x their value."""
    out = []
    for k, rarity in enumerate(("common", "uncommon", "uncommon", "rare")):
        it = make_item("vendor:%s:%d" % (day, k), max(1, level - 1 + k % 2), "Bought from Trader Fenn", "Fenn's", rarity)
        it["price"] = it["value"] * 4
        out.append(it)
    return out


# ------------------------------------------------------------------ likes (Settings > Creations hearts)
def hearts_of(likes: dict, path: str) -> int:
    return int(_num((likes or {}).get(path), 0, 5))


# ------------------------------------------------------------------ the shared profile between machines
def _own_counters(d: dict) -> dict:
    days = {day: dict(v) for day, v in sorted(d["days"].items())[-DAY_KEEP:]}
    return {"xp": int(d["xp"]), "stats": dict(d["stats"]), "gold": [d["gold"]["earned"], d["gold"]["spent"]],
            "days": days, "gauges": dict(d["gauges"]), "t": d.get("counters_t", 0)}


def export_doc(prof: Profile) -> dict:
    """The part of the profile every machine shares: one character on all of them. Name, class and
    guild are last-writer-wins by time; XP, gold and stats are per-machine counters that add up;
    bags, worn gear, achievements and claimed dailies merge item by item."""
    d = prof.data
    with prof.lock:
        me = d.get("machine") or "this computer"
        lww = d["lww"]
        counters = {m: c for m, c in _others(d).items()}
        counters[me] = _own_counters(d)
        return {"v": SYNC_VERSION, "machine": me,
                "lww": {"name": [d["name"], lww.get("name", 0)], "cls": [d["cls"], lww.get("cls", 0)],
                        "guild": [d["guild"], lww.get("guild", 0)]},
                "counters": counters, "bags": dict(d["bags"]), "equipped": dict(d["equipped"]),
                "achievements": dict(d["achievements"]), "claimed": {k: dict(v) for k, v in d["claimed"].items()}}


def _clean_counters(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    stats = raw.get("stats") if isinstance(raw.get("stats"), dict) else {}
    gold = raw.get("gold") if isinstance(raw.get("gold"), list) and len(raw.get("gold")) == 2 else [0, 0]
    days = {}
    for day, metrics in list((raw.get("days") or {}).items())[-DAY_KEEP:] if isinstance(raw.get("days"), dict) else []:
        if re.fullmatch(r"\d{4}-\d\d-\d\d", str(day)) and isinstance(metrics, dict):
            days[str(day)] = {re.sub(r"[^a-z_]", "", str(k))[:20]: int(_num(v, 0, 1e6)) for k, v in list(metrics.items())[:20]}
    gauges = raw.get("gauges") if isinstance(raw.get("gauges"), dict) else {}
    return {"xp": int(_num(raw.get("xp"), 0, 1e12)), "stats": {k: int(_num(stats.get(k), 0, 1e9)) for k in STAT_KEYS},
            "gold": [int(_num(gold[0], 0, 1e12)), int(_num(gold[1], 0, 1e12))], "days": days,
            "gauges": {re.sub(r"[^a-z_]", "", str(k))[:20]: int(_num(v, 0, 1e9)) for k, v in list(gauges.items())[:10]},
            "t": _num(raw.get("t"), 0, 1e11)}


def merge_doc(prof: Profile, doc: Any) -> bool:
    """Take another machine's shared profile (sanitised). True when anything here changed."""
    if not isinstance(doc, dict) or doc.get("v") != SYNC_VERSION:
        return False
    d = prof.data
    changed = False
    with prof.lock:
        me = d.get("machine") or ""
        lww = doc.get("lww") if isinstance(doc.get("lww"), dict) else {}
        for field, limit in (("name", 24), ("cls", 12), ("guild", 32)):
            pair = lww.get(field)
            if not (isinstance(pair, list) and len(pair) == 2):
                continue
            value, ts = _clean(pair[0], limit), _num(pair[1], 0, 1e11)
            if ts <= float(d["lww"].get(field, 0)) or (field == "cls" and value not in CLASSES) or (field != "cls" and not value):
                continue
            d[field], d["lww"][field] = value, ts
            changed = True
        counters = doc.get("counters") if isinstance(doc.get("counters"), dict) else {}
        for machine, raw in list(counters.items())[:16]:
            machine = _clean(machine, 40)
            c = _clean_counters(raw)
            if not machine or c is None:
                continue
            if machine == me:
                # our own counters as the other machine last heard them: never less than that
                # (a reinstalled machine gets its progress back from its twin)
                if c["xp"] > d["xp"]:
                    d["xp"], changed = c["xp"], True
                for k in STAT_KEYS:
                    if c["stats"].get(k, 0) > d["stats"].get(k, 0):
                        d["stats"][k], changed = c["stats"][k], True
                for i, k in enumerate(("earned", "spent")):
                    if c["gold"][i] > d["gold"][k]:
                        d["gold"][k], changed = c["gold"][i], True
                continue
            if c["t"] > float((d["counters"].get(machine) or {}).get("t", -1)):
                d["counters"][machine] = c
                changed = True
        bags = doc.get("bags") if isinstance(doc.get("bags"), dict) else {}
        for raw in list(bags.values())[:400]:
            it = clean_item(raw)
            if it is None:
                continue
            here = d["bags"].get(it["id"])
            if here is None or it["ts"] > float(here.get("ts") or 0):
                d["bags"][it["id"]] = it
                changed = True
        equipped = doc.get("equipped") if isinstance(doc.get("equipped"), dict) else {}
        for slot in GEAR_SLOTS:
            e = equipped.get(slot)
            if not isinstance(e, dict):
                continue
            ts = _num(e.get("ts"), 0, 1e11)
            if ts <= float((d["equipped"].get(slot) or {}).get("ts", 0)):
                continue
            item = clean_item(e.get("item")) if e.get("item") is not None else None
            if e.get("item") is not None and (item is None or item["slot"] != slot):
                continue
            d["equipped"][slot] = {"id": item["id"] if item else "", "item": item, "ts": ts}
            changed = True
        ach = doc.get("achievements") if isinstance(doc.get("achievements"), dict) else {}
        known = {a[0] for a in ACHIEVEMENTS}
        for aid, t in ach.items():
            t = _num(t, 0, 1e11)
            if aid in known and t > 0 and (aid not in d["achievements"] or t < float(d["achievements"][aid])):
                d["achievements"][aid] = t
                changed = True
        claimed = doc.get("claimed") if isinstance(doc.get("claimed"), dict) else {}
        for day, ids in list(claimed.items())[-DAY_KEEP:]:
            if not (re.fullmatch(r"\d{4}-\d\d-\d\d", str(day)) and isinstance(ids, dict)):
                continue
            mine = d["claimed"].setdefault(str(day), {})
            for qid, t in list(ids.items())[:DAILY_COUNT * 2]:
                qid = _clean(qid, 40)
                if qid and qid not in mine:
                    mine[qid] = _num(t, 0, 1e11)
                    changed = True
        if changed:
            _prune_bags(d, time.time())
            for day in sorted(d["claimed"])[:-DAY_KEEP]:
                del d["claimed"][day]
            prof.save()
    return changed


class SyncAdapter:
    """What the presence hub calls to carry the shared profile over the peer link (presence.py)."""

    def __init__(self, prof_fn) -> None:
        self.prof_fn = prof_fn if callable(prof_fn) else (lambda: prof_fn)

    def version(self) -> str:
        prof = self.prof_fn()
        return prof.sync_version() if prof is not None else ""

    def export(self) -> dict | None:
        prof = self.prof_fn()
        return export_doc(prof) if prof is not None else None

    def merge(self, doc: Any) -> bool:
        prof = self.prof_fn()
        return merge_doc(prof, doc) if prof is not None else False


# ------------------------------------------------------------------ achievements and dailies
def day_key(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(now))


def day_start(now: float) -> float:
    lt = time.localtime(now)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def daily_quests(day: str, linked: bool) -> list:
    """Today's three daily quests (from the date only, so every machine has the same three)."""
    pool = [t for t in DAILY_TEMPLATES if linked or t[2] not in ("visits", "guild_chat")]
    h = _hash("daily:" + day)
    out, metrics = [], set()
    k = 0
    while len(out) < DAILY_COUNT and k < 40:
        tid, title, metric, amounts = pool[(h >> (k % 24)) % len(pool)] if k < 24 else pool[k % len(pool)]
        k += 1
        if metric in metrics:
            continue
        metrics.add(metric)
        n = amounts[(h >> (3 + k)) % len(amounts)]
        out.append({"id": "%s:%s" % (day, tid), "title": title.format(n=n), "metric": metric, "need": n,
                    "gold": DAILY_GOLD + 10 * (n - 1), "xp": DAILY_XP + 20 * (n - 1)})
    return out


def own_day_metrics(d: dict, jobs: list, made: list, now: float) -> dict:
    """What THIS machine did today, from its real jobs, creations and game log."""
    t0 = day_start(now)
    init_t = float(d.get("init_t") or 0) + 1

    def today(t: Any) -> bool:
        return float(t or 0) >= t0 and float(t or 0) > init_t

    done = [j for j in jobs if j.get("status") == "done" and float(j.get("finished") or 0) >= t0]
    counts = d["day_counts"].get(day_key(now), {})
    return {"pictures": sum(1 for c in made if c.get("show") == "image" and float(c.get("t") or 0) >= t0),
            "jobs_done": len(done), "research_done": sum(1 for j in done if quest_kind(j) == "research"),
            "turned_in": sum(1 for t in d["turned_in"].values() if today(t)),
            "kills": sum(1 for t in d["slain"].values() if today(t)),
            "visits": int(counts.get("visits", 0)), "likes_given": int(counts.get("likes_given", 0)),
            "guild_chat": int(counts.get("guild_chat", 0))}


def _count_today(prof: Profile, key: str, now: float) -> None:
    day = day_key(now)
    counts = prof.data["day_counts"].setdefault(day, {})
    counts[key] = int(counts.get(key, 0)) + 1
    for old in sorted(prof.data["day_counts"])[:-DAY_KEEP]:
        del prof.data["day_counts"][old]


def daily_state(d: dict, now: float, linked: bool) -> dict:
    day = day_key(now)
    progress: dict = dict(d["days"].get(day, {}))
    for c in _others(d).values():
        for k, v in ((c.get("days") or {}).get(day) or {}).items():
            progress[k] = progress.get(k, 0) + int(v or 0)
    claimed = d["claimed"].get(day, {})
    out = []
    for q in daily_quests(day, linked):
        have = int(progress.get(q["metric"], 0))
        out.append({**q, "progress": min(have, q["need"]), "done": have >= q["need"], "claimed": q["id"] in claimed})
    return {"date": day, "quests": out, "resets_in_s": int(day_start(now) + 86400 - now)}


def totals(d: dict) -> dict:
    """Everything achievements count, over all the owner's machines."""
    t = total_stats(d)
    t["level"] = level_of(total_xp(d))["level"]
    t["gold_earned"] = gold_totals(d)[0]
    for g in ("pictures", "legendary"):
        t[g] = int(d["gauges"].get(g, 0)) + sum(int((c.get("gauges") or {}).get(g, 0)) for c in _others(d).values())
    likes = int(d["gauges"].get("likes", 0)) + sum(int((c.get("gauges") or {}).get("likes", 0)) for c in _others(d).values())
    t["likes"] = max(int(t.get("likes", 0)), likes)
    t["slots"] = len(worn_items(d))
    return t


def check_achievements(prof: Profile, now: float | None = None) -> list:
    """Unlock what was earned (never locked again). Returns the newly unlocked ids."""
    now = time.time() if now is None else now
    d = prof.data
    t = totals(d)
    new = []
    for aid, _title, _about, _steam, key, need in ACHIEVEMENTS:
        if aid not in d["achievements"] and t.get(key, 0) >= need:
            d["achievements"][aid] = round(now, 3)
            new.append(aid)
    return new


def achievements_state(d: dict) -> list:
    t = totals(d)
    return [{"id": aid, "title": title, "about": about, "steam": steam, "unlocked": aid in d["achievements"],
             "t": float(d["achievements"].get(aid, 0)), "progress": min(int(t.get(key, 0)), need), "need": need}
            for aid, title, about, steam, key, need in ACHIEVEMENTS]


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
        d["init_t"] = now
        prof.save()
        return {"xp": grant, "quests": len(done), "creations": len(creations), **level_of(total_xp(d))}


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


def loot(prof: dict, creations: list, likes: dict | None = None) -> dict:
    items = []
    for c in creations:
        path = str(c.get("path") or "")
        show = str(c.get("show") or "")
        hearts = hearts_of(likes or {}, path)
        items.append({"id": path, "title": c.get("title", ""), "kind": c.get("kind", ""), "show": show,
                      # a picture is a painting: its rarity is how much the owner liked it
                      "rarity": painting_rarity(hearts) if show == "image" else RARITY.get(show, "common"),
                      "hearts": hearts, "painting": "painting:" + path if show == "image" else "",
                      "url": "/creations/" + path, "t": c.get("t", 0), "new": path not in prof["seen_creations"]})
    return {"items": items, "scrolls": prof["scrolls"][-40:]}


def _refresh_gauges(prof: Profile, jobs: list, creations: list, likes: dict, now: float) -> bool:
    """Keep this machine's numbers that come from LOKI itself (pictures, likes, today's work) and a
    painting you wear (its rarity follows its hearts) up to date. True when they changed."""
    d = prof.data
    gauges = {"pictures": sum(1 for c in creations if c.get("show") == "image"),
              "likes": sum(1 for v in (likes or {}).values() if int(v or 0) > 0),
              "legendary": sum(1 for v in (likes or {}).values() if painting_rarity(int(v or 0)) == "legendary")}
    day = day_key(now)
    metrics = own_day_metrics(d, jobs, creations, now)
    changed = gauges != d["gauges"] or metrics != d["days"].get(day)
    d["gauges"] = gauges
    d["days"][day] = metrics
    for old in sorted(d["days"])[:-DAY_KEEP]:
        del d["days"][old]
    relic = (d["equipped"].get("relic") or {}).get("item")
    if isinstance(relic, dict) and relic.get("kind") == "painting":
        c = next((c for c in creations if c.get("path") == relic.get("path")), None)
        if c is not None and hearts_of(likes, relic["path"]) != relic.get("hearts"):
            d["equipped"]["relic"] = {"id": relic["id"], "item": painting_item(c, hearts_of(likes, relic["path"])), "ts": round(now, 3)}
            changed = True
    return changed


def guild_state(d: dict, self_info: dict, machines: list, players: list) -> dict:
    """The owner's characters on his machines are one guild: this machine, every linked one, who is
    online (in LOKI World right now, from presence) and where."""
    me = str(self_info.get("name") or "this computer")
    lvl = level_of(total_xp(d))["level"]
    members = [{"machine": me, "name": d["name"], "cls": d["cls"] or "", "level": lvl, "online": True, "self": True,
                "zone": me, "linked": True}]
    seen = {me}
    by_machine = {str(p.get("machine")): p for p in players or []}
    for m in machines or []:
        name = str(m.get("name") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        p = by_machine.get(name) or {}
        members.append({"machine": name, "name": p.get("name") or d["name"], "cls": p.get("cls") or "",
                        "level": int(p.get("lvl") or lvl), "online": bool(p), "self": False, "zone": p.get("zone", ""),
                        "linked": bool(m.get("ok"))})
    for name, p in by_machine.items():
        if name not in seen:
            members.append({"machine": name, "name": p.get("name") or "", "cls": p.get("cls") or "", "level": int(p.get("lvl") or 1),
                            "online": True, "self": False, "zone": p.get("zone", ""), "linked": True})
    return {"name": d["guild"], "members": members, "online": sum(1 for x in members if x["online"])}


def build_state(prof: Profile, jobs: list, creations: list, agents: list, self_info: dict,
                machines: list | None = None, presence_part: dict | None = None, now: float | None = None,
                likes: dict | None = None) -> dict:
    now = time.time() if now is None else now
    likes = likes or {}
    welcome = first_run(prof, jobs, creations)
    with prof.lock:
        d = prof.data
        if not d.get("machine"):
            prof.bind(str(self_info.get("name") or "this computer"))
        seen_before = len(d["done_seen"])
        dirty = _refresh_gauges(prof, jobs, creations, likes, now)
        new_ach = check_achievements(prof, now)
        lv = level_of(total_xp(d))
        cls = _player_class(d, str(self_info.get("os") or ""))
        base = CLASSES[cls]
        bonus = gear_bonus(d)
        self_name = str(self_info.get("name") or "this computer")
        machines = machines or []
        part = presence_part or {"players": [], "chat": [], "cursor": 0}
        state = {
            "ok": True, "version": VERSION, "time": now,
            "profile": {"name": d["name"], "cls": cls, "color": CLASSES[cls]["color"], "xp": total_xp(d), **lv,
                        "hp_max": int((90 + lv["level"] * 12) * base["hp"]) + bonus["hp"], "en_max": 100 + bonus["en"],
                        "power": round(base["power"] * (1 + bonus["power"] / 100.0), 3), "gear": bonus,
                        "gold": gold_of(d), "stats": total_stats(d), "machine": self_name, "guild": d["guild"]},
            "classes": CLASSES,
            "skills": SKILLS,
            "quests": quests(d, jobs),
            "monsters": monsters(d, jobs, lv["level"], self_name, now),
            "npcs": npcs(d, jobs, agents),
            "loot": loot(d, creations, likes),
            "gear": {"slots": list(GEAR_SLOTS), "equipped": worn_items(d), "bags": bag_items(d), "bag_max": BAG_MAX,
                     "rarities": RARITY_COLORS},
            "vendor": {"name": "Trader Fenn", "stock": vendor_stock(day_key(now), lv["level"])},
            "achievements": achievements_state(d),
            "daily": daily_state(d, now, bool(machines)),
            "guild": guild_state(d, self_info, machines, part.get("players") or []),
            "zones": {"self": self_info, "machines": [{"name": m.get("name"), "ok": bool(m.get("ok")), "os": m.get("os", "")}
                                                      for m in machines]},
            "presence": part,
            "sync": {"machine": d.get("machine", ""), "version": "", "machines": sorted(_others(d)),
                     "heard": {m: c.get("t", 0) for m, c in _others(d).items()}},
        }
        if new_ach:
            state["new_achievements"] = new_ach
        if dirty or new_ach or len(d["done_seen"]) != seen_before:   # NPCs levelled, gauges, unlocks: keep them
            prof.save()
        state["sync"]["version"] = prof.sync_version()
    if welcome:
        state["welcome"] = welcome
    return state


# ------------------------------------------------------------------ actions
def set_profile(prof: Profile, data: dict) -> dict:
    with prof.lock:
        now = round(time.time(), 3)
        if "name" in data:
            name = _clean(data.get("name"), 24)
            if not name:
                raise ValueError("a name cannot be empty")
            prof.data["name"] = name
            prof.data["lww"]["name"] = now
        if "cls" in data:
            if data.get("cls") not in CLASSES:
                raise ValueError("class must be one of %s" % ", ".join(CLASSES))
            prof.data["cls"] = data["cls"]
            prof.data["lww"]["cls"] = now
        if "guild" in data:
            guild = _clean(data.get("guild"), 32)
            if not guild:
                raise ValueError("a guild needs a name")
            prof.data["guild"] = guild
            prof.data["lww"]["guild"] = now
        prof.save()
        return {"name": prof.data["name"], "cls": prof.data["cls"], "guild": prof.data["guild"]}


def _grant(prof: Profile, xp: int) -> dict:
    before = level_of(total_xp(prof.data))["level"]
    prof.data["xp"] += max(0, int(xp))
    after = level_of(total_xp(prof.data))
    return {"xp": int(xp), "total_xp": total_xp(prof.data), **after, "level_up": after["level"] > before}


def _reward(prof: Profile, extra: dict) -> dict:
    """XP/level/gold/unlocks in one answer (the client shows them at once)."""
    out = dict(extra)
    out["gold"] = gold_of(prof.data)
    new = check_achievements(prof)
    if new:
        out["new_achievements"] = new
    return out


def turn_in(prof: Profile, jobs: list, creations: list, job_id: str = "", every: bool = False) -> dict:
    """Turn in finished quests: XP, gold, the creations made while the job ran as loot, and now and
    then a piece of gear (seeded by the job, so it is always the same piece)."""
    done = [j for j in jobs if j.get("status") == "done" and str(j.get("id")) not in prof.data["turned_in"]
            and (every or str(j.get("id")) == job_id)]
    if not done:
        raise ValueError("no finished quest to turn in" if every else "that quest is not finished (or was turned in)")
    with prof.lock:
        xp, gold, items, gear, now = 0, 0, [], [], time.time()
        level = level_of(total_xp(prof.data))["level"]
        for j in done:
            jid = str(j["id"])
            prof.data["turned_in"][jid] = now
            _stat(prof, "quests")
            xp += quest_xp(j)
            gold += 5 + min(25, (quest_xp(j) - 100) // 10)
            if _hash("drop:" + jid) % 4 == 0:
                got = add_to_bags(prof, make_item("quest:" + jid, level, "Reward: " + _clean(j.get("title"), 60), "LOKI's"))
                gear.append(dict(got["item"], auto_sold=got.get("auto_sold", 0)))
            start, end = float(j.get("started") or j.get("created") or 0) - 5, float(j.get("finished") or now) + 120
            for c in creations:
                if start <= float(c.get("t") or 0) <= end:
                    path = str(c.get("path"))
                    items.append({"id": path, "title": c.get("title", ""), "show": c.get("show", ""),
                                  "rarity": RARITY.get(str(c.get("show") or ""), "common"), "url": "/creations/" + path})
                    prof.data["seen_creations"][path] = now
        _stat(prof, "loot", len(items) + len(gear))
        _gold(prof, gold)
        reward = _grant(prof, xp)
        out = _reward(prof, {"turned_in": [str(j["id"]) for j in done], "loot": items + gear, "gold_got": gold, **reward})
        prof.save()
    return out


def defeat(prof: Profile, jobs: list, job_id: str, retried: bool = False) -> dict:
    """A failure monster is beaten (once): XP, gold, a lesson scroll with what went wrong and the
    gear it dropped (seeded by the job id)."""
    job = next((j for j in jobs if str(j.get("id")) == job_id and j.get("status") == "failed"), None)
    if job is None:
        raise ValueError("no such monster (that job did not fail)")
    with prof.lock:
        if job_id in prof.data["slain"]:
            raise ValueError("that monster was already beaten")
        mon = monster_for(job, level_of(total_xp(prof.data))["level"], "")
        prof.data["slain"][job_id] = time.time()
        _stat(prof, "kills")
        if retried:
            _stat(prof, "retries")
        scroll = {"id": "scroll:" + job_id, "title": "Lesson: " + (mon["title"] or "a failed job")[:60], "rarity": "uncommon",
                  "text": mon["error"] or "It failed without saying why.", "job_id": job_id}
        prof.data["scrolls"].append(scroll)
        del prof.data["scrolls"][:-200]
        got = add_to_bags(prof, make_item("drop:" + job_id, mon["level"], "Dropped by a " + mon["name"],
                                          MONSTER_AFFIX.get(mon["kind"], "")))
        gold = 3 + mon["level"]
        _gold(prof, gold)
        _stat(prof, "loot")
        reward = _grant(prof, mon["xp"])
        out = _reward(prof, {"monster": mon["name"], "loot": [scroll, dict(got["item"], auto_sold=got.get("auto_sold", 0))],
                             "gold_got": gold, "retry": {"id": job_id, "path": "/mmo/monster/retry"}, **reward})
        prof.save()
    return out


def note(prof: Profile, data: dict, self_name: str = "") -> dict:
    """Small facts the client reports: a death, loot looked at, a visit to another machine's
    island, a line said in guild chat."""
    with prof.lock:
        now = time.time()
        if data.get("death"):
            _stat(prof, "deaths")
        seen = data.get("seen")
        if isinstance(seen, list):
            for path in seen[:500]:
                prof.data["seen_creations"][_clean(path, 300)] = now
        zone = _clean(data.get("visit"), 40)
        if zone and zone != (self_name or prof.data.get("machine")):
            _stat(prof, "visits")
            _count_today(prof, "visits", now)
        if data.get("chat") == "guild":
            _stat(prof, "chats")
            _count_today(prof, "guild_chat", now)
        out = _reward(prof, {"stats": total_stats(prof.data)})
        prof.save()
        return out


def cast_recorded(prof: Profile) -> None:
    with prof.lock:
        _stat(prof, "casts")
        prof.save()


def equip(prof: Profile, item_id: str, slot: str = "", creations: list | None = None, likes: dict | None = None) -> dict:
    """Wear an item from the bags (or one of LOKI's pictures as a painting); an empty id takes the
    slot off."""
    with prof.lock:
        d = prof.data
        now = round(time.time(), 3)
        if not item_id:
            if slot not in GEAR_SLOTS:
                raise ValueError("say which slot to take off (%s)" % ", ".join(GEAR_SLOTS))
            d["equipped"][slot] = {"id": "", "item": None, "ts": now}
        elif item_id.startswith("painting:"):
            path = item_id[len("painting:"):]
            c = next((c for c in creations or [] if c.get("path") == path and c.get("show") == "image"), None)
            if c is None:
                raise ValueError("no such picture on this machine")
            item = painting_item(c, hearts_of(likes or {}, path))
            slot = "relic"
            d["equipped"][slot] = {"id": item["id"], "item": item, "ts": now}
        else:
            item = d["bags"].get(item_id)
            if not isinstance(item, dict) or item.get("gone"):
                raise ValueError("that item is not in your bags")
            slot = item["slot"]
            d["equipped"][slot] = {"id": item_id, "item": dict(item), "ts": now}
        out = _reward(prof, {"slot": slot, "equipped": worn_items(d), "gear": gear_bonus(d)})
        prof.save()
        return out


def sell(prof: Profile, item_id: str) -> dict:
    """Sell an item to the vendor for its value in gold (not while you wear it; paintings are not for sale)."""
    with prof.lock:
        d = prof.data
        item = d["bags"].get(item_id)
        if not isinstance(item, dict) or item.get("gone"):
            raise ValueError("that item is not in your bags")
        if any((e or {}).get("id") == item_id for e in d["equipped"].values() if isinstance(e, dict)):
            raise ValueError("take it off before you sell it")
        item["gone"] = True
        item["ts"] = round(time.time(), 3)
        _gold(prof, item.get("value", 0))
        _stat(prof, "sold")
        out = _reward(prof, {"sold": item_id, "gold_got": int(item.get("value", 0))})
        prof.save()
        return out


def buy(prof: Profile, stock_id: str, now: float | None = None) -> dict:
    """Buy one of today's vendor pieces (each once)."""
    now = time.time() if now is None else now
    with prof.lock:
        d = prof.data
        stock = vendor_stock(day_key(now), level_of(total_xp(d))["level"])
        item = next((it for it in stock if it["id"] == stock_id), None)
        if item is None:
            raise ValueError("Trader Fenn does not sell that today")
        if stock_id in d["bags"]:
            raise ValueError("you bought that one already")
        price = int(item.pop("price"))
        if gold_of(d) < price:
            raise ValueError("not enough gold (%d, it costs %d)" % (gold_of(d), price))
        if len(bag_items(d)) >= BAG_MAX:
            raise ValueError("your bags are full - sell something first")
        d["gold"]["spent"] += price
        d["bags"][item["id"]] = item
        _stat(prof, "bought")
        out = _reward(prof, {"bought": item, "price": price})
        prof.save()
        return out


def claim_daily(prof: Profile, quest_id: str, linked: bool, now: float | None = None) -> dict:
    """Claim a finished daily quest (once, on whichever machine): gold and XP."""
    now = time.time() if now is None else now
    with prof.lock:
        d = prof.data
        daily = daily_state(d, now, linked)
        q = next((q for q in daily["quests"] if q["id"] == quest_id), None)
        if q is None:
            raise ValueError("that is not one of today's daily quests")
        if q["claimed"]:
            raise ValueError("already claimed")
        if not q["done"]:
            raise ValueError("not done yet: %d of %d" % (q["progress"], q["need"]))
        d["claimed"].setdefault(daily["date"], {})[quest_id] = round(now, 3)
        _stat(prof, "dailies")
        _gold(prof, q["gold"])
        reward = _grant(prof, q["xp"])
        out = _reward(prof, {"daily": quest_id, "gold_got": q["gold"], **reward})
        prof.save()
        return out


def like(prof: Profile, data_dir: Path, path: str, hearts: int, creations: list) -> dict:
    """Settings > Creations: 0-5 hearts on a creation. A picture's hearts are its painting's rarity."""
    import creations as creations_mod  # pylint: disable=import-outside-toplevel
    if not any(c.get("path") == path for c in creations):
        raise ValueError("no such creation")
    before = creations_mod.set_likes(Path(data_dir), path, hearts)
    after = creations_mod.get_likes(Path(data_dir)).get(path, 0)
    with prof.lock:
        if after > before:
            _stat(prof, "likes")
            _count_today(prof, "likes_given", time.time())
        prof.save()
    return {"path": path, "hearts": after, "rarity": painting_rarity(after)}


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
    prof.bind(self_info["name"])
    _ACTIVE["profile"] = prof
    return prof, jobs, made, agents, self_info, machines


def _likes(state: Any) -> dict:
    try:
        import creations  # pylint: disable=import-outside-toplevel
        return creations.get_likes(Path(getattr(state.agent, "DATA_DIR", "") or "."))
    except Exception:  # noqa: BLE001
        return {}


def _start_sync() -> None:
    """The shared profile rides on the presence exchange between machines (presence.py): make
    sure its pusher runs whenever a client plays, even before the world posts presence."""
    try:
        import peers  # pylint: disable=import-outside-toplevel
        import presence  # pylint: disable=import-outside-toplevel
        if peers.peers():
            presence.HUB.ensure_pusher(peers.peers, peers.call)
    except Exception:  # noqa: BLE001
        pass


def route(state: Any, method: str, path: str, data: dict, job_action: Any) -> tuple:
    """GET /mmo/state | /mmo/likes; POST /mmo/profile | /mmo/skill | /mmo/quest/accept |
    /mmo/quest/turnin | /mmo/monster/defeat | /mmo/monster/retry | /mmo/note | /mmo/equip |
    /mmo/vendor/sell | /mmo/vendor/buy | /mmo/daily/claim | /mmo/like | /mmo/guild.
    Returns (status, payload). job_action is the bridge's own POST /jobs (policy included), so
    nothing here starts work any other way than the app's Creations box does."""
    prof, jobs, made, agents, self_info, machines = _context(state)
    _start_sync()
    try:
        if method == "GET" and path == "/mmo/state":
            import presence  # pylint: disable=import-outside-toplevel
            return 200, build_state(prof, jobs, made, agents, self_info, machines, presence.world_part(), likes=_likes(state))
        if method == "GET" and path == "/mmo/likes":
            return 200, {"ok": True, "likes": _likes(state), "max": 5}
        if method != "POST":
            return 404, {"ok": False, "error": "Unknown endpoint."}
        if path == "/mmo/profile":
            return 200, {"ok": True, **set_profile(prof, {k: data[k] for k in ("name", "cls") if k in data})}
        if path == "/mmo/guild":
            return 200, {"ok": True, **set_profile(prof, {"guild": data.get("name")})}
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
            return 200, {"ok": True, **note(prof, data, self_info["name"])}
        if path == "/mmo/equip":
            return 200, {"ok": True, **equip(prof, _clean(data.get("id"), 220), str(data.get("slot") or ""), made, _likes(state))}
        if path == "/mmo/vendor/sell":
            return 200, {"ok": True, **sell(prof, _clean(data.get("id"), 220))}
        if path == "/mmo/vendor/buy":
            return 200, {"ok": True, **buy(prof, _clean(data.get("id"), 220))}
        if path == "/mmo/daily/claim":
            return 200, {"ok": True, **claim_daily(prof, _clean(data.get("id"), 60), bool(machines))}
        if path == "/mmo/like":
            return 200, {"ok": True, **like(prof, Path(getattr(state.agent, "DATA_DIR", "") or "."), _clean(data.get("path"), 300),
                                            int(_num(data.get("hearts"), 0, 5)), made)}
    except ValueError as exc:
        return 400, {"ok": False, "error": str(exc)}
    return 404, {"ok": False, "error": "Unknown endpoint."}
