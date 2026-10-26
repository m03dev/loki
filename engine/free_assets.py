"""Free CC0 assets for LOKI's agents (owner 2026-10-26: "get more open resources for free").

Only sources whose assets are CC0 - free for anything, commercial too, no attribution needed for the ASSETS:
  polyhaven   HDRIs, PBR textures, models     api.polyhaven.com - the API asks for a unique User-Agent and a visible
                                              "Powered by Poly Haven" credit for API use (written into each sidecar)
  ambientcg   PBR materials, HDRIs            ambientcg.com/api/v2 (CC0)
Kenney, Quaternius and KayKit (CC0 game kits) have no API: they are listed in KITS for agents to point the owner at.

    search(source, query, kind)  -> [{"id", "name", "kind", "source", "tags", "licence"}]
    download(source, id, dest_dir, resolution="1k", kind=...) -> {"files": [...], "main": path, "licence", "credit"}

Files land in <workspace>/assets/<source>/<id>/ with a loki_asset.json sidecar (source, licence, credit, url).
Standard library only.
"""
from __future__ import annotations

import io
import json
import os
import re
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

UA = "LOKI/1.0 (+https://github.com/m03dev/loki)"
PH = "https://api.polyhaven.com"
ACG = "https://ambientcg.com/api/v2/full_json"
LICENCE = "CC0-1.0"
KITS = [
    {"name": "Kenney", "url": "https://kenney.nl/assets", "what": "game kits: 3D, 2D, UI, audio", "licence": LICENCE},
    {"name": "Quaternius", "url": "https://quaternius.com", "what": "low-poly characters (many rigged) and props", "licence": LICENCE},
    {"name": "KayKit", "url": "https://kaylousberg.itch.io", "what": "stylised low-poly game kits", "licence": LICENCE},
]
PH_KINDS = {"hdri": "hdris", "hdris": "hdris", "texture": "textures", "textures": "textures", "model": "models",
            "models": "models"}


class AssetError(Exception):
    pass


