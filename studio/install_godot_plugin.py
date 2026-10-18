"""Put the LOKI Studio plugin into any Godot 4 project and turn it on.

    python studio/install_godot_plugin.py <path to the Godot project>          install / update
    python studio/install_godot_plugin.py <path> --remove                      take it out again

It copies studio/godot_plugin/addons/loki_studio/ to <project>/addons/loki_studio/ (replacing an
older copy of it, nothing else) and adds it to [editor_plugins] in project.godot. Open the project in
Godot: the LOKI Studio dock appears on the right and connects to Studio by itself. Works on macOS
and Windows (pathlib, no shell).
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "godot_plugin" / "addons" / "loki_studio"
PLUGIN_CFG = "res://addons/loki_studio/plugin.cfg"


def enable_in_project(text: str, enable: bool = True) -> str:
    """project.godot text with the plugin in (or out of) [editor_plugins] enabled=PackedStringArray(...)."""
    nl = "\r\n" if "\r\n" in text else "\n"
    m = re.search(r"^\[editor_plugins\][ \t]*$", text, re.M)
    if not m:
        if not enable:
            return text
        return text.rstrip() + nl + nl + "[editor_plugins]" + nl + nl + 'enabled=PackedStringArray("%s")' % PLUGIN_CFG + nl
    sec_end = re.search(r"^\[", text[m.end():], re.M)
    body_end = m.end() + (sec_end.start() if sec_end else len(text) - m.end())
    body = text[m.end():body_end]
    em = re.search(r'^enabled=PackedStringArray\((.*?)\)[ \t\r]*$', body, re.M)
    items = re.findall(r'"([^"]+)"', em.group(1)) if em else []
    items = [i for i in items if i != PLUGIN_CFG] + ([PLUGIN_CFG] if enable else [])
    line = "enabled=PackedStringArray(%s)" % ", ".join('"%s"' % i for i in items)
    if em:
        body = body[:em.start()] + line + body[em.end():]
    else:
        body = nl + line + body if body.startswith(nl) else nl + line + nl + body
    return text[:m.end()] + body + text[body_end:]


AUTOLOAD_LINE = 'LokiStudioGame="*res://addons/loki_studio/game_bridge.gd"'


def autoload_in_project(text: str, enable: bool = True) -> str:
    """The game bridge autoload in (or out of) [autoload] - the plugin also adds it itself when enabled in the editor."""
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = [line for line in text.split(nl) if not line.startswith("LokiStudioGame=")]
    text = nl.join(lines)
    if not enable:
        return text
    m = re.search(r"^\[autoload\][ \t\r]*$", text, re.M)
    if m:
        return text[:m.end()] + nl + AUTOLOAD_LINE + text[m.end():]
    return text.rstrip() + nl + nl + "[autoload]" + nl + nl + AUTOLOAD_LINE + nl


def install(project: Path, remove: bool = False) -> dict:
    project = Path(project).expanduser().resolve()
    cfg = project / "project.godot"
    if not cfg.is_file():
        return {"ok": False, "error": "%s is not a Godot project (no project.godot)" % project}
    target = project / "addons" / "loki_studio"
    if remove:
        if target.is_dir():
            shutil.rmtree(target)
    else:
        if not (SOURCE / "plugin.cfg").is_file():
            return {"ok": False, "error": "the plugin is missing from this LOKI copy (%s)" % SOURCE}
        if target.resolve() == SOURCE.resolve():
            return {"ok": False, "error": "that is the plugin's own source folder"}
        if target.is_dir():
            shutil.rmtree(target)
        shutil.copytree(SOURCE, target, ignore=shutil.ignore_patterns("*.uid", "*.import", "__pycache__"))
    raw = cfg.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw                    # Windows-edited project files keep their line ends
    new = autoload_in_project(enable_in_project(raw.replace("\r\n", "\n"), enable=not remove), enable=not remove)
    if crlf:
        new = new.replace("\n", "\r\n")
    if new != raw:
        cfg.write_bytes(new.encode("utf-8"))
    files = sorted(p.relative_to(project).as_posix() for p in target.rglob("*") if p.is_file()) if not remove else []
    return {"ok": True, "project": str(project), "removed" if remove else "installed": str(target), "files": files,
            "note": "Open the project in Godot: the LOKI Studio dock connects to Studio by itself."
            if not remove else "The plugin is out of the project."}


def main(argv: list | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    res = install(Path(args[0]), remove="--remove" in args)
    print(res.get("note") or res.get("error"))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
