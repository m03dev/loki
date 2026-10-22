"""Maya's layout, read from a Maya install: every Modeling-set menu, the hotbox zones, the marking menus (with their
compass positions) and the default hotkeys - as a tree of LABELS, in order (dividers with their labels, sub-menus,
option boxes, the runtime command's name). Owner 2026-10-22: Forge must be laid out "almost 1:1 to maya".

Reference only: it reads Autodesk's own startup scripts and MayaStrings on the owner's machine and writes NAMES,
ORDER, POSITIONS and KEYS to docs/forge/maya2027_layout.json - no Autodesk code is copied into LOKI.

    python tools/forge_maya/extract_maya.py "D:/Maya2027"            (Windows)
    python tools/forge_maya/extract_maya.py /Applications/Autodesk/maya2027/Maya.app/Contents   (macOS)
Then: python tools/forge_maya/gen_layout.py   (Forge's menus from it; docs/FORGE_MAYA_PARITY.md)
"""
import json
import os
import re
import sys
from pathlib import Path

M = Path(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else os.environ.get("MAYA_LOCATION", "D:/Maya2027"))
S = {}
for line in (M / "resources" / "MayaStrings").read_text(encoding="utf-8", errors="replace").splitlines():
    m = re.match(r'(\S+)\s*=\s*"(.*)"\s*$', line)
    if m:
        S[m.group(1)] = m.group(2).replace('\\"', '"')


RTC = {}
_src = (M / "scripts" / "startup" / "defaultRunTimeCommands.mel").read_text(encoding="utf-8", errors="replace")
for blk in re.split(r"runTimeCommand\s", _src)[1:]:
    body = blk.split(";", 1)[0] if False else blk
    m = re.search(r"\)\s*\n?\s*(\w+)\s*;", blk[:6000])
    lab = re.search(r'-label\s*\(?\s*uiRes\(\s*"([^"]+)"', blk[:3000])
    name = None
    # the command name is the last bare word before the first ; that ends the runTimeCommand statement
    end = re.search(r"\n\s*(\w+)\s*;", blk)
    if end and lab:
        RTC[end.group(1)] = S.get(lab.group(1), lab.group(1))


def label_of(expr, rtc):
    if expr:
        m = re.search(r'uiRes\(\s*"([^"]+)"\s*\)', expr)
        if m:
            return S.get(m.group(1), m.group(1))
        m = re.search(r'localized\w+\(\s*"([^"]*)"\s*\)', expr)
        if m:
            return m.group(1)
        m = re.match(r'\s*"([^"]*)"', expr)
        if m:
            return m.group(1)
        return expr.strip()
    if rtc:
        return RTC.get(rtc) or S.get("m_defaultRunTimeCommands.k%sLbl" % rtc, rtc)
    return ""


def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def statements(src):
    """Split on ; outside strings/backticks/parens."""
    out, cur, depth, q = [], [], 0, None
    for ch in src:
        if q:
            cur.append(ch)
            if ch == q:
                q = None
            continue
        if ch in "{}" and depth == 0:
            if "".join(cur).strip():
                out.append("".join(cur).strip())
            cur = []
            continue
        if ch in "\"`":
            q = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch == ";" and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        elif ch in "{}" and depth == 0:
            if "".join(cur).strip():
                out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return out


def flag(stmt, *names):
    for n in names:
        m = re.search(r"\s-%s\s+(`[^`]*`|\([^;]*?\)\)|\([^;]*?\)|\"[^\"]*\"|\$\w+|\S+)" % re.escape(n), " " + stmt)
        if m:
            return m.group(1)
    return None


PARAMS = {}


def procs_of(src):
    out = {}
    for m in re.finditer(r"(?:global\s+)?proc\s+(?:[\w\[\]]+\s+)?(\w+)\s*\(([^)]*)\)", src):
        PARAMS[m.group(1)] = re.findall(r"\$(\w+)", m.group(2))
        i = src.find("{", m.end())
        if i < 0:
            continue
        d, j = 0, i
        while j < len(src):
            if src[j] == "{":
                d += 1
            elif src[j] == "}":
                d -= 1
                if d == 0:
                    break
            j += 1
        out[m.group(1)] = src[i + 1:j]
    return out