def _get(url: str, opener=urllib.request.urlopen, timeout: float = 60, raw: bool = False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with opener(req, timeout=timeout) as r:
            data = r.read()
    except Exception as exc:  # noqa: BLE001
        raise AssetError("%s: %s" % (url.split("?")[0], exc)) from None
    return data if raw else json.loads(data.decode("utf-8"))


def _words(q: str) -> list:
    return [w for w in re.findall(r"[a-z0-9]+", str(q or "").lower()) if len(w) > 1]


# ----------------------------------------------------------------------------- Poly Haven
def polyhaven_search(query: str = "", kind: str = "models", limit: int = 12, opener=urllib.request.urlopen) -> list:
    t = PH_KINDS.get(str(kind).lower(), "models")
    data = _get("%s/assets?t=%s" % (PH, t), opener)
    words = _words(query)
    rows = []
    for aid, a in (data or {}).items():
        hay = " ".join([aid, a.get("name", "")] + list(a.get("tags", [])) + list(a.get("categories", []))).lower()
        score = sum(w in hay for w in words) if words else 1
        if score:
            rows.append((score, a.get("download_count", 0), aid, a))
    rows.sort(key=lambda r: (-r[0], -r[1]))
    return [{"id": aid, "name": a.get("name", aid), "kind": t, "source": "polyhaven", "tags": a.get("tags", [])[:8],
             "licence": LICENCE} for _s, _d, aid, a in rows[:limit]]


def _pick_res(options: dict, want: str) -> str:
    keys = list(options or {})
    if want in keys:
        return want
    order = ["1k", "2k", "4k", "8k", "16k"]
    return next((k for k in order if k in keys), keys[0] if keys else "")


def polyhaven_download(aid: str, dest: Path, resolution: str = "1k", kind: str = "", opener=urllib.request.urlopen) -> dict:
    files = _get("%s/files/%s" % (PH, urllib.parse.quote(aid)), opener)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    got = []

    def fetch(url: str, rel: str) -> Path:
        target = (dest / rel).resolve()
        if dest.resolve() not in target.parents and target != dest.resolve():
            raise AssetError("refusing a path outside the asset folder: %s" % rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_get(url, opener, timeout=300, raw=True))
        got.append(str(target))
        return target

    main = None
    if "gltf" in files:                                    # a model: the .gltf + its .bin and textures
        res = _pick_res(files["gltf"], resolution)
        g = files["gltf"][res]["gltf"]
        main = fetch(g["url"], Path(g["url"]).name)
        for rel, inc in (g.get("include") or {}).items():
            fetch(inc["url"], rel)
    elif "hdri" in files:
        res = _pick_res(files["hdri"], resolution)
        h = files["hdri"][res]
        f = h.get("hdr") or h.get("exr")
        main = fetch(f["url"], Path(f["url"]).name)
    else:                                                  # a texture set: every map at one resolution, as jpg/png
        for mapname, by_res in files.items():
            if not isinstance(by_res, dict):
                continue
            res = _pick_res(by_res, resolution)
            fmt = by_res.get(res) or {}
            f = fmt.get("jpg") or fmt.get("png") or next(iter(fmt.values()), None) if isinstance(fmt, dict) else None
            if isinstance(f, dict) and f.get("url"):
                p = fetch(f["url"], Path(f["url"]).name)
                main = main or p
    if main is None:
        raise AssetError("Poly Haven had no downloadable files for %s" % aid)
    return {"main": str(main), "files": got}


# ----------------------------------------------------------------------------- ambientCG
def ambientcg_search(query: str = "", kind: str = "Material", limit: int = 12, opener=urllib.request.urlopen) -> list:
    q = urllib.parse.urlencode({"type": kind if kind in ("Material", "HDRI", "Atlas", "Decal") else "Material",
                                "q": query or "", "limit": limit, "include": "tagData,downloadData", "sort": "Popular"})
    data = _get("%s?%s" % (ACG, q), opener)
    return [{"id": a.get("assetId"), "name": a.get("displayName") or a.get("assetId"), "kind": a.get("dataType"),
             "source": "ambientcg", "tags": (a.get("tags") or [])[:8], "licence": LICENCE}
            for a in (data or {}).get("foundAssets", [])][:limit]


def ambientcg_download(aid: str, dest: Path, resolution: str = "1k", opener=urllib.request.urlopen) -> dict:
    q = urllib.parse.urlencode({"id": aid, "include": "downloadData"})
    data = _get("%s?%s" % (ACG, q), opener)
    assets = (data or {}).get("foundAssets") or []
    if not assets:
        raise AssetError("ambientCG has no asset %s" % aid)
    cats = ((assets[0].get("downloadFolders") or {}).get("default") or {}).get("downloadFiletypeCategories") or {}
    downloads = (cats.get("zip") or {}).get("downloads") or []
    want = resolution.upper() + "-JPG"
    pick = next((d for d in downloads if d.get("attribute") == want), None) or \
        next((d for d in downloads if str(d.get("attribute", "")).endswith("JPG")), None) or (downloads[0] if downloads else None)
    if not pick:
        raise AssetError("ambientCG had no download for %s" % aid)
    blob = _get(pick["downloadLink"], opener, timeout=300, raw=True)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    got = []
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for info in z.infolist():
            name = Path(info.filename).name
            if info.is_dir() or not name or name.startswith("."):
                continue
            (dest / name).write_bytes(z.read(info))
            got.append(str(dest / name))
    main = next((p for p in got if re.search(r"_Color\.|_BaseColor\.|\.hdr$|\.exr$", p)), got[0] if got else "")
    return {"main": main, "files": got, "variant": pick.get("attribute")}


# ----------------------------------------------------------------------------- one door for agents
def search(source: str, query: str = "", kind: str = "", limit: int = 12, opener=urllib.request.urlopen) -> list:
    if source == "polyhaven":
        return polyhaven_search(query, kind or "models", limit, opener)
    if source == "ambientcg":
        return ambientcg_search(query, kind or "Material", limit, opener)
    raise AssetError("source is polyhaven or ambientcg (Kenney / Quaternius / KayKit: see KITS, no API)")


def download(source: str, aid: str, workspace: Path, resolution: str = "1k", kind: str = "",
             opener=urllib.request.urlopen) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", str(aid or "")):
        raise AssetError("bad asset id")
    dest = Path(workspace) / "assets" / source / aid
    if source == "polyhaven":
        res = polyhaven_download(aid, dest, resolution, kind, opener)
        credit = "Powered by Poly Haven (polyhaven.com) - asset CC0"
        url = "https://polyhaven.com/a/" + aid
    elif source == "ambientcg":
        res = ambientcg_download(aid, dest, resolution, opener)
        credit = "ambientCG (ambientcg.com) - CC0"
        url = "https://ambientcg.com/view?id=" + aid
    else:
        raise AssetError("source is polyhaven or ambientcg")
    side = {"source": source, "id": aid, "licence": LICENCE, "credit": credit, "url": url, "resolution": resolution,
            "files": [os.path.relpath(f, dest) for f in res["files"]]}
    (dest / "loki_asset.json").write_text(json.dumps(side, indent=1), encoding="utf-8")
    return dict(res, ok=True, licence=LICENCE, credit=credit, url=url, folder=str(dest))


TOOL = {"name": "free_assets",
        "description": "CC0 assets, free for anything: Poly Haven (models, HDRIs, PBR textures) and ambientCG (PBR "
                       "materials, HDRIs). action=search: source (polyhaven|ambientcg), query, kind (polyhaven: "
                       "models|hdris|textures; ambientcg: Material|HDRI). action=download: source, id, resolution "
                       "(1k default) -> assets/<source>/<id>/ (use the main file with the blender tool: import). "
                       "action=kits: CC0 game kits without an API (Kenney, Quaternius, KayKit).",
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["search", "download", "kits"]},
            "source": {"type": "string", "enum": ["polyhaven", "ambientcg"]}, "query": {"type": "string"},
            "kind": {"type": "string"}, "id": {"type": "string"}, "resolution": {"type": "string"}},
            "required": ["action"]}}


def tool(args: dict, cwd: Path, opener=urllib.request.urlopen) -> dict:
    a = args or {}
    try:
        act = a.get("action") or "search"
        if act == "kits":
            return {"ok": True, "kits": KITS}
        if act == "download":
            return download(str(a.get("source") or "polyhaven"), str(a.get("id") or ""), Path(cwd),
                            str(a.get("resolution") or "1k"), str(a.get("kind") or ""), opener)
        return {"ok": True, "results": search(str(a.get("source") or "polyhaven"), str(a.get("query") or ""),
                                              str(a.get("kind") or ""), int(a.get("limit") or 12), opener)}
    except AssetError as exc:
        return {"ok": False, "error": str(exc)}
