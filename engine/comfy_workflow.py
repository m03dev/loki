"""ComfyUI workflows as LOKI uses them: the UI format (what ComfyUI saves and what Comfy-Org's templates are) -> the API
format (what POST /prompt takes), and the small graph edits LOKI makes before queueing one.

    ui_to_api(ui, info, drop=..., replace=...)   UI -> API. `info` is /object_info (or a fixture of it): its
                                                 input_order says which input each widgets_values entry belongs to.
                                                 A widget is an INT / FLOAT / STRING / BOOLEAN / COMBO / COLOR / a
                                                 list of choices, a DynamicCombo (its chosen option's own widgets
                                                 follow it, sent as "<name>.<sub>"), or any input the UI marks as a
                                                 widget. A seed with control_after_generate has one extra slot
                                                 ("fixed" / "randomize"), an upload widget too; both skipped. A linked widget sends the
                                                 link; a node whose widget count does not match is an error, never a
                                                 guess.
    resolve_switches(api)                        a ComfySwitchNode whose switch is known now (a value, or a
                                                 PrimitiveBoolean) is removed: its users take the chosen side directly
    prune(api, keep)                             only the nodes the outputs `keep` need
    loaders(api)                                 [(node, class, input, file)] - the model files a graph needs
    check_models(api, info)                      the ones this ComfyUI does not list (its loader's choices)
    missing_nodes(api, info)                     node classes this ComfyUI does not have (too old: update it)
Standard library only.
"""
from __future__ import annotations

import copy

WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO", "COLOR", "LOAD3D", "COMFY_DYNAMICCOMBO_V3"}
UI_ONLY = ("Note", "MarkdownNote", "Reroute", "PrimitiveNode")   # never sent to the server
# loader class -> (its file input, the models/ folder it reads)
LOADERS = {
    "UNETLoader": ("unet_name", "diffusion_models"),
    "VAELoader": ("vae_name", "vae"),
    "CLIPVisionLoader": ("clip_name", "clip_vision"),
    "CLIPLoader": ("clip_name", "text_encoders"),
    "CheckpointLoaderSimple": ("ckpt_name", "checkpoints"),
    "LoraLoader": ("lora_name", "loras"),
    "LoraLoaderModelOnly": ("lora_name", "loras"),
    "UpscaleModelLoader": ("model_name", "upscale_models"),
    "LoadMoGeModel": ("model_name", "geometry_estimation"),
    "LoadBackgroundRemovalModel": ("bg_removal_name", "background_removal"),
    "DualCLIPLoader": (("clip_name1", "clip_name2"), "text_encoders"),
}


class WorkflowError(ValueError):
    pass


def _is_widget(spec) -> bool:
    if not isinstance(spec, (list, tuple)) or not spec:
        return False
    t = spec[0]
    return isinstance(t, list) or (isinstance(t, str) and t.upper() in WIDGET_TYPES)


def _extra_slot(spec) -> bool:
    opts = spec[1] if isinstance(spec, (list, tuple)) and len(spec) > 1 and isinstance(spec[1], dict) else {}
    # the seed's "fixed" / "randomize", LoadImage's upload button: one more saved value, not an input
    return bool(opts.get("control_after_generate")) or any(k.endswith("_upload") and v for k, v in opts.items())


def _ordered(info_node: dict) -> list:
    """[(name, spec)] in the node's widget order: required, then optional."""
    inp = info_node.get("input") or {}
    order = info_node.get("input_order") or {}
    out = []
    for part in ("required", "optional"):
        specs = inp.get(part) or {}
        for name in (order.get(part) or list(specs)):
            if name in specs:
                out.append((name, specs[name]))
    return out


def _take_widgets(specs: list, values: list, pos: int, ui_widget_names: set, prefix: str = "") -> tuple:
    """Assign widgets_values[pos:] to the widget inputs in `specs`; returns ({name: value}, new pos)."""
    got = {}
    for name, spec in specs:
        if not (_is_widget(spec) or name in ui_widget_names):
            continue
        if pos >= len(values):
            raise WorkflowError("ran out of widget values at %s%s" % (prefix, name))
        got[prefix + name] = values[pos]
        pos += 1
        if _extra_slot(spec):
            pos += 1
        if isinstance(spec[0], str) and spec[0].upper() == "COMFY_DYNAMICCOMBO_V3":
            chosen = got[prefix + name]
            for opt in (spec[1] or {}).get("options") or []:
                if opt.get("key") == chosen:
                    sub = list(((opt.get("inputs") or {}).get("required") or {}).items())
                    sub += list(((opt.get("inputs") or {}).get("optional") or {}).items())
                    more, pos = _take_widgets(sub, values, pos, set(), prefix + name + ".")
                    got.update(more)
                    break
    return got, pos