def parse(src, entry=None, _procs=None, _depth=0):
    src = strip_comments(src)
    procs = _procs if _procs is not None else procs_of(src)
    if entry and entry in procs:
        src = procs[entry]
        entry = None
    if entry:   # only the body of one proc
        m = re.search(r"global\s+proc\s+[\w\[\]]*\s*%s\s*\(" % re.escape(entry), src)
        if m:
            i = src.index("{", m.end())
            d, j = 0, i
            while j < len(src):
                if src[j] == "{":
                    d += 1
                elif src[j] == "}":
                    d -= 1
                    if d == 0:
                        break
                j += 1
            src = src[i + 1:j]
    vars_ = {}
    root = []
    stack = [root]
    labvars = {}
    for st in statements(src):
        m = re.match(r"(?:string\s+)?\$(\w+)\s*=\s*\"([^\"]*)\"$", st)
        if m:
            vars_[m.group(1)] = m.group(2)
            continue
        m = re.match(r"(?:string\s+)?\$(\w+)\s*=\s*`runTimeCommand\s+-q\s+-l(?:abel)?\s+\$(\w+)\s*`$", st)
        if m:
            labvars[m.group(1)] = RTC.get(vars_.get(m.group(2), ""), vars_.get(m.group(2), ""))
            continue
        m = re.match(r"(?:string\s+)?\$(\w+)\s*=\s*\(?\s*uiRes\(\s*\"([^\"]+)\"\s*\)\s*\)?$", st)
        if m:
            labvars[m.group(1)] = S.get(m.group(2), m.group(2))
            continue
        m = re.match(r"(?:string\s+)?\$\w+\s*=\s*`(menuItem\b.*)`$", st, re.S)
        if m:
            st = m.group(1)
        if re.match(r"setParent\s+(-m(enu)?\s+)?\.\.", st) or re.match(r"setParent\s+-m(enu)?\s+\.\.", st):
            if len(stack) > 1:
                stack.pop()
            continue
        if re.match(r"setParent\s+-m(enu)?\s+\$(parent|\w*[Mm]enu\w*)\s*$", st) and _depth == 0:
            del stack[1:]
            continue
        if not re.match(r"menuItem\b", st):
            mc = re.match(r"(\w+)\s*(\(|\s|$)", st)
            if mc and mc.group(1) in procs and _depth < 6 and mc.group(1) not in ("if", "for", "while", "string", "int"):
                body = procs[mc.group(1)]
                rest = st[len(mc.group(1)):].strip()
                if rest.startswith("(") and rest.endswith(")"):
                    rest = rest[1:-1]
                    args, cur, d, q = [], "", 0, None
                    for ch in rest:
                        if q:
                            cur += ch
                            if ch == q: q = None
                            continue
                        if ch == '"': q = ch
                        if ch == "(": d += 1
                        if ch == ")": d -= 1
                        if ch == "," and d == 0:
                            args.append(cur.strip()); cur = ""
                        else:
                            cur += ch
                    if cur.strip(): args.append(cur.strip())
                else:
                    args = re.findall(r'"[^"]*"|\S+', rest)
                for pn, av in zip(PARAMS.get(mc.group(1), []), args):
                    av = av.strip()
                    if av.startswith("$") and av[1:] in vars_:
                        av = '"%s"' % vars_[av[1:]]
                    body = re.sub(r"\$%s\b" % re.escape(pn), lambda _m, a=av: a, body)
                stack[-1].extend(parse(body, None, procs, _depth + 1))
                continue
            m = re.match(r"(\w+Menu|\w+SubMenu)\s+\S", st)
            if m and m.group(1) not in ("setParent",):
                stack[-1].append({"call": m.group(1)})
            continue
        bare = re.sub(r"`[^`]*`", "``", st)
        if re.search(r"\s-(e|edit|q|query|ex|exists)\b", " " + bare):
            continue
        rtc = flag(st, "rtc", "runTimeCommand")
        if rtc and rtc.startswith("$"):
            rtc = vars_.get(rtc[1:], rtc)
        rtc = rtc.strip('()" ') if rtc else None
        cmd = flag(st, "c", "command")
        if cmd:
            cv = re.match(r"\(?\s*\$(\w+)\s*\)?$", cmd.strip())
            if cv:
                cmd = vars_.get(cv.group(1), cmd)
            cq = re.match(r'\(\s*"(\w+)"\s*\)$', cmd.strip())
            if cq:
                cmd = cq.group(1)
        lab_expr = flag(st, "label", "l")
        if lab_expr and lab_expr.startswith("`runTimeCommand"):
            mv = re.search(r'-l(?:abel)?\s+"?(\$?\w+)"?\s*`', lab_expr)
            rc = (vars_.get(mv.group(1)[1:]) if mv.group(1).startswith("$") else mv.group(1)) if mv else None
            if rc:
                rtc = rtc or rc
            lab_expr = None
        if re.search(r"\s-(d|divider)\s+(true|1)", " " + st):
            stack[-1].append({"div": label_of(flag(st, "dividerLabel", "dl"), None)})
            continue
        if re.search(r"\s-(ob|optionBox)\s+(true|1)", " " + st):
            if stack[-1]:
                stack[-1][-1]["opt"] = True
            continue
        if lab_expr:
            lv = re.match(r"\(?\s*\$(\w+)\s*\)?$", lab_expr.strip())
            if lv and lv.group(1) in labvars:
                lab_expr = '"%s"' % labvars[lv.group(1)]
        item = {"label": label_of(lab_expr, rtc or (cmd if cmd and re.match(r"^\w+$", cmd) else None))}
        rp = flag(st, "rp", "radialPosition")
        if rp:
            item["rp"] = rp.strip('"')
        if rtc:
            item["rtc"] = rtc
        elif cmd and re.match(r'^"?\w+"?$', cmd.strip()):
            item["c"] = cmd.strip('"')
        if re.search(r"\s-(sm|subMenu)\s+(true|1)", " " + st):
            item["sub"] = []
            stack[-1].append(item)
            stack.append(item["sub"])
            continue
        if re.search(r"\s-(cb|checkBox)\s", " " + st):
            item["check"] = True
        if re.search(r"\s-(rb|radioButton)\s", " " + st):
            item["radio"] = True
        prev = stack[-1][-1] if stack[-1] else None
        if prev and prev.get("label") == item["label"] and prev.get("rtc") == item.get("rtc") and "sub" not in prev:
            continue                       # the same row from an if / else branch
        stack[-1].append(item)
    return root


