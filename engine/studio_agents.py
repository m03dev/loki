"""Studio > Agents: every agent at work on every machine, what each one makes, and the controls.

Owner 2026-10-25 11:20: "the studio should be a place i can see my agents working as well and other machines. why do
i only see one machine? and i should be able to have some sort of control over what im doing ... i want them to make
real things like art 3d models or paintings comic books novels real websites".

  view(state)                       GET  /studio/agents   this machine + every linked machine (and farm workers): who
                                                          is working on what, the stage, the last thing said, and
                                                          what to do when only one machine is there
  stop(state, machine, job)         POST /studio/agents/stop   a job here, or on a linked machine (its /peer/jobs/<id>/cancel)
  again(state, machine, job)        POST /studio/agents/again  the same brief once more (a fresh job)
  make(state, kind, brief, ...)     POST /studio/make     a REAL piece of work as a background job: the brief below,
                                                          its own folder in ~/LOKI Projects/<Kind>/<name>, the files it
                                                          made listed when it is done. machine= sends it to a linked
                                                          machine (the PC's GPU for pictures and 3D)

The agent is OpenCode (engine/opencode_engine.py) with LOKI's makers (engine/make_mcp.py: make_image, make_3d,
make_video) - it writes text and code itself and draws / models through those.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

# kind -> (folder, label, how long it may run, the brief the agent gets around the owner's words)
KINDS: dict = {
    "art": ("Art", "Art", 3 * 3600,
            "Make finished artwork: {brief}\n"
            "1. Decide the look (medium, style, palette, light, composition) and write it in ART_NOTES.md.\n"
            "2. Draw it with the make_image tool (count 4 for variations) - describe each picture fully.\n"
            "3. Look at what came out (read the files), pick the best, make 2-3 more rounds that improve it.\n"
            "4. Keep the best in final/ and write a short caption for each in README.md."),
    "painting": ("Paintings", "Painting", 3 * 3600,
                 "Paint this (as a painter would - a real painting, not a photo): {brief}\n"
                 "Choose the medium (oil, acrylic, watercolour, gouache, ink) and the painter's approach, write it in "
                 "NOTES.md, then make_image with prompts that name the medium, brushwork, canvas texture, palette and "
                 "light. Make a few versions, keep the best in final/, describe each in README.md."),
    "3d": ("3D Models", "3D model", 3 * 3600,
           "Make a 3D model: {brief}\n"
           "1. Draw clean reference pictures first with make_image (front view, plain background, the whole object).\n"
           "2. Turn the best one into a model with make_3d (image= that picture), or make_3d prompt= for a quick one.\n"
           "3. If the result looks wrong, improve the reference and make it again (up to 3 tries).\n"
           "4. Write README.md: what it is, the files (.glb/.obj), and 'open it in Forge to sculpt and export'."),
    "comic": ("Comics", "Comic book", 6 * 3600,
              "Make a comic book: {brief}\n"
              "1. Write SCRIPT.md: title, characters (with a fixed visual description each), and the pages - every "
              "panel with what we see, the dialogue and captions.\n"
              "2. Draw every panel with make_image, repeating each character's exact description so they stay the "
              "same; one style for the whole book (say it in every prompt). Save as pages/page01/panel1.png ...\n"
              "3. Put each page together as an HTML page (pages/page01.html: the panels in a grid, speech bubbles "
              "and captions as text over them) and make index.html - the cover and the pages in order.\n"
              "4. Open index.html in the browser tool (or check every image path exists) before you say it is done."),
    "novel": ("Novels", "Novel", 6 * 3600,
              "Write a novel: {brief}\n"
              "1. OUTLINE.md: the premise, the characters (wants, flaws, arcs), the world, and a chapter-by-chapter "
              "plan with the turning points.\n"
              "2. Write the chapters in chapters/01.md, 02.md ... - real prose, scenes and dialogue, each chapter "
              "1,500-3,000 words, the voice kept the same throughout. Re-read the outline before each chapter.\n"
              "3. Make a cover with make_image (cover.png) and put the whole book together as book.md with a title "
              "page and contents.\n"
              "4. At the end, report how many chapters and words there are (count them with the shell)."),
    "website": ("Websites", "Website", 3 * 3600,
                "Build a real website: {brief}\n"
                "1. PLAN.md: who it is for, the pages, the sections, the look (colours, type).\n"
                "2. Build it as a static site (index.html + the other pages, styles.css, script.js if needed) - real "
                "copy, not lorem ipsum; pictures with make_image saved in images/.\n"
                "3. Check it: open every page (the browser tool, or a quick local server with the shell) and fix what "
                "is broken - links, images, the layout on a narrow phone width.\n"
                "4. README.md: what it is and how to open or publish it."),
    "game": ("Games", "Game", 6 * 3600,
             "Make a small playable game: {brief}\n"
             "Plan it in GAME_PLAN.md, build it (a Godot project, or HTML5 canvas if simpler), make the art with "
             "make_image, then run it and fix what breaks. README.md says how to play and how it was checked."),
}


def slug(text: str, n: int = 40) -> str:
    s = re.sub(r"[^\w\s-]", "", str(text or "")).strip().lower()
    s = re.sub(r"[\s_-]+", "-", s)[:n].strip("-")
    return s or time.strftime("work-%Y%m%d-%H%M")


def folder_for(kind: str, name: str, projects: Path) -> Path:
    base = projects / KINDS[kind][0]
    target = base / slug(name)
    k = 2
    while target.exists():
        target = base / ("%s-%d" % (slug(name), k))
        k += 1
    return target


def brief_for(kind: str, brief: str, folder: Path) -> str:
    return (KINDS[kind][3].format(brief=brief.strip()) + "\n\n"
            "Work in this folder: %s - every file goes here. This is real work for the owner, not a test: make the "
            "whole thing, check it, and at the end list every file you made. If something cannot be done (no image "
            "model, no network), say exactly that - never say it is done when it is not." % folder)


# ------------------------------------------------------------------ the view
def _local_agents(state: Any) -> tuple[list, dict]:
    import events  # pylint: disable=import-outside-toplevel
    runner = getattr(state.agent, "TEAMS", None)
    jobs = state.jobs.store.all() if getattr(state, "jobs", None) is not None else []
    busy = bool(getattr(state, "chat_lock", None) is not None and state.chat_lock.locked())
    w = events.world(jobs, runner.all() if runner else [], busy, dict(getattr(state.agent, "LAST_TRIAGE", {}) or {}))
    by_id = {str(j.get("id")): j for j in jobs}
    out = []
    for a in w["agents"]:
        if a["id"] == "loki" and a["state"] == "idle":
            continue                       # the conductor shows when it is answering, not as an idle card
        job = by_id.get(a["id"][4:]) if a["id"].startswith("job-") else None
        out.append({**a, "job": job.get("id") if job else "", "status": job.get("status", a["state"]) if job else a["state"],
                    "workspace": (job or {}).get("workspace", ""), "kind": (job or {}).get("make_kind", ""),
                    "note": str((job or {}).get("note") or "")[:200], "error": str((job or {}).get("error") or "")[:200],
                    "screenshot": bool((job or {}).get("screenshot")), "can_stop": bool(job) and job.get("status") in (
                        "queued", "starting", "working", "blocked")})
    return out, w.get("stats", {})


def view(state: Any) -> dict:
    import peer_link  # pylint: disable=import-outside-toplevel
    import peers  # pylint: disable=import-outside-toplevel
    import platform  # pylint: disable=import-outside-toplevel
    agents, stats = _local_agents(state)
    me = peers.my_name()
    for a in agents:
        a["machine"] = me
    machines = [{"name": me, "self": True, "ok": True, "os": platform.system(), "working": stats.get("working", 0),
                 "queued": stats.get("waiting", 0), "blocked": stats.get("blocked", 0)}]
    for m in peer_link.machines_live():
        machines.append({**{k: m.get(k) for k in ("name", "ok", "ms", "relay", "error", "os", "version", "working",
                                                   "queued", "blocked", "models")}, "self": False})
        for a in m.get("agents") or []:
            agents.append({**a, "machine": m["name"], "remote": True})
    try:   # the render farm's GPU workers count as machines too (engine/render_farm.py)
        import render_farm  # pylint: disable=import-outside-toplevel
        known = {x["name"] for x in machines}
        for wk in render_farm.farm(state).workers():
            name, url = str(wk.get("name") or wk.get("url") or ""), str(wk.get("url") or "")
            local = name.lower() in ("this computer", "local", me.lower()) or "127.0.0.1" in url or "localhost" in url
            if name and name not in known and not local:   # this computer's own worker is this machine
                machines.append({"name": name, "ok": bool(wk.get("online")), "self": False, "farm": True,
                                 "working": 1 if wk.get("busy") else 0, "gpu": str(wk.get("gpu") or "")})
    except Exception:  # noqa: BLE001 - the view never fails over the farm
        pass
    linked = len([m for m in machines if not m.get("self")])
    hint = "" if linked else ("Only this computer is linked. To see the other one: on it, open Settings > Machines and "
                              "turn on 'Let my other machines link' - it shows a link code - then paste that code in "
                              "Studio > Agents > Link a machine (or Settings > Machines) here.")
    return {"ok": True, "machine": me, "machines": machines, "agents": agents, "stats": stats, "hint": hint,
            "kinds": [{"id": k, "label": v[1], "folder": v[0]} for k, v in KINDS.items()], "time": time.time()}


# ------------------------------------------------------------------ the controls
def _peer(name: str):
    import peers  # pylint: disable=import-outside-toplevel
    p = peers.find(name)
    if p is None:
        raise ValueError("no linked machine called %s" % name)
    return p


def stop(state: Any, machine: str, job_id: str) -> dict:
    import peers  # pylint: disable=import-outside-toplevel
    job_id = "".join(ch for ch in str(job_id) if ch.isalnum())[:16]
    if not job_id:
        raise ValueError("which job?")
    if not machine or machine == peers.my_name():
        if getattr(state, "jobs", None) is None:
            raise ValueError("background jobs are not running here")
        job = state.jobs.cancel(job_id)
        if job is None:
            raise ValueError("no such job here")
        return {"ok": True, "job": {"id": job["id"], "status": job["status"]}, "machine": peers.my_name()}
    got = peers.call(_peer(machine), "POST", "/peer/jobs/%s/cancel" % job_id, {})
    return {"ok": bool(got.get("ok")), "job": got.get("job"), "machine": machine}


def again(state: Any, machine: str, job_id: str) -> dict:
    import peers  # pylint: disable=import-outside-toplevel
    if machine and machine != peers.my_name():
        got = peers.call(_peer(machine), "GET", "/peer/jobs/%s" % job_id)
        old = got.get("job") or {}
        prompt = str(old.get("prompt") or "")
        if not prompt:
            raise ValueError("that machine did not say what the job was")
        got = peers.call(_peer(machine), "POST", "/peer/jobs", {"prompt": prompt, "title": old.get("title", "")})
        return {"ok": bool(got.get("ok")), "job": got.get("job"), "machine": machine}
    old = state.jobs.store.get(job_id) if getattr(state, "jobs", None) is not None else None
    if not old:
        raise ValueError("no such job here")
    spec = {k: old.get(k) for k in ("prompt", "title", "backend", "agent", "workspace", "timeout_s", "make_kind") if old.get(k)}
    spec["isolate"] = bool(old.get("isolate", True))
    job = state.jobs.create(spec)
    return {"ok": True, "job": {"id": job["id"], "status": job["status"]}, "machine": peers.my_name()}


def make(state: Any, kind: str, brief: str, name: str = "", machine: str = "", projects: Path | None = None) -> dict:
    import peers  # pylint: disable=import-outside-toplevel
    kind = str(kind or "").strip().lower()
    if kind not in KINDS:
        raise ValueError("make one of: %s" % ", ".join(KINDS))
    brief = str(brief or "").strip()
    if len(brief) < 3:
        raise ValueError("say what to make")
    label = KINDS[kind][1]
    title = "%s: %s" % (label, (name or brief).strip().splitlines()[0][:60])
    if machine and machine != peers.my_name():
        # the other machine picks its own folder: the brief names ~/LOKI Projects there
        prompt = brief_for(kind, brief, Path("~/LOKI Projects") / KINDS[kind][0] / slug(name or brief))
        got = peers.call(_peer(machine), "POST", "/peer/jobs", {"prompt": prompt, "title": title,
                                                                 "timeout_s": KINDS[kind][2]})
        return {"ok": bool(got.get("ok")), "job": got.get("job"), "machine": machine, "kind": kind}
    if getattr(state, "jobs", None) is None:
        raise ValueError("background jobs are not running here")
    if projects is None:
        import agent_folders  # pylint: disable=import-outside-toplevel
        projects = agent_folders.projects_dir()
    folder = folder_for(kind, name or brief, Path(projects))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "BRIEF.md").write_text("# %s\n\n%s\n" % (title, brief), encoding="utf-8")
    job = state.jobs.create({"prompt": brief_for(kind, brief, folder), "title": title, "backend": "local",
                             "agent": "loki", "workspace": str(folder), "isolate": False, "timeout_s": KINDS[kind][2],
                             "make_kind": kind})
    try:   # start it now, not on the next tick
        import threading  # pylint: disable=import-outside-toplevel
        threading.Thread(target=state.jobs.tick, daemon=True).start()
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "job": {"id": job["id"], "status": job["status"], "title": job["title"]},
            "folder": str(folder), "machine": peers.my_name(), "kind": kind}


def world_for_peer(state: Any) -> dict:
    """What a linked machine shows of us: the agents at work (no prompts, no paths beyond the folder name)."""
    agents, stats = _local_agents(state)
    keep = ("id", "name", "role", "state", "status", "task", "stage", "last_message", "since", "finished", "job",
            "kind", "note", "error", "can_stop")
    return {"agents": [{k: a.get(k) for k in keep} | {"folder": Path(a.get("workspace") or "").name} for a in agents][:30],
            "stats": stats}