def ui_to_api(ui: dict, info: dict, drop=(), replace: dict | None = None) -> dict:
    """The UI-format workflow `ui` as an API prompt. `drop`: node types left out (with UI_ONLY). `replace`: {node id:
    (new class, {input: value or None for 'the link this node had on its first input'})} - also for a dropped node,
    so a node the server could not take (a crop with a UI-only widget) can be swapped for another under the same id."""
    drop = set(UI_ONLY) | set(drop or ())
    links = {}
    for ln in ui.get("links") or []:
        if isinstance(ln, dict):
            links[ln["id"]] = (str(ln["origin_id"]), int(ln["origin_slot"]))
        else:
            links[ln[0]] = (str(ln[1]), int(ln[2]))
    api = {}
    types = {str(n["id"]): n.get("type") for n in ui.get("nodes") or []}
    for node in ui.get("nodes") or []:
        nid, cls = str(node["id"]), node.get("type")
        if cls in drop or node.get("mode") in (2, 4):      # 2 = muted, 4 = bypassed: not run
            continue
        if cls not in info:
            raise WorkflowError("node %s: %s is not in object_info" % (nid, cls))
        ins = node.get("inputs") or []
        ui_widgets = {i["name"] for i in ins if i.get("widget")}
        values = node.get("widgets_values")
        if isinstance(values, dict):                    # some nodes save {name: value}
            inputs = dict(values)
        else:
            values = list(values or [])
            inputs, used = _take_widgets(_ordered(info[cls]), values, 0, ui_widgets)
            if used != len(values):
                raise WorkflowError("node %s (%s): %d widget values but the node takes %d" % (nid, cls, len(values), used))
        for i in ins:
            if i.get("link") is not None and i["link"] in links:
                src, slot = links[i["link"]]
                if types.get(src) in drop and i["name"] in inputs:
                    continue          # a UI-only PrimitiveNode feeds this widget: its value is already in the widget
                inputs[i["name"]] = [src, slot]
        api[nid] = {"class_type": cls, "inputs": inputs, "_meta": {"title": node.get("title") or cls}}
    for nid, (cls, new_inputs) in (replace or {}).items():
        old = api.get(str(nid))
        if old is None and any(n.get("id") == int(nid) or str(n.get("id")) == str(nid) for n in ui.get("nodes") or []):
            old = {"inputs": {}}                        # a dropped node put back as something else (same id)
        if old is None:
            continue
        first_link = next((v for v in old["inputs"].values() if isinstance(v, list)), None)
        api[str(nid)] = {"class_type": cls, "_meta": {"title": cls},
                         "inputs": {k: (first_link if v is None else v) for k, v in new_inputs.items()}}
    for nid, node in api.items():                       # a link to a dropped node is dropped too
        for k, v in list(node["inputs"].items()):
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] not in api:
                del node["inputs"][k]
    return api


def _is_link(v) -> bool:
    return isinstance(v, list) and len(v) == 2 and isinstance(v[0], str)


def resolve_switches(api: dict) -> dict:
    """Remove every ComfySwitchNode whose switch is known: its users link to the side it picks."""
    api = copy.deepcopy(api)
    changed = True
    while changed:
        changed = False
        for nid, node in list(api.items()):
            if node["class_type"] != "ComfySwitchNode":
                continue
            sw = node["inputs"].get("switch")
            if _is_link(sw):
                src = api.get(sw[0]) or {}
                if src.get("class_type") != "PrimitiveBoolean" or _is_link(src["inputs"].get("value")):
                    continue
                sw = src["inputs"].get("value")
            chosen = node["inputs"].get("on_true" if sw else "on_false")
            for other in api.values():
                for k, v in list(other["inputs"].items()):
                    if _is_link(v) and v[0] == nid:
                        if chosen is None:
                            del other["inputs"][k]
                        else:
                            other["inputs"][k] = list(chosen)
            del api[nid]
            changed = True
    return api


def prune(api: dict, keep) -> dict:
    """Only the nodes in `keep` and everything they need."""
    want, todo = set(), [str(k) for k in keep]
    while todo:
        nid = todo.pop()
        if nid in want or nid not in api:
            continue
        want.add(nid)
        todo += [v[0] for v in api[nid]["inputs"].values() if _is_link(v)]
    return {k: copy.deepcopy(v) for k, v in api.items() if k in want}


def loaders(api: dict) -> list:
    out = []
    for nid, node in api.items():
        spec = LOADERS.get(node["class_type"])
        if not spec:
            continue
        for inp in (spec[0] if isinstance(spec[0], tuple) else (spec[0],)):
            if isinstance(node["inputs"].get(inp), str):
                out.append((nid, node["class_type"], inp, node["inputs"][inp], spec[1]))
    return out


def missing_nodes(api: dict, info: dict) -> list:
    return sorted({n["class_type"] for n in api.values() if n["class_type"] not in info})


def check_models(api: dict, info: dict) -> list:
    """[{node, file, folder}] for the model files this server's loaders do not list."""
    missing = []
    for nid, cls, inp, name, folder in loaders(api):
        spec = (((info.get(cls) or {}).get("input") or {}).get("required") or {}).get(inp)
        choices = spec[0] if isinstance(spec, (list, tuple)) and spec else None
        if isinstance(spec, (list, tuple)) and len(spec) > 1 and spec[0] == "COMBO":
            choices = (spec[1] or {}).get("options")
        if isinstance(choices, list) and name not in choices:
            missing.append({"node": nid, "file": name, "folder": folder})
    return missing
