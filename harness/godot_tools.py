"""Godot API reference + project-editing tools for Loki.

loki.py imports this and sets WORKSPACE/ROOT before use. The API data is the
engine's own output:  godot --headless --dump-extension-api
"""
from __future__ import annotations

import json
import re
from pathlib import Path

WORKSPACE = Path(".")
ROOT = Path(".")
_CACHE = None


def _dump() -> dict:
    global _CACHE
    if _CACHE is None:
        try:
            _CACHE = json.loads((ROOT / "extension_api.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _CACHE = {}
    return _CACHE


def _classes() -> list:
    api = _dump()
    return list(api.get("classes", [])) + list(api.get("builtin_classes", []))


def _globals() -> tuple:
    api = _dump()
    return list(api.get("global_enums", [])), list(api.get("global_constants", []))


def _enum_text(enum: dict, limit: int = 40) -> str:
    return "%s = %s" % (enum.get("name"), ", ".join(
        "%s=%s" % (v.get("name"), v.get("value")) for v in enum.get("values", [])[:limit]))


def _ready() -> str:
    if not _classes():
        return ("error: no Godot API dump found. Create it once with:  godot --headless "
                "--dump-extension-api  inside the harness folder.")
    return ""


def _type(info) -> str:
    if not isinstance(info, dict):
        return "?"
    if info.get("type") == "enum":
        return "int (enum)"
    return str(info.get("type") or "?")


def _find(name: str):
    wanted = str(name or "").strip().lower()
    for cls in _classes():
        if cls.get("name", "").lower() == wanted:
            return cls
    return None


def _signature(class_name: str, method: dict) -> str:
    parts = ["%s: %s" % (a.get("name", "arg"), _type(a)) for a in method.get("args", [])]
    if method.get("is_vararg"):
        parts.append("...")
    ret = method.get("return_value")
    prefix = "static " if method.get("is_static") else ""
    return "%s%s.%s(%s) -> %s" % (prefix, class_name, method.get("name"), ", ".join(parts),
                                  _type(ret) if ret else "void")


def godot_api(name: str, member: str = "") -> str:
    """Look up the REAL Godot 4 API before calling a Godot method you are unsure of.

    name is a class ('InputMap', 'CharacterBody3D') or 'Class.member'.
    With member, returns that exact signature, property type or enum values.
    """
    problem = _ready()
    if problem:
        return problem
    target = str(name or "").strip()
    member = str(member or "").strip()
    if "." in target and not member:
        target, member = target.split(".", 1)
    cls = _find(target)
    if cls is None:
        # global enums / constants (e.g. Key, KEY_W, PROPERTY_USAGE_DEFAULT)
        enums, constants = _globals()
        for enum in enums:
            if enum.get("name", "").lower() == target.lower():
                return _enum_text(enum)
        for const in constants:
            if const.get("name", "").lower() == target.lower():
                return "%s = %s" % (const.get("name"), const.get("value"))
        for enum in enums:
            for value in enum.get("values", []):
                if value.get("name", "").lower() == target.lower():
                    return "%s = %s   (member of enum %s, usable as %s.%s)" % (
                        value.get("name"), value.get("value"), enum.get("name"),
                        enum.get("name"), value.get("name"))
        near = [c["name"] for c in _classes() if target.lower() in c.get("name", "").lower()][:15]
        return "error: no class or global '%s'. Similar classes: %s" % (target, ", ".join(near) or "none")
    cname = cls["name"]
    if member:
        for method in cls.get("methods", []):
            if method.get("name") == member:
                return _signature(cname, method)
        for prop in cls.get("properties", []):
            if prop.get("name") == member:
                return "%s.%s: %s" % (cname, prop["name"], _type(prop))
        for enum in cls.get("enums", []):
            if enum.get("name") == member:
                return "%s.%s = %s" % (cname, member, ", ".join(
                    "%s=%s" % (v.get("name"), v.get("value")) for v in enum.get("values", [])[:20]))
        return "error: %s has no member '%s'. Methods: %s" % (
            cname, member, ", ".join(sorted(m.get("name", "") for m in cls.get("methods", []))[:60]))
    NL = chr(10)
    lines = ["%s (inherits %s)" % (cname, cls.get("inherits") or "Object")]
    props = cls.get("properties", [])
    if props:
        lines.append("properties: " + ", ".join("%s:%s" % (p.get("name"), _type(p)) for p in props[:45]))
    methods = sorted(m.get("name", "") for m in cls.get("methods", []))
    if methods:
        lines.append("methods: " + ", ".join(methods[:90]))
    signals = cls.get("signals", [])
    if signals:
        lines.append("signals: " + ", ".join(x.get("name", "?") for x in signals[:25]))
    enums = cls.get("enums", [])
    if enums:
        lines.append("enums: " + ", ".join(e.get("name", "?") for e in enums[:25]))
    return NL.join(lines)


def godot_search(query: str) -> str:
    """Search the Godot API by keyword to find the right class or method name."""
    problem = _ready()
    if problem:
        return problem
    needle = str(query or "").strip().lower()
    if not needle:
        return "error: give a search term, e.g. 'input action'"
    class_hits, member_hits = [], []
    for cls in _classes():
        if needle in cls.get("name", "").lower():
            class_hits.append(cls["name"])
        for method in cls.get("methods", []):
            if needle in method.get("name", "").lower() and len(member_hits) < 30:
                member_hits.append("%s.%s" % (cls["name"], method["name"]))
    enums, constants = _globals()
    for enum in enums:
        if needle in enum.get("name", "").lower():
            class_hits.append("enum " + enum["name"])
        for value in enum.get("values", []):
            if needle in value.get("name", "").lower() and len(member_hits) < 30:
                member_hits.append("%s.%s=%s" % (enum["name"], value["name"], value.get("value")))
    for const in constants:
        if needle in const.get("name", "").lower():
            member_hits.append("%s=%s" % (const.get("name"), const.get("value")))
    if not class_hits and not member_hits:
        for word in [w for w in re.split(r"[^a-z0-9]+", needle) if len(w) > 2]:
            for cls in _classes():
                if word in cls.get("name", "").lower() and cls["name"] not in class_hits:
                    class_hits.append(cls["name"])
                for method in cls.get("methods", []):
                    if word in method.get("name", "").lower() and len(member_hits) < 30:
                        member_hits.append("%s.%s" % (cls["name"], method["name"]))
    out = []
    if class_hits:
        out.append("classes: " + ", ".join(class_hits[:25]))
    if member_hits:
        out.append("members: " + ", ".join(member_hits))
    return chr(10).join(out) or "nothing matched '%s'" % query


def _resolve(filename: str) -> Path:
    text = str(filename or "").strip()
    if text.startswith("res://"):
        return WORKSPACE / text[len("res://"):]
    path = Path(text)
    return path if path.is_absolute() else WORKSPACE / text


def _project_file() -> Path:
    return WORKSPACE / "project.godot"


def _key_map() -> dict:
    for enum in _dump().get("global_enums", []):
        if enum.get("name") == "Key":
            return {str(v.get("name", "")).replace("KEY_", "").lower(): v.get("value")
                    for v in enum.get("values", [])}
    return {}


def _event_key(keycode: int) -> str:
    code = str(int(keycode))
    return ('Object(InputEventKey,"resource_local_to_scene":false,"resource_name":"",'
            '"device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,'
            '"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":0,'
            '"physical_keycode":' + code + ',"key_label":0,"unicode":0,"location":0,'
            '"echo":false,"script":null)')


def _event_mouse(button: int) -> str:
    index = str(int(button))
    return ('Object(InputEventMouseButton,"resource_local_to_scene":false,"resource_name":"",'
            '"device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,'
            '"ctrl_pressed":false,"meta_pressed":false,"button_mask":0,'
            '"position":Vector2(0, 0),"global_position":Vector2(0, 0),"factor":1.0,'
            '"button_index":' + index + ',"canceled":false,"pressed":false,'
            '"double_click":false,"script":null)')


def add_input_action(name: str, keys: str, deadzone: float = 0.5) -> str:
    """Register an input action in project.godot so scripts can use
    Input.is_action_pressed("<name>") with no runtime InputMap hacks.

    keys is a comma-separated list, e.g. "W,Up", "Space", "Shift", "mouse_left".
    """
    action = re.sub(r"[^A-Za-z0-9_]", "_", str(name or "").strip())
    if not action:
        return "error: an action name is required"
    keymap = _key_map()
    events = []
    for token in str(keys or "").split(","):
        word = token.strip().lower().replace(" ", "")
        if not word:
            continue
        if word in ("mouse_left", "mouse1", "lmb"):
            events.append(_event_mouse(1))
            continue
        if word in ("mouse_right", "mouse2", "rmb"):
            events.append(_event_mouse(2))
            continue
        code = keymap.get(word, keymap.get("key_" + word))
        if code is None:
            return ("error: unknown key '%s' (%d known). Try a letter, Space, Shift, Ctrl, "
                    "Up, Down, Left, Right, Escape, Enter, or mouse_left." % (token.strip(), len(keymap)))
        events.append(_event_key(code))
    if not events:
        return 'error: give at least one key, e.g. "W,Up"'
    project_file = _project_file()
    text = project_file.read_text(encoding="utf-8") if project_file.exists() else ""
    if re.search(r"^%s\s*=" % re.escape(action), text, re.M):
        return "error: input action '%s' already exists in project.godot" % action
    NL = chr(10)
    entry = "%s={%s\"deadzone\": %s,%s\"events\": [%s]%s}%s" % (
        action, NL, float(deadzone), NL, ", ".join(events), NL, NL)
    if "[input]" in text:
        text = text.replace("[input]", "[input]" + NL + entry, 1)
    else:
        if text and not text.endswith(NL):
            text += NL
        text = text + NL + "[input]" + NL + NL + entry
    project_file.write_text(text, encoding="utf-8")
    return "registered input action '%s' with %d event(s) in project.godot" % (action, len(events))


def read_scene(filename: str) -> str:
    """Show the node tree of a .tscn: names, types, attached scripts, instanced scenes."""
    path = _resolve(str(filename))
    if not path.is_file():
        return "error: no such scene: %s" % filename
    text = path.read_text(encoding="utf-8", errors="replace")
    NL = chr(10)
    ext = {}
    for match in re.finditer(r'\[ext_resource type="([^"]+)"[^]]*path="([^"]+)"[^]]*id="([^"]+)"\]', text):
        ext[match.group(3)] = match.group(2)
    out = []
    for chunk in text.split("[node ")[1:]:
        head, _, body = chunk.partition("]")
        name_match = re.search(r'name="([^"]+)"', head)
        if not name_match:
            continue
        name = name_match.group(1)
        type_match = re.search(r'type="([^"]+)"', head)
        parent_match = re.search(r'parent="([^"]*)"', head)
        inst_match = re.search(r'instance=ExtResource\("([^"]+)"\)', head)
        script_match = re.search(r'script = ExtResource\("([^"]+)"\)', body)
        parent = parent_match.group(1) if parent_match else ""
        full = name if not parent else (name if parent == "." else parent + "/" + name)
        label = "%s [%s]" % (name, type_match.group(1) if type_match else "instance")
        if inst_match:
            label += " instance=" + str(ext.get(inst_match.group(1), "?"))
        elif script_match:
            label += " script=" + str(ext.get(script_match.group(1), "?"))
        out.append("  " * full.count("/") + label)
    if not out:
        return "%s: no nodes found" % filename
    return "%s (%d nodes)%s%s" % (filename, len(out), NL, NL.join(out))


def set_project_setting(name: str, value: str) -> str:
    """Set a project.godot setting, e.g. 'display/window/size/viewport_width' = '1280'."""
    setting = str(name or "").strip()
    if "/" not in setting:
        return "error: use section/key form, e.g. display/window/size/viewport_width"
    section, _, key = setting.rpartition("/")
    raw = str(value).strip()
    if raw.lower() in ("true", "false"):
        literal = raw.lower()
    elif re.fullmatch(r"-?[0-9]+", raw) or re.fullmatch(r"-?[0-9]*[.][0-9]+", raw):
        literal = raw
    else:
        literal = '"' + raw.replace('"', "") + '"'
    project_file = _project_file()
    text = project_file.read_text(encoding="utf-8") if project_file.exists() else ""
    NL = chr(10)
    line = "%s/%s=%s" % (section, key, literal)
    existing = re.search(r"^" + re.escape(setting) + r"=.*$", text, re.M)
    if existing:
        text = text[:existing.start()] + line + text[existing.end():]
    elif ("[" + section + "]") in text:
        text = text.replace("[" + section + "]", "[" + section + "]" + NL + line, 1)
    else:
        if text and not text.endswith(NL):
            text += NL
        text = text + NL + "[" + section + "]" + NL + line + NL
    project_file.write_text(text, encoding="utf-8")
    return "set %s = %s" % (setting, literal)


def add_autoload(name: str, path: str) -> str:
    """Register an autoload singleton, e.g. add_autoload('GameState', 'res://scripts/game_state.gd')."""
    singleton = re.sub(r"[^A-Za-z0-9_]", "_", str(name or "").strip())
    target = str(path or "").strip().lstrip("*")
    if not singleton or not target:
        return "error: need a name and a res:// path"
    project_file = _project_file()
    text = project_file.read_text(encoding="utf-8") if project_file.exists() else ""
    if re.search(r"^%s\s*=" % re.escape(singleton), text, re.M):
        return "error: autoload '%s' already exists" % singleton
    NL = chr(10)
    entry = '"%s"="*%s"' % (singleton, target)
    if "[autoload]" in text:
        text = text.replace("[autoload]", "[autoload]" + NL + entry, 1)
    else:
        if text and not text.endswith(NL):
            text += NL
        text = text + NL + "[autoload]" + NL + entry + NL
    project_file.write_text(text, encoding="utf-8")
    return "registered autoload %s -> %s" % (singleton, target)
