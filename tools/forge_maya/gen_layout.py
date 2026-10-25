"""Forge laid out like Maya 2027 (owner 2026-10-22: "rework everything so its like that, its almost 1:1 to maya ...
place everything exactly like that, thats how maya works and those are where those functions go").

Input:  docs/forge/maya2027_layout.json  - Maya's own layout (tools/forge_maya/extract_maya.py reads it from a Maya
                                           install): every Modeling-set menu, the hotbox zones, the marking menus
                                           with their compass positions, the default hotkeys.
        MAP (below)                       - which Forge command does each Maya command.
Output: app/ui/forge_maya_layout.js       - FORGE_MAYA: the menu bar, the menu sets, every menu in Maya's order with
                                           Maya's labels and section headings, the hotbox zones and the marking
                                           menus at Maya's compass positions - built only from commands Forge has
                                           (a row Forge can't run is not drawn: a menu must not lie).
        docs/FORGE_MAYA_PARITY.md         - the plan and the record: every Maya row, the Forge command it maps to or
                                           "not yet", per menu and in total.

    python tools/forge_maya/gen_layout.py            (writes both)
    python tools/forge_maya/gen_layout.py --check    (exit 1 when either output is stale - tests/test_forge_maya_layout.py)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LAYOUT = REPO / "docs" / "forge" / "maya2027_layout.json"
OUT_JS = REPO / "app" / "ui" / "forge_maya_layout.js"
OUT_MD = REPO / "docs" / "FORGE_MAYA_PARITY.md"

# Maya runtime command -> Forge command id. One Forge command can stand in for several Maya rows.
MAP = {
    # File
    "SaveScene": "save", "Export": "export", "CreateImagePlane": "imagePlane",
    # Edit
    "Undo": "undo", "Redo": "redo", "RepeatLast": "repeatLast", "Delete": "delete", "DeleteHistory": "deleteHistory",
    "DeleteAllHistory": "deleteHistory", "Duplicate": "duplicate", "DuplicateWithTransform": "duplicateT",
    "Group": "group", "Ungroup": "ungroup", "Parent": "parent", "Unparent": "unparent",
    # Create
    "CreatePolygonSphere": "sphere", "CreatePolygonCube": "cube", "CreatePolygonCylinder": "cylinder",
    "CreatePolygonCone": "cone", "CreatePolygonTorus": "torus", "CreatePolygonPlane": "plane",
    # Select
    "SelectAll": "selectAll", "SelectNone": "selectNone", "SelectHierarchy": "hierarchy", "InvertSelection": "invert",
    "GrowPolygonSelectionRegion": "grow", "ShrinkPolygonSelectionRegion": "shrink", "SelectToggleMode": "objComp",
    "SelectMultiComponentMask": "multi", "SelectVertexMask": "vertex", "SelectEdgeMask": "edge",
    "SelectFacetMask": "face", "SelectVertexFaceMask": "vertexFace", "SelectUVMask": "uv",
    "SelectMeshUVShell": "uvShell", "SelectEdgeLoopSp": "loopSel", "SelectEdgeRingSp": "ringSel",
    "ConvertSelectionToUVs": "toUV",
    # Modify
    "MoveTool": "move", "RotateTool": "rotate", "ScaleTool": "scale", "ShowManipulatorTool": "showManip",
    "ResetTransformations": "resetXf", "FreezeTransformations": "freeze", "CenterPivot": "centerPivot",
    "ZeroPivot": "resetPivot", "MakeLive": "makeLive",
    # Display
    "ToggleGrid": "grid", "ToggleInViewEditor": "iveToggle", "ToggleVisibilityAndKeepSelection": "hideToggle",
    "HideSelectedObjects": "hide", "HideUnselectedObjects": "hideOthers", "ShowSelectedObjects": "show",
    "ShowLastHidden": "showLast", "ShowAll": "showAll", "FrameAllInAllViews": "frameAll",
    "FrameSelectedWithoutChildrenInAllViews": "frameSel",
    # Windows
    "OpenChannelBox": "winChannel", "OpenChannelsLayers": "winChannel", "OpenLayerEditor": "layerEditor",
    "DisplayLayerEditorWindow": "layerEditor", "OpenModelingToolkit": "winToolkit", "TextureViewWindow": "uvEditor",
    "OutlinerWindow": "winOutliner", "GraphEditor": "graphEditor", "HypershadeWindow": "winMaterials",
    "RenderViewWindow": "renderDialog", "HotkeyPreferencesWindow": "hotkeyEditor", "PreferencesWindow": "preferences",
    # Mesh
    "PolygonBooleanUnion": "boolUnion", "PolygonBooleanDifference": "boolDifference",
    "PolygonBooleanDifferenceBA": "boolDifferenceBA", "PolygonBooleanIntersection": "boolIntersection",
    "PolygonBooleanSlice": "boolSlice", "PolygonBooleanHolePunch": "boolHolePunch", "PolygonBooleanCutOut": "boolCutOut",
    "PolygonBooleanSplitEdges": "boolSplitEdges",
    "CombinePolygons": "combine", "SeparatePolygon": "separate", "FillHole": "fillHole", "ReducePolygon": "sculptReduce",
    "PolyRemesh": "sculptRemesh", "PolyRetopo": "sculptQuadRemesh", "SmoothPolygon": "smooth", "Triangulate": "triangulate",
    "Quadrangulate": "quadrangulate", "MirrorPolygonGeometry": "mirror", "CleanupPolygon": "cleanup",
    # Edit Mesh
    "BevelPolygon": "bevel", "BridgeOrFill": "bridge", "BridgeEdge": "bridge", "performBridgeOrFill": "bridge",
    "PolyCircularize": "circularize", "PolygonCollapse": "collapse", "polyCollapseEdge": "collapse",
    "ConnectComponents": "connect", "EnterConnectTool": "connect", "PolyEditEdgeFlow": "editEdgeFlow",
    "MovePolygonComponent": "transformComp", "ConformPolygonNormals": "conformNormals",
    "SetToFaceNormals": "setToFace", "AveragePolygonNormals": "averageNormals", "DetachComponent": "detach", "PolyExtrude": "extrude", "PolyMerge": "merge",
    "MergeToCenter": "mergeCenter", "AverageVertex": "averageVerts", "ChamferVertex": "chamfer",
    "DeletePolyElements": "deleteEdgeVert", "DeleteEdge": "deleteEdgeVert", "DeleteVertex": "deleteEdgeVert",
    "PolySpinEdgeBackward": "spinEdgeBack", "PolySpinEdgeForward": "spinEdge", "DuplicateFace": "duplicateFace",
    "ExtractFace": "extractFace", "PokePolygon": "poke", "WedgePolygon": "wedge",
    "ConvertSelectionToVertices": "convertToVerts", "ConvertSelectionToEdges": "convertToEdges",
    "ConvertSelectionToFaces": "convertToFaces", "ConvertSelectionToContainedEdges": "convertToContainedEdges",
    "ConvertSelectionToContainedFaces": "convertToContainedFaces", "ConvertSelectionToEdgePerimeter": "convertToEdgePerimeter",
    "ConvertSelectionToVertexPerimeter": "convertToVertexPerimeter", "ConvertSelectionToFacePerimeter": "convertToFacePerimeter",
    "ConvertSelectionToShell": "convertToShell", "ConvertSelectionToShellBorder": "convertToShellBorder",
    "SelectSimilar": "selectSimilar", "SelectShortestEdgePathTool": "shortestPath",
    "GrowLoopPolygonSelectionRegion": "growLoop", "ShrinkLoopPolygonSelectionRegion": "shrinkLoop",
    "SelectContiguousEdges": "contiguousEdges", "CreateQuickSelectSet": "quickSet", "ArtPaintSelectTool": "paintSelect", "BakeCustomPivot": "bakePivot",
    "MatchTransform": "matchAll", "MatchTranslation": "matchTranslate", "MatchRotation": "matchRotate",
    "MatchScaling": "matchScale", "MatchPivots": "matchPivot", "SetEditor": "setEditor",
    "NewScene": "newScene", "OpenScene": "openScene", "SaveSceneAs": "saveAs", "Import": "importFile",
    "SubdividePolygon": "addDivisions", "FlipTriangleEdge": "flipTriangleEdge", "Symmetrize": "symmetrize", "FlipMesh": "flipMesh",
    # Mesh Tools
    "ToggleModelingToolkit": "winToolkit", "SplitEdgeRingTool": "insertLoopTool", "MultiCutTool": "multiCut",
    "dR_multiCutTool": "multiCut", "DuplicateEdges": "offsetEdgeLoop", "QuadDrawTool": "quadDraw",
    "dR_quadDrawTool": "quadDraw", "SlideEdgeTool": "slideEdge", "MergeVertexTool": "targetWeld",
    "dR_targetWeldTool": "targetWeld", "SetMeshSculptTool": "sculpt",
    "SetMeshSmoothTool": "mayaSmoothTool", "SetMeshRelaxTool": "mayaRelaxTool", "SetMeshGrabTool": "mayaGrabTool",
    "SetMeshPinchTool": "mayaPinchTool", "SetMeshFlattenTool": "mayaFlattenTool", "SetMeshFoamyTool": "mayaFoamyTool",
    "SetMeshImprintTool": "mayaImprintTool", "SetMeshWaxTool": "mayaWaxTool", "SetMeshScrapeTool": "mayaScrapeTool",
    "SetMeshFillTool": "mayaFillTool", "SetMeshKnifeTool": "mayaKnifeTool", "SetMeshSmearTool": "mayaSmearTool",
    "SetMeshBulgeTool": "mayaBulgeTool", "SetMeshFreezeTool": "mayaFreezeTool",
    # Mesh Display
    "ConformPolygonNormals": "conformNormals", "ReversePolygonNormals": "reverse", "PolygonHardenEdge": "hardEdge",
    "PolygonSoftenEdge": "softEdge", "PolygonSoftenHarden": "softHard",
    # UV
    "UVAutomaticProjection": "uvAutomatic", "UVCameraBasedProjection": "uvCamera", "UVCylindricProjection": "uvCylindrical",
    "UVPlanarProjection": "uvPlanar", "UVSphericalProjection": "uvSpherical", "AutoSeamUVs": "uvAutoSeams",
    "CutUVsWithoutHotkey": "uvCut", "SewUVsWithoutHotkey": "uvSew", "TogglePolyUVsCreateShader": "uvChecker",
    # Key / Playback
    "SetKey": "setKey", "DeleteKeys": "deleteKey", "CopyKeys": "copyAnim", "PasteKeys": "pasteAnim",
    "PlaybackToggle": "playPause", "PlaybackForward": "playPause", "NextKey": "nextKey", "PreviousKey": "prevKey",
    "GoToMinFrame": "rangeStart", "GoToMaxFrame": "rangeEnd",
}
# rows Maya builds without a runtime command (marking menus, hotbox): by context and label
LABELS = {
    "*": {"Extrude": "extrude", "Mirror": "mirror", "Toggle Soft Edge Display": "softHardDisplay", "Harden Edge": "hardEdge",
          "Soften Edge": "softEdge", "Toggle Face Normal Display": "faceNormals", "Toggle Vertex Normal Display": "vertexNormals",
          "Toggle Backface Culling": "backfaces", "Smooth Faces": "smooth", "Merge Faces To Center": "mergeCenter",
          "Extrude Face": "extrude", "Bevel Face": "bevel", "Extrude Edge": "extrude", "Extrude Vertex": "extrude",
          "Merge Edges To Center": "mergeCenter", "Merge Border Edges": "merge", "Merge Vertices": "merge",
          "Add Divisions To Edge": None, "Interactive Creation": None},
    "zones": {"Perspective View": "persp", "Side View": "side", "Front View": "front", "Top View": "top",
              "Single Perspective": "single", "Toggle Outliner": "winOutliner", "Outliner": "winOutliner",
              "Graph Editor": "graphEditor", "Hypershade": "winMaterials", "Render View": "renderDialog",
              "Channel Box": "winChannel", "Layer Editor": "layerEditor", "Shelf": "winShelf",
              "Object/Components": "objComp", "Hierarchy": "hierarchy"},
}
# Forge's own commands (no Maya row): placed under a "LOKI" heading at the end of the Maya menu they belong with
EXTRAS = {
    "File": ["saveObj", "-", "close"],
    "Create": [["Polygon Primitives", ["quadsphere"]], ["Make with LOKI", ["draw", "image", "describe", "creature"]]],
    "Select": ["marquee", "paintSelect", ["Every Nth in Loop / Ring", ["everyNth2", "everyNth3", "everyNth4"]]],                             # Select > Preferences (camera-based selection ...) is forge_chrome.js's
    "Modify": ["lastTool", ["Axes", ["worldAxes", "objectAxes", "componentAxes"]], "pivotEdit", "pivotEach", "tweakMode",
               ["Discrete Steps", ["discreteMove", "discreteRotate", "discreteScale"]],
               ["Pivot", ["pivotBottom", "pivotOrigin", "pivotToSelection"]]],
    "Display": ["isolate", "xray", "quadToggle", ["Smooth Mesh Preview", ["smooth1", "smooth2", "smooth3"]],
                ["Display Layers", ["layerAdd", "layerAssign"]]],
    "Windows": [["Workspaces", ["wsModel", "wsSculpt", "wsUv", "wsRetopo", "wsBake", "wsMat", "wsAnim", "wsLevel"]],
                ["Panels", ["winOutliner", "winCreate", "winShelf", "winCreature", "panelModel", "panelMaterials"]],
                ["Menus", ["wheel", "quickMenu"]], ["Layouts", ["layouts", "layoutReset", "hideUI"]],
                ["Settings / Preferences", ["preferences", "hotkeyEditor", "menuSettings"]]],
    "Mesh": ["dynamesh", "meshStats", "mirrorY", "mirrorZ", "sculptModel", "bakeMaps"],
    "Edit Mesh": ["inset", "relax", "deleteComp", "mergeThreshold", ["Flatten (Scale to 0)", ["flattenX", "flattenY", "flattenZ", "flattenNormal"]]],
    "Mesh Tools": ["edgeLoop", "multiCutStep", "retopoFinish", "softSel"],
    "Mesh Display": ["softHardAngle", "softHardDisplay", "faceNormals", "vertexNormals", "normalsBigger", "normalsSmaller"],
    "UV": [["Unfold", ["uvUnfold", "uvLayout"]], ["Automatic", ["uvSmart", "uvAtlas", "uvOptCuts"]], "uvMoveSew", "uvShell"],
    "Key": ["clearKeys", ["Tangents", ["keyLinear", "keySmooth", "keyStep"]],
            ["Mirror Keys", ["mirrorKeysX", "mirrorKeysY", "mirrorKeysZ"]], "animAutoKey", "graphEditor"],
    "Playback": [],
}
# Forge's own menus (Maya has no such menu): the Sculpting and Rendering sets
OWN_MENUS = {
    "Sculpt": ["wsSculpt", "sculptModel", "sculpt", "-", ["Remesh", ["sculptRemesh", "sculptQuadRemesh", "sculptReduce", "dynamesh"]],
               ["Subdivision", ["sculptDivide", "sculptDynamic", "sculptLevelUp", "sculptLevelDown"]],
               ["Masking", ["maskClear", "maskInvert", "maskFill", "maskHideToggle"]], "sculptWheel", "smooth", "-", "sculptExit"],
    "Render": ["renderDialog", "renderPreview", "-", "renderStudio", "bakeMaps"],
    # the Level workspace (forge_level.js) - Unreal-style level editing, Forge's own menu set
    "Level": ["levelWorkspace", "-", "levelPlay", "levelSimulate", "levelStop", "-",
              ["Place Actors", ["placeTerrain", "placeNpcSpawn", "-", "placeEmpty", "placePlayerStart", "placeTriggerBox", "placeCamera", "-",
                                "placePointLight", "placeDirLight", "placeSpotLight"]],
              "-", "levelCheckScripts", "levelSave"],
}
# the menu sets: Maya's F2 Modeling, F4 Animation, F6 Rendering; Sculpting is Forge's own (Maya sculpts with tools)
SETS = {
    "modeling": {"label": "Modeling", "menus": ["Mesh", "Edit Mesh", "Mesh Tools", "Mesh Display", "Curves", "Surfaces", "Deform", "UV", "Generate"]},
    "sculpting": {"label": "Sculpting", "menus": ["Sculpt", "Mesh Tools", "Mesh Display"]},
    "animation": {"label": "Animation", "menus": ["Key", "Playback"]},
    "rendering": {"label": "Rendering", "menus": ["Render"]},
    "level": {"label": "Level", "menus": ["Level"]},
}
MARKING = {"object": "Shift+RMB object", "vertex": "Shift+RMB vertex", "edge": "Shift+RMB edge", "face": "Shift+RMB face",
           "empty": "Shift+RMB default"}
ZONES = {"center": "Hotbox Center", "north": "Hotbox North", "south": "Hotbox South", "east": "Hotbox East", "west": "Hotbox West"}


def forge_ids():
    """Every Forge command id that exists (FORGE_PRO_CMDS keys, read from the sources)."""
    src = "\n".join(p.read_text(encoding="utf-8") for p in (REPO / "app" / "ui").glob("forge*.js") if p.name != OUT_JS.name)
    ids = set(re.findall(r"^\s+(\w+):\s*\[\s*\"", src, re.M))
    ids |= set(re.findall(r"(?:FORGE_PRO_CMDS|\bC)\.(\w+)\s*=\s*\[", src))
    ids |= set(re.findall(r"\badd\(\s*\"(\w+)\"\s*,\s*\"", src))          # forge_uv_editor.js / forge_retopo.js: add("id", "Name", fn)
    ids |= set(re.findall(r"FORGE_PRO_CMDS\[\s*\"(\w+)\"\s*\]\s*=", src))
    ids |= set(re.findall(r"\[\s*\"(ws[A-Z]\w*)\"\s*,\s*\"\w+\"\s*,\s*\"", src))   # the workspaces (forge_uv_editor.js)
    ids |= {"sculptFav%d" % i for i in range(1, 10)}
    return ids


def fid(item, ctx):
    k = item.get("rtc") or item.get("c")
    if k in MAP:
        return MAP[k]
    if item.get("rtc"):
        return None                                  # a Maya command Forge does not have (never matched by its label)
    lab = item.get("label", "")
    for d in (LABELS.get(ctx, {}), LABELS["*"]):
        if lab in d:
            return d[lab]
    return None


def convert(tree, ctx, have, rec, path=""):
    """Maya rows -> Forge entries (only what Forge can run); every row is recorded for the parity doc."""
    out = []
    for it in tree:
        if "div" in it:
            out.append("#" + it["div"] if it["div"] else "-")
            continue
        if "call" in it or "error" in it or not it.get("label"):
            continue
        lab = it["label"]
        if "sub" in it:
            kids = convert(it["sub"], ctx, have, rec, path + lab + " > ")
            if any(isinstance(k, list) or (isinstance(k, str) and k not in ("-",) and not k.startswith("#")) for k in kids):
                out.append([lab, kids])
            continue
        f = fid(it, ctx)
        ok = bool(f and f in have)
        rec.append({"menu": ctx, "path": path + lab, "maya": it.get("rtc") or it.get("c") or "", "forge": f if ok else "",
                    "rp": it.get("rp", "")})
        if ok:
            out.append([f, lab])
    # tidy: no heading / separator with nothing under it
    tidy = []
    for e in out:
        if isinstance(e, str) and (e == "-" or e.startswith("#")):
            while tidy and isinstance(tidy[-1], str) and (tidy[-1] == "-" or tidy[-1].startswith("#")):
                tidy.pop()
            if tidy or e != "-":                      # a heading may open the menu; a separator may not
                tidy.append(e)
            continue
        tidy.append(e)
    while tidy and isinstance(tidy[-1], str) and (tidy[-1] == "-" or tidy[-1].startswith("#")):
        tidy.pop()
    return tidy


def ring_of(tree, ctx, have, rec, title=""):
    """A marking menu: {title, ring: {N: id | sub-menu}, labels: {N: "Maya's label"}, list: [...]}. A wedge that opens a
    sub-menu (Maya's Face Normals, Merge/Collapse Edges ...) holds a marking menu of its own, at its own compass places."""
    ring, labels, rest = {}, {}, []
    for it in tree:
        if it.get("rp"):
            if "sub" in it:
                sub = ring_of(it["sub"], ctx, have, rec, it["label"])
                if sub["ring"] or sub["list"]:
                    ring[it["rp"]] = sub
                    labels[it["rp"]] = it["label"]
                continue
            f = fid(it, ctx)
            rec.append({"menu": ctx, "path": "(%s) %s%s" % (it["rp"], title + " > " if title else "", it["label"]),
                        "maya": it.get("rtc") or "", "forge": f if f in have else "", "rp": it["rp"]})
            if f in have:
                ring[it["rp"]] = f
                labels[it["rp"]] = it["label"]
        else:
            rest.append(it)
    out = {"title": title, "ring": ring, "labels": labels, "list": convert(rest, ctx, have, rec)}
    return out


def dedupe(entries, seen):
    """A command once per menu: Maya's own row (the first) wins, a later row - or a LOKI extra - with the same command
    goes; a sub-menu emptied by that goes too."""
    out = []
    for e in entries:
        if isinstance(e, list) and len(e) == 2 and isinstance(e[1], list):
            kids = dedupe(e[1], seen)
            if any(not isinstance(k, str) or (k != "-" and not k.startswith("#")) for k in kids):
                out.append([e[0], kids])
            continue
        cid = e[0] if isinstance(e, list) else e
        if isinstance(e, str) and (e == "-" or e.startswith("#")):
            out.append(e)
            continue
        if cid in seen:
            continue
        seen.add(cid)
        out.append(e)
    # headings / separators with nothing after them
    tidy = []
    for e in out:
        if isinstance(e, str) and (e == "-" or e.startswith("#")) and tidy and isinstance(tidy[-1], str) and (tidy[-1] == "-" or tidy[-1].startswith("#")):
            tidy[-1] = e
            continue
        tidy.append(e)
    while tidy and isinstance(tidy[-1], str) and (tidy[-1] == "-" or tidy[-1].startswith("#")):
        tidy.pop()
    return tidy


def build():
    lay = json.loads(LAYOUT.read_text(encoding="utf-8"))
    have = forge_ids()
    rec = []
    menus = {}
    for name, tree in lay["menus"].items():
        items = convert(tree, name, have, rec)
        extra = [e for e in EXTRAS.get(name, []) if (isinstance(e, list) or e == "-" or e in have)]
        if extra:
            items = items + ["#LOKI"] + extra
        items = dedupe(items, set())
        if items:                                      # Maya's Curves / Surfaces / Deform / Generate: nothing in Forge yet
            menus[name] = items
    menus.update(OWN_MENUS)
    bar = [m for m in lay["menubar"][:7]]
    sets = {k: {"label": v["label"], "menus": [m for m in v["menus"] if menus.get(m)]} for k, v in SETS.items()}
    marking = {k: ring_of(lay["marking"][v], v, have, rec,
                          {"object": "Mesh tools", "vertex": "Vertex tools", "edge": "Edge tools", "face": "Face tools", "empty": "Create"}[k])
               for k, v in MARKING.items()}
    zones = {}
    for k, v in ZONES.items():
        z = ring_of(lay["marking"][v], "zones", have, rec)
        z["title"] = {"center": "Views", "north": "Layouts", "south": "Editors", "east": "UI Elements", "west": "Selection Masks"}[k]
        z.pop("list", None)
        zones[k] = z
    hot = []
    for h in lay["hotkeys"]:
        if not h.get("ctx") and h.get("press"):
            hot.append(h)
    return {"bar": bar, "sets": sets, "menus": menus, "marking": marking, "zones": zones}, rec, lay


def js_text(data):
    return ("// GENERATED by tools/forge_maya/gen_layout.py from docs/forge/maya2027_layout.json - do not edit by hand.\n"
            "// Forge laid out like Maya 2027 (owner 2026-10-22): the menu bar, the menu sets, every menu in Maya's order with\n"
            "// Maya's labels and section headings, the hotbox zones and the Shift+right-click marking menus at Maya's compass\n"
            "// positions. Only commands Forge has are listed; the rest are in docs/FORGE_MAYA_PARITY.md (\"not yet\").\n"
            "// An entry is [commandId, \"Maya's label\"], \"#Heading\", \"-\", or [\"Submenu\", [entries]].\n"
            "\"use strict\";\n\nconst FORGE_MAYA = " + json.dumps(data, indent=1, ensure_ascii=False) + ";\n")


def md_text(rec, data):
    by = {}
    for r in rec:
        by.setdefault(r["menu"], []).append(r)
    done = sum(1 for r in rec if r["forge"])
    lines = ["# Forge = Maya 2027 - the plan and the record", "",
             "Owner 2026-10-22: \"rework everything so its like that, its almost 1:1 to maya ... place everything exactly like",
             "that, thats how maya works and those are where those functions go\".", "",
             "The `bk_maya` folder the owner pointed to turned out to be BlendKit's asset-library plug-in for Maya (an asset",
             "bar + drag-and-drop placement, GPL-3.0) - it holds no Maya layout. The layout comes from **Maya 2027 itself**,",
             "read from the owner's install by `tools/forge_maya/extract_maya.py` into `docs/forge/maya2027_layout.json` (names,",
             "order, compass positions and keys only - no Autodesk code). `tools/forge_maya/gen_layout.py` turns it into",
             "`app/ui/forge_maya_layout.js`, which Forge's menus, hotbox and marking menus are built from, and writes this file.", "",
             "## The plan", "",
             "1. **Menu bar and menu sets** (done): File Edit Create Select Modify Display Windows, then the set's menus - Modeling",
             "   (F2): Mesh, Edit Mesh, Mesh Tools, Mesh Display, UV (Curves, Surfaces, Deform, Generate when Forge has rows",
             "   for them); Animation (F4): Key, Playback; Rendering (F6): Render; Sculpting (Forge's own). Snap and Symmetry",
             "   live on the status line, as in Maya.",
             "2. **Every menu in Maya's order, with Maya's labels and section headings** (done for every row Forge can run; Forge's",
             "   own extras sit under a *LOKI* heading at the end of the menu they belong with).",
             "3. **Marking menus at Maya's compass positions** (done): Shift+right-click on an object / vertex / edge / face / empty",
             "   space (contextPolyTools*MM); the hotbox's centre, north, south, east and west zones (Hotbox*Menu).",
             "4. **Hotkeys = Maya's defaults** (done for the keys Forge has; see *Hotkeys* below).",
             "5. **Build the missing commands, most-used first** (next): every \"not yet\" row below is a command to write.",
             "   Order: Edit Mesh and Mesh Tools rows, then Mesh, Mesh Display, Select conversions, Modify (Match / Snap Align),",
             "   File (New / Open / Save As / Import), UV, Key / Playback.",
             "6. **Panel menus** (View Shading Lighting Show Renderer Panels) laid out from Maya's panel scripts (next).", "",
             "## Where Forge stands", "",
             "%d of %d Maya rows in the menus, hotbox and marking menus are in Forge (%d%%)." % (done, len(rec), round(100 * done / max(1, len(rec)))), "",
             "| Menu | In Forge | Maya rows |", "| --- | ---: | ---: |"]
    for m, rs in by.items():
        lines.append("| %s | %d | %d |" % (m, sum(1 for r in rs if r["forge"]), len(rs)))
    lines += ["", "## Every row", "", "`✓ id` = Forge's command; `-` = not in Forge yet (a command to build).", ""]
    for m, rs in by.items():
        lines += ["### %s" % m, ""]
        for r in rs:
            lines.append("- %s %s%s" % ("✓ `%s`" % r["forge"] if r["forge"] else "-", r["path"], " (Maya: %s)" % r["maya"] if r["maya"] else ""))
        lines.append("")
    return "\n".join(lines) + "\n"


def main():
    data, rec, _ = build()
    js, md = js_text(data), md_text(rec, data)
    if "--check" in sys.argv:
        stale = [p.name for p, t in ((OUT_JS, js), (OUT_MD, md)) if not p.exists() or p.read_text(encoding="utf-8") != t]
        print("stale: " + ", ".join(stale) if stale else "up to date")
        sys.exit(1 if stale else 0)
    OUT_JS.write_text(js, encoding="utf-8")
    OUT_MD.write_text(md, encoding="utf-8")
    done = sum(1 for r in rec if r["forge"])
    print("%d of %d Maya rows mapped to Forge commands" % (done, len(rec)))


if __name__ == "__main__":
    main()