def show(tree, ind=0, out=None):
    out = out if out is not None else []
    for it in tree:
        pad = "  " * ind
        if "div" in it:
            out.append(pad + ("-- " + it["div"] + " --" if it["div"] else "--"))
        elif "call" in it:
            out.append(pad + "[built by " + it["call"] + "]")
        else:
            out.append(pad + ("(" + it["rp"] + ") " if it.get("rp") else "") + it["label"] + (" [opt]" if it.get("opt") else "") + (" >" if "sub" in it else "")
                       + ("  {" + it.get("rtc", it.get("c", "")) + "}" if it.get("rtc") or it.get("c") else ""))
            if "sub" in it:
                show(it["sub"], ind + 1, out)
    return out




def main():
    MENUS = [("File","FileMenu.mel","buildFileMenu"),("Edit","buildEditMenu.mel","buildEditMenu"),("Create","ModCreateMenu.mel","ModCreateMenu"),
     ("Select","buildSelectMenu.mel","buildSelectMenu"),("Modify","ModObjectsMenu.mel","ModObjectsMenu"),("Display","buildDisplayMenu.mel","buildDisplayMenu"),
     ("Windows","WindowMenu.mel","buildDeferredWindowMenu"),("Mesh","PolygonsMeshMenu.mel","PolygonsMeshMenu"),("Edit Mesh","PolygonsBuildMenu.mel","PolygonsBuildMenu"),
     ("Mesh Tools","PolygonsBuildToolsMenu.mel","PolygonsBuildToolsMenu"),("Mesh Display","ModelingMeshDisplayMenu.mel","ModelingMeshDisplayMenu"),
     ("Curves","ModelingCurvesMenu.mel","ModelingCurvesMenu"),("Surfaces","ModelingSurfacesMenu.mel","ModelingSurfacesMenu"),("Deform","ChaDeformationsMenu.mel","ChaDeformationsMenu"),
     ("UV","ModelingUVMenu.mel","ModelingUVMenu"),("Generate","ModelingGenerateMenu.mel","ModelingGenerateMenu"),
     ("Key","AniKeyMenu.mel","AniKeyMenu"),("Playback","AniPlaybackMenu.mel","AniPlaybackMenu")]
    ref = {"menubar": [m[0] for m in MENUS[:16]], "menus": {}, "marking": {}, "hotkeys": []}
    for name, f, p in MENUS:
        ref["menus"][name] = parse((M / "scripts/startup" / f).read_text(encoding="utf-8", errors="replace"), p)
    # sub-menus Maya fills when they open (postMenuCommand): Display > Hide / Show
    disp_src = (M / "scripts/startup/buildDisplayMenu.mel").read_text(encoding="utf-8", errors="replace")
    for it in ref["menus"]["Display"]:
        if it.get("sub") == [] and it.get("label") in ("Hide", "Show"):
            it["sub"] = parse(disp_src, "build%sSubmenu" % it["label"])
    for name, f, p in [("Hotbox North","HotboxNorthMenu.mel","HotboxNorthMenu"),("Hotbox South","HotboxSouthMenu.mel","HotboxSouthMenu"),
       ("Hotbox East","HotboxEastMenu.mel","HotboxEastMenu"),("Hotbox West","HotboxWestMenu.mel","HotboxWestMenu"),("Hotbox Center","HotboxCenterMenu.mel","HotboxCenterMenu"),
       ("Object RMB (dagMenuProc)","../others/dagMenuProc.mel","createSelectMenuItems"),("Shift+RMB poly tools","../others/contextPolyToolsMM.mel","contextPolyToolsMM"),
       ("Shift+RMB object","../others/contextPolyToolsObjectMM.mel","contextPolyToolsObjectMM"),("Shift+RMB vertex","../others/contextPolyToolsVertexMM.mel","contextPolyToolsVertexMM"),
       ("Shift+RMB edge","../others/contextPolyToolsEdgeMM.mel","contextPolyToolsEdgeMM"),("Shift+RMB face","../others/contextPolyToolsFaceMM.mel","contextPolyToolsFaceMM"),
       ("Shift+RMB default","../others/contextPolyToolsDefaultMM.mel","contextPolyToolsDefaultMM"),("Ctrl+RMB select comp","buildSelectComponentMM.mel","buildSelectComponentMM"),
       ("Ctrl+RMB select object","buildSelectObjectMM.mel","buildSelectObjectMM"),("w marking","../others/buildTranslateMM.mel","buildTranslateMM"),
       ("e marking","../others/buildRotateMM.mel","buildRotateMM"),("r marking","../others/buildScaleMM.mel","buildScaleMM"),("q marking","../others/buildSelectMM.mel","buildSelectMM")]:
        try:
            ref["marking"][name] = parse((M / "scripts" / ("others/" + f[10:] if f.startswith("../others/") else "startup/" + f)).read_text(encoding="utf-8", errors="replace"), p)
        except Exception as exc:
            ref["marking"][name] = [{"error": str(exc)}]
    src = (M / "scripts/startup/hotkeySetup.mel").read_text(encoding="utf-8", errors="replace")
    ctx = ""
    for line in strip_comments(src).splitlines():
        c = re.match(r'\s*hotkeyCtx\s.*-t(?:ype)?\s+"(\w+)".*-c(?:lient)?\s+"(\w+)"', line)
        if c: ctx = c.group(2)
        m = re.match(r'\s*hotkey\s+(.*);', line)
        if not m: continue
        a = m.group(1)
        k = re.search(r'-k(?:eyShortcut)?\s+"([^"]+)"', a)
        if not k: continue
        key = k.group(1)
        mods = [x for x in ("ctl", "alt", "cmd", "sht") if re.search(r"\s-%s\b" % x, " " + a)]
        nm = re.search(r'-(?:n|name)\s+"([^"]*)"', a); rn = re.search(r'-(?:rn|releaseName)\s+"([^"]*)"', a)
        ref["hotkeys"].append({"key": key, "mods": mods, "press": nm.group(1) if nm else "", "release": rn.group(1) if rn else "",
                               "ctx": re.search(r'-ctx\s+"(\w+)"', a).group(1) if re.search(r'-ctx\s+"(\w+)"', a) else ""})
    OUT = Path(__file__).resolve().parents[2] / "docs" / "forge" / "maya2027_layout.json"
    ref["source"] = "Maya 2027 (%s): scripts/startup + scripts/others + resources/MayaStrings, read by tools/forge_maya/extract_maya.py" % M.name
    OUT.write_text(json.dumps(ref, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print({k: len(v) for k, v in ref["menus"].items()}); print({k: len(v) for k, v in ref["marking"].items()}); print(len(ref["hotkeys"]))


if __name__ == "__main__":
    main()
