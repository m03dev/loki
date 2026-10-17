"""LOKI World MMO systems on the engine side (session 28): the player profile that survives
restarts and is the same on every machine (synced over the signed peer link), items and gear,
the vendor and gold, paintings whose rarity is the owner's hearts, achievements (with their Steam
ids) and daily quests from real LOKI use, the guild of the owner's machines and chat channels.

    python tests/test_mmo_systems.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
import creations  # noqa: E402
import mmo_state  # noqa: E402
import peers  # noqa: E402
import presence  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, ("  <- " + str(detail)[:300]) if (detail and not ok) else ""))


def section(title):
    print("\n" + title)


def free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


TMP = Path(tempfile.mkdtemp(prefix="loki-mmo-sys-"))
now = time.time()


def job(jid, status, title, error="", started=None, finished=None, prompt=""):
    return {"id": jid, "status": status, "title": title, "prompt": prompt or title, "error": error, "agent": "loki",
            "backend": "local", "created": now - 3000, "started": started or now - 2900,
            "finished": finished if finished is not None else (now - 100 if status in ("done", "failed") else 0)}


def fresh_profile(name: str, machine: str) -> mmo_state.Profile:
    prof = mmo_state.Profile(TMP / name / "mmo" / "profile.json")
    prof.bind(machine)
    prof.data["init"] = True          # no welcome grant: these tests count exactly
    return prof


try:
    # --------------------------------------------------------------------------------------
    section("the profile survives a restart and keeps every new field")
    prof = fresh_profile("a", "mac")
    prof.data["xp"] = 500
    prof.data["gold"]["earned"] = 40
    item = mmo_state.make_item("drop:job1", 5, "test", "Timeless")
    mmo_state.add_to_bags(prof, item)
    prof.data["achievements"]["first_kill"] = now
    prof.save()
    again = mmo_state.Profile(TMP / "a" / "mmo" / "profile.json")
    check("XP, gold, bags and achievements are on disk under the data folder", again.data["xp"] == 500
          and again.data["gold"]["earned"] == 40 and item["id"] in again.data["bags"] and "first_kill" in again.data["achievements"])
    check("the profile knows which machine it belongs to", again.data["machine"] == "mac")
    old = TMP / "old" / "mmo" / "profile.json"
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps({"name": "Mo", "xp": 77, "stats": {"kills": 2}, "init": True}), encoding="utf-8")
    oldp = mmo_state.Profile(old)
    check("an older profile.json loads (new fields get defaults)", oldp.data["xp"] == 77 and oldp.data["stats"]["kills"] == 2
          and oldp.data["gold"] == {"earned": 0, "spent": 0} and oldp.data["bags"] == {} and oldp.data["guild"] == mmo_state.GUILD_DEFAULT)
    v1 = prof.sync_version()
    check("the shared-profile version is cached until the next save", v1 == prof.sync_version() and len(v1) == 16)
    prof.data["xp"] += 1
    prof.save()
    check("...and changes after one", prof.sync_version() != v1)

    # --------------------------------------------------------------------------------------
    section("items and gear")
    a = mmo_state.make_item("drop:abc", 7, "src", "Unparsed")
    b = mmo_state.make_item("drop:abc", 7, "src", "Unparsed")
    check("the same job always drops the same piece", {k: a[k] for k in ("id", "name", "slot", "rarity", "stats")}
          == {k: b[k] for k in ("id", "name", "slot", "rarity", "stats")}, (a, b))
    check("an item has a slot, a rarity, stats, a value and a look", a["slot"] in mmo_state.GEAR_SLOTS and a["rarity"] in mmo_state.RARITIES
          and a["stats"] and a["value"] > 0 and a["look"])
    rar = {mmo_state.roll_rarity(h) for h in range(0, 1000)}
    check("every rarity can drop", rar == set(mmo_state.RARITIES), rar)
    counts = {}
    for k in range(400):
        counts[mmo_state.make_item("x%d" % k, 5)["rarity"]] = counts.get(mmo_state.make_item("x%d" % k, 5)["rarity"], 0) + 1
    check("legendaries are rare, commons common", counts.get("legendary", 0) < counts.get("common", 0), counts)
    leg = mmo_state.make_item("y", 10, rarity="legendary", slot="weapon")
    com = mmo_state.make_item("y", 10, rarity="common", slot="weapon")
    check("rarer gear is stronger and worth more", leg["stats"]["power"] > com["stats"]["power"] and leg["value"] > com["value"]
          and leg["name"].endswith("of LOKI"))
    check("rarity colours: common / uncommon / rare / epic / legendary", list(mmo_state.RARITY_COLORS) == list(mmo_state.RARITIES))
    check("paintings: hearts make the rarity (0 common ... 5 legendary)", [mmo_state.painting_rarity(h) for h in range(6)]
          == ["common", "uncommon", "rare", "epic", "epic", "legendary"])
    pic = {"path": "images/fox.png", "title": "Fox", "show": "image", "t": now}
    p0, p5 = mmo_state.painting_item(pic, 0), mmo_state.painting_item(pic, 5)
    check("a painting is a relic you carry; a loved one is stronger", p0["slot"] == "relic" and p0["kind"] == "painting"
          and p5["stats"]["power"] > p0["stats"]["power"] and p5["url"] == "/creations/images/fox.png" and p0["value"] == 0)
    bad = mmo_state.clean_item({"id": "../../x", "kind": "gear", "slot": "head", "rarity": "rare"})
    check("an item from another machine is checked: bad ids, slots, rarities are dropped", bad is None
          and mmo_state.clean_item({"id": "g1", "kind": "gear", "slot": "hat", "rarity": "rare"}) is None
          and mmo_state.clean_item("x") is None)
    big = mmo_state.clean_item({"id": "g1", "kind": "gear", "slot": "head", "rarity": "rare", "name": "x" * 500,
                                "stats": {"hp": 1e12, "evil": 3}, "level": 1000, "value": -5})
    check("...and numbers are clamped, names capped, unknown stats dropped", big["stats"] == {"hp": 2000} and big["level"] == 99
          and big["value"] == 0 and len(big["name"]) == 60, big)

    section("bags, equip, gear stats, the vendor, gold")
    gp = fresh_profile("gear", "mac")
    jobs = [job("f1", "failed", "Build the page", error="SyntaxError: unexpected token"),
            job("f2", "failed", "Research: tea", error="timed out after 1800 s"),
            job("d1", "done", "Make an image of a fox", started=now - 700, finished=now - 50)]
    made = [{"path": "images/fox.png", "title": "Fox", "show": "image", "kind": "images", "t": now - 60}]
    r = mmo_state.defeat(gp, jobs, "f1")
    drop = r["loot"][1]
    check("a beaten monster drops gear (seeded by the job) and gold", drop["kind"] == "gear" and drop["id"] == mmo_state.make_item("drop:f1", 1)["id"]
          and r["gold_got"] > 0 and r["gold"] == r["gold_got"], r)
    check("...the gear is in the bags", drop["id"] in gp.data["bags"])
    check("...the first kill unlocks an achievement", "first_kill" in r.get("new_achievements", []), r.get("new_achievements"))
    st = mmo_state.build_state(gp, jobs, made, [], {"name": "mac", "os": "Darwin"})
    base_hp, base_power = st["profile"]["hp_max"], st["profile"]["power"]
    check("state: gear (slots, equipped, bags, rarities), vendor, achievements, daily, guild, sync, gold",
          all(k in st for k in ("gear", "vendor", "achievements", "daily", "guild", "sync")) and st["profile"]["gold"] == r["gold"]
          and st["gear"]["slots"] == list(mmo_state.GEAR_SLOTS) and st["gear"]["bags"][0]["id"] == drop["id"])
    e = mmo_state.equip(gp, drop["id"])
    st2 = mmo_state.build_state(gp, jobs, made, [], {"name": "mac", "os": "Darwin"})
    stat = list(drop["stats"])[0]
    grew = (st2["profile"]["hp_max"] > base_hp) if stat == "hp" else (st2["profile"]["power"] > base_power or st2["profile"]["en_max"] > 100)
    check("wearing it: shown in its slot, the stats count", e["slot"] == drop["slot"] and st2["gear"]["equipped"][drop["slot"]]["id"] == drop["id"]
          and grew and st2["gear"]["bags"][0]["equipped"], (stat, st2["profile"]))
    try:
        mmo_state.sell(gp, drop["id"])
        check("a worn item cannot be sold", False)
    except ValueError:
        check("a worn item cannot be sold", True)
    eq = mmo_state.equip(gp, "painting:images/fox.png", creations=made, likes={"images/fox.png": 5})
    check("a picture can be worn as a painting (relic slot), as rare as it is loved", eq["slot"] == "relic"
          and eq["equipped"]["relic"]["rarity"] == "legendary")
    st3 = mmo_state.build_state(gp, jobs, made, [], {"name": "mac", "os": "Darwin"}, likes={"images/fox.png": 2})
    check("a worn painting follows its hearts", st3["gear"]["equipped"]["relic"]["rarity"] == "rare", st3["gear"]["equipped"]["relic"])
    check("loot: pictures carry their hearts and painting rarity", st3["loot"]["items"][0]["rarity"] == "rare"
          and st3["loot"]["items"][0]["hearts"] == 2 and st3["loot"]["items"][0]["painting"] == "painting:images/fox.png")
    mmo_state.equip(gp, "", "head")
    mmo_state.equip(gp, "", drop["slot"])
    gold_before = mmo_state.gold_of(gp.data)
    s = mmo_state.sell(gp, drop["id"])
    check("selling: the item goes, its value comes in gold", s["gold"] == gold_before + drop["value"]
          and gp.data["bags"][drop["id"]].get("gone") and not mmo_state.bag_items(gp.data))
    for bad_id, why in (("nope", "not in the bags"), (drop["id"], "sold already")):
        try:
            mmo_state.sell(gp, bad_id)
            check("sell refuses an item %s" % why, False)
        except ValueError:
            check("sell refuses an item %s" % why, True)
    stock = mmo_state.vendor_stock(mmo_state.day_key(now), 3)
    check("the vendor has four pieces today, the same on every machine", len(stock) == 4
          and [x["id"] for x in stock] == [x["id"] for x in mmo_state.vendor_stock(mmo_state.day_key(now), 3)]
          and all(x["price"] == x["value"] * 4 for x in stock))
    stock = mmo_state.vendor_stock(mmo_state.day_key(time.time()), mmo_state.level_of(mmo_state.total_xp(gp.data))["level"])
    cheap = min(stock, key=lambda x: x["price"])
    gp.data["gold"]["earned"] += 10000
    bought = mmo_state.buy(gp, cheap["id"])
    check("buying: gold spent, item in the bags", bought["price"] == cheap["price"] and cheap["id"] in gp.data["bags"]
          and gp.data["gold"]["spent"] == cheap["price"])
    try:
        mmo_state.buy(gp, cheap["id"])
        check("each vendor piece sells once", False)
    except ValueError:
        check("each vendor piece sells once", True)
    poor = fresh_profile("poor", "mac")
    try:
        mmo_state.buy(poor, stock[0]["id"])
        check("no gold, no sale", False)
    except ValueError as exc:
        check("no gold, no sale", "gold" in str(exc))
    full = fresh_profile("full", "mac")
    for k in range(mmo_state.BAG_MAX):
        mmo_state.add_to_bags(full, mmo_state.make_item("fill%d" % k, 1))
    over = mmo_state.add_to_bags(full, mmo_state.make_item("one-more", 1))
    check("full bags: a new drop is sold for you", over["auto_sold"] > 0 and len(mmo_state.bag_items(full.data)) == mmo_state.BAG_MAX)
    t = mmo_state.turn_in(gp, jobs, made, "d1")
    check("turning in a quest pays gold too, and the picture made meanwhile", t["gold_got"] >= 5
          and any(x.get("id") == "images/fox.png" for x in t["loot"]))

    # --------------------------------------------------------------------------------------
    section("achievements (with Steam ids) and daily quests from real LOKI use")
    ids = [a[0] for a in mmo_state.ACHIEVEMENTS]
    steam = [a[3] for a in mmo_state.ACHIEVEMENTS]
    check("achievement ids and Steam API names are unique; Steam names are ACH_*", len(set(ids)) == len(ids)
          and len(set(steam)) == len(steam) and all(s.startswith("ACH_") and s.upper() == s for s in steam))
    keys = {a[4] for a in mmo_state.ACHIEVEMENTS}
    check("every achievement counts something real", keys <= set(mmo_state.totals(gp.data)), keys - set(mmo_state.totals(gp.data)))
    ap = fresh_profile("ach", "mac")
    st = mmo_state.build_state(ap, [], made, [], {"name": "mac"}, likes={"images/fox.png": 5})
    unlocked = {a["id"] for a in st["achievements"] if a["unlocked"]}
    check("a picture LOKI made, a like and a legendary painting unlock theirs", {"first_picture", "first_like", "masterpiece"} <= unlocked
          and set(st.get("new_achievements", [])) >= {"first_picture", "masterpiece"}, unlocked)
    st = mmo_state.build_state(ap, [], made, [], {"name": "mac"}, likes={})
    check("unlocked stays unlocked (the like was taken back)", "first_like" in {a["id"] for a in st["achievements"] if a["unlocked"]}
          and "new_achievements" not in st)
    check("each achievement shows progress toward its goal", all(0 <= a["progress"] <= a["need"] for a in st["achievements"]))
    day = mmo_state.day_key(now)
    d1 = mmo_state.daily_quests(day, True)
    check("three daily quests a day, the same on every machine", len(d1) == 3 and d1 == mmo_state.daily_quests(day, True)
          and len({q["metric"] for q in d1}) == 3, d1)
    other_days = {json.dumps(mmo_state.daily_quests("2026-10-%02d" % k, True)) for k in range(1, 15)}
    check("...and they change from day to day", len(other_days) > 5)
    solo = [q["metric"] for k in range(1, 30) for q in mmo_state.daily_quests("2026-11-%02d" % k, False)]
    check("a machine with no linked machines never gets 'visit' or 'guild chat'", "visits" not in solo and "guild_chat" not in solo)
    dp = fresh_profile("daily", "mac")
    real_jobs = [job("r1", "done", "Research: foxes", started=now - 300, finished=now - 10)]
    today_made = [{"path": "images/p%d.png" % k, "title": "p", "show": "image", "kind": "images", "t": now - 5} for k in range(3)]
    metrics = mmo_state.own_day_metrics(dp.data, real_jobs, today_made, now)
    check("today's metrics come from real jobs and creations", metrics["pictures"] == 3 and metrics["jobs_done"] == 1
          and metrics["research_done"] == 1, metrics)
    mmo_state.note(dp, {"visit": "pc"}, "mac")
    mmo_state.note(dp, {"visit": "mac"}, "mac")
    mmo_state.note(dp, {"chat": "guild"}, "mac")
    metrics = mmo_state.own_day_metrics(dp.data, real_jobs, today_made, now)
    check("visiting another island and guild chat count (your own island does not)", metrics["visits"] == 1 and metrics["guild_chat"] == 1
          and dp.data["stats"]["visits"] == 1, metrics)
    st = mmo_state.build_state(dp, real_jobs, today_made, [], {"name": "mac"}, machines=[{"name": "pc", "ok": True}])
    daily = st["daily"]
    check("daily state: date, quests with progress/need/claimed, time to reset", daily["date"] == day and len(daily["quests"]) == 3
          and all({"progress", "need", "done", "claimed", "gold", "xp"} <= set(q) for q in daily["quests"]) and 0 < daily["resets_in_s"] <= 86400)
    # make every metric "done" so whichever three were picked can be claimed
    dp.data["day_counts"][day] = {"visits": 5, "likes_given": 5, "guild_chat": 5}
    many_jobs = [job("j%d" % k, "done", "Research: x%d" % k, started=now - 300, finished=now - 10) for k in range(4)]
    for k in range(4):
        dp.data["turned_in"]["t%d" % k] = now - 5
        dp.data["slain"]["s%d" % k] = now - 5
    st = mmo_state.build_state(dp, many_jobs, today_made, [], {"name": "mac"}, machines=[{"name": "pc", "ok": True}])
    q0 = st["daily"]["quests"][0]
    check("with the work done, the quests are done", all(q["done"] for q in st["daily"]["quests"]), st["daily"]["quests"])
    gold0 = mmo_state.gold_of(dp.data)
    c = mmo_state.claim_daily(dp, q0["id"], True)
    check("claiming a daily: gold and XP, counted", c["gold_got"] == q0["gold"] and c["xp"] == q0["xp"]
          and mmo_state.gold_of(dp.data) == gold0 + q0["gold"] and dp.data["stats"]["dailies"] == 1)
    for qid, why in ((q0["id"], "twice"), ("2020-01-01:job", "from another day")):
        try:
            mmo_state.claim_daily(dp, qid, True)
            check("a daily cannot be claimed %s" % why, False)
        except ValueError:
            check("a daily cannot be claimed %s" % why, True)
    np_ = fresh_profile("notdone", "mac")
    try:
        mmo_state.claim_daily(np_, mmo_state.daily_quests(day, False)[0]["id"], False)
        check("an unfinished daily cannot be claimed", False)
    except ValueError as exc:
        check("an unfinished daily cannot be claimed", "not done" in str(exc))
    old_p = fresh_profile("init", "mac")
    old_p.data["init"] = False
    mmo_state.build_state(old_p, [job("o1", "done", "Old")], [], [], {"name": "mac"})
    check("the first-run grant does not count as today's turn-ins", mmo_state.own_day_metrics(old_p.data, [], [], now)["turned_in"] == 0)

    # --------------------------------------------------------------------------------------
    section("hearts on creations (Settings > Creations)")
    data_dir = TMP / "likes"
    check("no likes yet", creations.get_likes(data_dir) == {})
    check("set hearts (returns the old count), capped at 5", creations.set_likes(data_dir, "images/fox.png", 9) == 0
          and creations.get_likes(data_dir) == {"images/fox.png": 5})
    check("0 hearts removes it", creations.set_likes(data_dir, "images/fox.png", 0) == 5 and creations.get_likes(data_dir) == {})
    for bad_path in ("../x.png", "images/../../x", "secrets/x.png", "images/a/b.png", "images\\x.png"):
        try:
            creations.set_likes(data_dir, bad_path, 1)
            check("refused path %r" % bad_path, False)
        except ValueError:
            check("refused path %r" % bad_path, True)
    lp = fresh_profile("liker", "mac")
    r = mmo_state.like(lp, data_dir, "images/fox.png", 3, made)
    check("POST /mmo/like logic: hearts, painting rarity, counted as a like today", r == {"path": "images/fox.png", "hearts": 3, "rarity": "epic"}
          and lp.data["stats"]["likes"] == 1 and lp.data["day_counts"][day]["likes_given"] == 1)
    mmo_state.like(lp, data_dir, "images/fox.png", 1, made)
    check("taking hearts back is not a new like", lp.data["stats"]["likes"] == 1)
    try:
        mmo_state.like(lp, data_dir, "images/none.png", 1, made)
        check("only an existing creation can be liked", False)
    except ValueError:
        check("only an existing creation can be liked", True)

    # --------------------------------------------------------------------------------------
    section("one character on every machine: the shared profile merges")
    mac = fresh_profile("smac", "mac")
    pc = fresh_profile("spc", "pc")
    mac.data["xp"], pc.data["xp"] = 300, 200
    mac.data["stats"]["kills"], pc.data["stats"]["kills"] = 2, 3
    mac.data["gold"] = {"earned": 50, "spent": 10}
    pc.data["gold"] = {"earned": 30, "spent": 0}
    mac.save()
    pc.save()
    mmo_state.set_profile(mac, {"name": "Mohamed", "cls": "Mage"})
    time.sleep(0.01)
    mmo_state.set_profile(pc, {"cls": "Warrior"})
    sword = mmo_state.make_item("pc-sword", 3, slot="weapon")
    mmo_state.add_to_bags(pc, sword)
    mmo_state.equip(pc, sword["id"])
    check("merging the other machine's document changes something", mmo_state.merge_doc(mac, mmo_state.export_doc(pc)))
    mmo_state.merge_doc(pc, mmo_state.export_doc(mac))
    for name, pr in (("mac", mac), ("pc", pc)):
        d = pr.data
        check("%s: XP adds up over machines (300 + 200)" % name, mmo_state.total_xp(d) == 500, mmo_state.total_xp(d))
        check("%s: stats add up, gold = all earned - all spent" % name, mmo_state.total_stats(d)["kills"] == 5
              and mmo_state.gold_of(d) == 70)
        check("%s: class is the newest choice (last writer wins), name kept" % name, d["cls"] == "Warrior" and d["name"] == "Mohamed")
        check("%s: the sword is in the bags and worn" % name, sword["id"] in d["bags"]
              and d["equipped"]["weapon"]["id"] == sword["id"])
    check("both machines now have the same shared profile (same version)", mac.sync_version() == pc.sync_version(),
          (mac.sync_version(), pc.sync_version()))
    check("merging the same again changes nothing", not mmo_state.merge_doc(mac, mmo_state.export_doc(pc)))
    mmo_state.sell(mac, sword["id"]) if not mac.data["equipped"]["weapon"]["id"] == sword["id"] else None
    mmo_state.equip(mac, "", "weapon")
    mmo_state.sell(mac, sword["id"])
    mmo_state.merge_doc(pc, mmo_state.export_doc(mac))
    check("selling on one machine removes it on the other (newest change wins per item)", pc.data["bags"][sword["id"]].get("gone")

          and not pc.data["equipped"]["weapon"]["id"])
    check("...and the gold from the sale counts there too", mmo_state.gold_of(pc.data) == mmo_state.gold_of(mac.data))
    section("LWW stamps: two changes in the same millisecond must not tie (the intermittent 'sold on one machine, still in the bags on the other')")
    check("stamps keep sub-millisecond precision", mmo_state.STAMP_DECIMALS >= 6, mmo_state.STAMP_DECIMALS)
    _seq = fresh_profile("stamps", "probe")
    _it = {"id": "gprobe1", "kind": "gear", "name": "Probe Blade", "slot": "weapon", "look": "sword",
           "rarity": "rare", "level": 3, "stats": {"power": 4}, "value": 10, "src": "test", "t": 0.0, "ts": 0.0}
    mmo_state.add_to_bags(_seq, _it)
    _before = _it["ts"]
    mmo_state.sell(_seq, "gprobe1")
    check("a sell made in the same millisecond is strictly newer than the item it stamps",
          float(_seq.data["bags"]["gprobe1"]["ts"]) > float(_before),
          (_before, _seq.data["bags"]["gprobe1"]["ts"]))
    check("and a 0.0005s-newer gone marker wins the merge (ms stamps could not tell them apart)",
          mmo_state.merge_doc(_seq, {"v": mmo_state.SYNC_VERSION, "machine": "twin", "bags": {
              "gprobe1": dict(_it, ts=float(_seq.data["bags"]["gprobe1"]["ts"]) + 0.0005, gone=True)}}))
    check("...without accepting an OLDER one", not mmo_state.merge_doc(_seq, {"v": mmo_state.SYNC_VERSION, "machine": "twin", "bags": {
        "gprobe1": dict(_it, ts=float(_seq.data["bags"]["gprobe1"]["ts"]) - 1.0, gone=False)}}))
    wiped = fresh_profile("wiped", "mac")
    mmo_state.merge_doc(wiped, mmo_state.export_doc(pc))
    check("a reinstalled machine gets its own progress back from its twin", wiped.data["xp"] == 300 and mmo_state.total_xp(wiped.data) == 500
          and wiped.data["gold"]["earned"] >= 50, (wiped.data["xp"], wiped.data["gold"]))
    mac.data["achievements"]["first_quest"] = now - 50
    pc.data["achievements"]["first_quest"] = now - 10
    mmo_state.merge_doc(pc, mmo_state.export_doc(mac))
    check("an achievement keeps its earliest unlock time", pc.data["achievements"]["first_quest"] == now - 50)
    evil = {"v": 1, "lww": {"name": ["\x00evil" + "x" * 100, 1e20], "cls": ["Necromancer", 1e10]},
            "counters": {"zz": {"xp": "lots", "stats": {"kills": -5}, "t": "x"}, "pc": "nope"},
            "bags": {"a": {"id": "../etc", "kind": "gear", "slot": "head", "rarity": "rare"}},
            "equipped": {"head": {"item": {"id": "g", "kind": "gear", "slot": "weapon", "rarity": "rare"}, "ts": 1e10}},
            "achievements": {"not_real": 1, "first_kill": "x"}, "claimed": {"bad day": {"x": 1}}}
    before = json.dumps(pc.data, sort_keys=True)
    mmo_state.merge_doc(pc, evil)
    pcd = pc.data
    check("a hostile document: control characters gone, name capped, unknown class refused",
          "\x00" not in pcd["name"] and len(pcd["name"]) <= 24 and pcd["cls"] == "Warrior")
    check("...bad counters cleaned, bad items, mismatched slots and unknown achievements ignored",
          pcd["counters"].get("zz", {}).get("xp", 0) == 0 and "../etc" not in pcd["bags"] and (pcd["equipped"].get("head") or {}).get("item") is None
          and "not_real" not in pcd["achievements"] and "bad day" not in pcd["claimed"])
    check("a document of another version is ignored", not mmo_state.merge_doc(pc, {"v": 99, "lww": {"name": ["x", 1e11]}}))
    check("...and so is garbage", not mmo_state.merge_doc(pc, "x") and not mmo_state.merge_doc(pc, None))
    check("the document is small enough for the peer link", len(json.dumps(mmo_state.export_doc(full))) < peers.MAX_BODY // 20)

    # --------------------------------------------------------------------------------------
    section("the profile travels on the signed peer link (presence), even with the world closed")
    clock = {"t": 5000.0}
    smac = fresh_profile("lmac", "mac")
    spc = fresh_profile("lpc", "pc")
    smac.data["xp"] = 1000
    smac.save()
    spc.data["xp"] = 10
    spc.save()
    MAC = presence.Presence(lambda: "mac", clock=lambda: clock["t"], sync=mmo_state.SyncAdapter(smac))
    PCH = presence.Presence(lambda: "pc", clock=lambda: clock["t"], sync=mmo_state.SyncAdapter(spc))
    SECRET = "q" * 40
    server = peers.PeerServer({"hello": lambda: {}, "presence": PCH.receive}, env={"LOKI_PEER_SECRET": SECRET},
                              host="127.0.0.1", port_number=free_port()).start()
    PEER = {"name": "pc", "url": "http://127.0.0.1:%d" % server.address[1]}
    env = {"LOKI_PEER_SECRET": SECRET, "LOKI_PEER_NAME": "mac"}
    sent_bodies = []

    def mac_call(peer, method, path, payload=None, timeout=4.0):
        sent_bodies.append(payload)
        return peers.call(peer, method, path, payload, env=env, timeout=timeout)

    try:
        check("world closed, profile never sent: the peer is due for a profile exchange", MAC.due(["pc"]) == ["pc"])
        v_before = smac.sync_version()
        ok = MAC.push_once(PEER, mac_call)
        check("one signed exchange", ok, MAC.errors)
        check("...carried no avatar (world closed) but the profile", sent_bodies[-1]["player"] is None and "mmo" in sent_bodies[-1]
              and sent_bodies[-1]["mmo_v"] == v_before, sent_bodies[-1].keys())
        check("both sides have both machines' XP (1000 + 10) after ONE call", mmo_state.total_xp(spc.data) == 1010
              and mmo_state.total_xp(smac.data) == 1010, (mmo_state.total_xp(spc.data), mmo_state.total_xp(smac.data)))
        check("...the same version on both", smac.sync_version() == spc.sync_version())
        check("nothing new: not due again for a while", MAC.due(["pc"]) == [])
        clock["t"] += presence.SYNC_EVERY_S + 1
        check("...but it looks in on the peer every minute", MAC.due(["pc"]) == ["pc"])
        MAC.push_once(PEER, mac_call)
        check("a quiet look-in sends only the hash, not the document", "mmo" not in sent_bodies[-1] and sent_bodies[-1]["mmo_v"])
        clock["t"] += 2
        mmo_state.set_profile(spc, {"name": "Mo the Great"})     # changed on the PC
        mmo_state._grant(spc, 90)
        spc.save()
        check("a change on the far side comes back in the reply", MAC.push_once(PEER, mac_call)
              and smac.data["name"] == "Mo the Great" and mmo_state.total_xp(smac.data) == 1100, (smac.data["name"], mmo_state.total_xp(smac.data)))
        clock["t"] += 2
        mmo_state.cast_recorded(smac)                              # changed on the Mac
        check("a change here makes the peer due within a second", MAC.due(["pc"]) == ["pc"])
        MAC.push_once(PEER, mac_call)
        check("...and gets there", mmo_state.total_stats(spc.data)["casts"] == 1)
        snap = MAC.update_local({"player": {"name": "Mo", "zone": "mac"}, "chat": "hi guild", "channel": "guild"})
        check("chat lines carry a channel (guild)", snap["chat"][-1]["ch"] == "guild")
        MAC.update_local({"chat": "weird", "channel": "<script>"})
        check("unknown channels become say", MAC.snapshot(0)["chat"][-1]["ch"] == "say")
        MAC.push_once(PEER, mac_call)
        lines = {c["text"]: c["ch"] for c in PCH.snapshot(0)["chat"]}
        check("the channel travels to the other machine", lines.get("hi guild") == "guild" and lines.get("weird") == "say", lines)
        st_pc = PCH.status()
        check("presence status reports profile syncs", st_pc["synced"] >= 1)
    finally:
        server.stop()

    # --------------------------------------------------------------------------------------
    section("the guild: the owner's characters on his machines")
    gd = fresh_profile("guild", "mac").data
    g = mmo_state.guild_state(gd, {"name": "mac"}, [{"name": "pc", "ok": True}, {"name": "laptop", "ok": False}],
                              [{"machine": "pc", "name": "Mo", "cls": "Warrior", "lvl": 9, "zone": "mac"}])
    by = {m["machine"]: m for m in g["members"]}
    check("this machine, every linked machine; who is online and where", set(by) == {"mac", "pc", "laptop"} and by["mac"]["self"]
          and by["pc"]["online"] and by["pc"]["zone"] == "mac" and by["pc"]["level"] == 9 and not by["laptop"]["online"]
          and g["online"] == 2 and g["name"] == mmo_state.GUILD_DEFAULT, g)
    gp2 = fresh_profile("guild2", "mac")
    check("the guild can be renamed (shared, last writer wins)", mmo_state.set_profile(gp2, {"guild": "Fox Den"})["guild"] == "Fox Den"
          and gp2.data["lww"]["guild"] > 0)

    # --------------------------------------------------------------------------------------
    section("the /mmo routes")

    class Store:
        def __init__(self, jobs_):
            self.jobs = {j["id"]: j for j in jobs_}

        def all(self):
            return list(self.jobs.values())

    class Agent:
        DATA_DIR = str(TMP / "engine")
        WORKSPACE = str(TMP / "ws")

    (TMP / "ws" / "images").mkdir(parents=True)
    (TMP / "ws" / "images" / "20261017-101010-a-fox.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 16)
    RJOBS = [job("rf", "failed", "Build it", error="permission denied"), job("rd", "done", "Research: x")]

    class Jobs:
        store = Store(RJOBS)

    class State:
        agent = Agent()
        chat_lock = None
        jobs = Jobs()

    def ja(state, route_, spec):
        return 200, {"ok": True, "id": "new"}

    S = State()
    code, out = mmo_state.route(S, "GET", "/mmo/state", {}, ja)
    check("GET /mmo/state has the new parts and is JSON", code == 200 and all(k in out for k in ("gear", "vendor", "achievements", "daily", "guild", "sync"))
          and json.dumps(out) and out["profile"]["gold"] == 0)
    code, out = mmo_state.route(S, "POST", "/mmo/monster/defeat", {"id": "rf"}, ja)
    gear_id = out["loot"][1]["id"]
    check("POST /mmo/monster/defeat drops gear and gold", code == 200 and out["gold_got"] > 0 and gear_id.startswith("g"))
    code, out = mmo_state.route(S, "POST", "/mmo/equip", {"id": gear_id}, ja)
    check("POST /mmo/equip", code == 200 and out["equipped"][out["slot"]]["id"] == gear_id, out)
    code, out = mmo_state.route(S, "POST", "/mmo/vendor/sell", {"id": gear_id}, ja)
    check("POST /mmo/vendor/sell refuses a worn item (400 with a reason)", code == 400 and "take it off" in out["error"])
    mmo_state.route(S, "POST", "/mmo/equip", {"id": "", "slot": out.get("slot") or mmo_state.profile_for(TMP / "engine").data["bags"][gear_id]["slot"]}, ja)
    code, out = mmo_state.route(S, "POST", "/mmo/vendor/sell", {"id": gear_id}, ja)
    check("POST /mmo/vendor/sell", code == 200 and out["gold_got"] > 0 and "first_sale" in out.get("new_achievements", []), out)
    code, out = mmo_state.route(S, "POST", "/mmo/vendor/buy", {"id": "nope"}, ja)
    check("POST /mmo/vendor/buy of something not sold today: 400", code == 400)
    code, out = mmo_state.route(S, "POST", "/mmo/like", {"path": "images/20261017-101010-a-fox.png", "hearts": 5}, ja)
    check("POST /mmo/like", code == 200 and out["rarity"] == "legendary", out)
    code, out = mmo_state.route(S, "GET", "/mmo/likes", {}, ja)
    check("GET /mmo/likes", code == 200 and out["likes"] == {"images/20261017-101010-a-fox.png": 5} and out["max"] == 5)
    code, out = mmo_state.route(S, "POST", "/mmo/equip", {"id": "painting:images/20261017-101010-a-fox.png"}, ja)
    check("POST /mmo/equip a painting", code == 200 and out["equipped"]["relic"]["rarity"] == "legendary", out)
    code, out = mmo_state.route(S, "POST", "/mmo/daily/claim", {"id": "nope"}, ja)
    check("POST /mmo/daily/claim of a quest that is not today's: 400", code == 400)
    code, out = mmo_state.route(S, "POST", "/mmo/guild", {"name": "Fox Den"}, ja)
    check("POST /mmo/guild renames the guild", code == 200 and out["guild"] == "Fox Den")
    code, out = mmo_state.route(S, "POST", "/mmo/note", {"visit": "pc"}, ja)
    check("POST /mmo/note {visit} counts an island visit", code == 200 and out["stats"]["visits"] == 1
          and "traveller" in out.get("new_achievements", []), out)
    code, out = mmo_state.route(S, "GET", "/mmo/state", {}, ja)
    check("...all of it is in the next state", out["guild"]["name"] == "Fox Den" and out["gear"]["equipped"]["relic"]["rarity"] == "legendary"
          and out["profile"]["gold"] > 0 and out["profile"]["guild"] == "Fox Den" and out["sync"]["version"])
    check("the running engine's profile is what the presence hub syncs", mmo_state.active_profile() is mmo_state.profile_for(TMP / "engine")
          and presence.HUB.sync.version() == mmo_state.profile_for(TMP / "engine").sync_version())

    # --------------------------------------------------------------------------------------
    section("docs, Settings > Creations, suite")
    api = (REPO / "docs" / "MMO_API.md").read_text(encoding="utf-8")
    for route_ in ("/mmo/equip", "/mmo/vendor/sell", "/mmo/vendor/buy", "/mmo/daily/claim", "/mmo/like", "/mmo/likes", "/mmo/guild"):
        check("docs/MMO_API.md documents %s" % route_, route_ in api)
    check("docs/MMO_API.md explains the shared profile sync", "mmo_v" in api and "last writer wins" in api.lower())
    check("ship.py runs this suite", '"test_mmo_systems"' in (REPO / "tools" / "ship.py").read_text(encoding="utf-8"))
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
