"""Put a Godot add-on into a project and switch it on (the Tool Shelf's Godot tools: godot-ai, GUT, gdUnit4 ...).

    python godot_addon.py <addon folder (the one with plugin.cfg)> <project folder (the one with project.godot)> [--no-enable]

Copies the folder to <project>/addons/<its name>/ - never over an existing copy (update those from the add-on's own
Update button, the way their authors ask) - and adds res://addons/<name>/plugin.cfg to [editor_plugins] enabled= in
project.godot. Prints one JSON line.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path


def enable(project: Path, name: str) -> bool:
    cfg = project / "project.godot"
    text = cfg.read_text(encoding="utf-8")
    entry = '"res://addons/%s/plugin.cfg"' % name
    if entry in text:
        return False
    m = re.search(r"^enabled=PackedStringArray\((.*)\)\s*$", text, re.M)
    if m:
        inner = m.group(1).strip()
        new = "enabled=PackedStringArray(%s)" % ((inner + ", " if inner else "") + entry)
        text = text[:m.start()] + new + text[m.end():]
    elif re.search(r"^\[editor_plugins\]\s*$", text, re.M):
        text = re.sub(r"^\[editor_plugins\]\s*$", "[editor_plugins]\n\nenabled=PackedStringArray(%s)" % entry, text,
                      count=1, flags=re.M)
    else:
        text = text.rstrip("\n") + "\n\n[editor_plugins]\n\nenabled=PackedStringArray(%s)\n" % entry
    cfg.write_text(text, encoding="utf-8")
    return True


def main(argv: list) -> dict:
    if len(argv) < 2:
        return {"ok": False, "error": __doc__.strip().splitlines()[2]}
    src, project = Path(argv[0]).resolve(), Path(argv[1]).resolve()
    if not (project / "project.godot").is_file():
        return {"ok": False, "error": "%s is not a Godot project (no project.godot)" % project}
    if not src.is_dir():
        return {"ok": False, "error": "no add-on folder at %s" % src}
    name = src.name
    dest = project / "addons" / name
    copied = False
    if dest.exists():
        note = "already there - update it from the add-on's own Update button"
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest)
        copied, note = True, "copied"
    enabled = False
    if "--no-enable" not in argv and (dest / "plugin.cfg").is_file():
        enabled = enable(project, name)
    return {"ok": True, "addon": name, "path": str(dest), "copied": copied, "enabled_now": enabled, "note": note}


if __name__ == "__main__":
    out = main(sys.argv[1:])
    print(json.dumps(out))
    sys.exit(0 if out.get("ok") else 1)
