#!/usr/bin/env python3
"""One command to build, test and open the Carbon MMO engine + editor on macOS or Windows.

    python3 tools/build.py            # build + tests
    python3 tools/build.py --open     # ... and open the editor
    python3 tools/build.py --doctor   # only print what this machine's toolchain looks like

It picks everything itself so nobody has to improvise flags:
- macOS: an arm64 Python 3.10+ (Homebrew's /opt/homebrew first; Apple's 3.9 and Intel/Rosetta Pythons are refused),
  Apple's own clang / clang++ / ar / ranlib via xcrun (a Homebrew LLVM or GNU binutils on PATH breaks the link),
  build dir on /Volumes/Xero when it is mounted, and it deletes macOS "._*" metadata files (exFAT / FAT drives).
- Windows: the Python running this script if 3.10+, else `py -3.13` / `py -3.12`; Visual Studio's generator.
When the build fails it prints the first error with context plus a short diagnosis, so the report is complete.
Runs on Python 3.8+ (works when started with Apple's /usr/bin/python3).
"""
import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAC = sys.platform == "darwin"
WIN = sys.platform.startswith("win")


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], **kw)


def out(cmd):
    try:
        return run(cmd, capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def python_info(exe):
    s = out([exe, "-c", "import platform,sys;print(platform.machine(),'%d.%d'%sys.version_info[:2],sys.executable)"])
    parts = s.split(" ", 2)
    if len(parts) != 3:
        return None
    machine, ver, path = parts
    return machine, tuple(int(x) for x in ver.split(".")), path


def pick_python():
    cands = []
    if MAC:
        cands += ["/opt/homebrew/bin/python3.13", "/opt/homebrew/bin/python3.12", "/opt/homebrew/bin/python3.14",
                  "/opt/homebrew/bin/python3.11", "/opt/homebrew/bin/python3"]
    cands += [sys.executable]
    for name in ("python3.13", "python3.12", "python3.14", "python3.11", "python3"):
        w = shutil.which(name)
        if w:
            cands.append(w)
    if WIN:
        for v in ("3.13", "3.12", "3.14", "3.11"):
            p = out(["py", "-" + v, "-c", "import sys;print(sys.executable)"])
            if p:
                cands.append(p)
    seen = set()
    for c in cands:
        if not c or c in seen or not Path(c).exists():
            continue
        seen.add(c)
        info = python_info(c)
        if not info:
            continue
        machine, ver, path = info
        if ver < (3, 10):
            continue
        if MAC and platform.machine() == "arm64" and machine != "arm64":
            print("  skipping %s: it is an Intel (%s) Python" % (path, machine))
            continue
        return path, ver
    sys.exit("No usable Python 3.10+ found%s." % (" (arm64). Install one: brew install python@3.13" if MAC else
                                                    ". Install Python 3.13 from python.org"))


def mac_tools():
    tools = {}
    for name, var in (("clang", "CMAKE_C_COMPILER"), ("clang++", "CMAKE_CXX_COMPILER"),
                      ("ar", "CMAKE_AR"), ("ranlib", "CMAKE_RANLIB")):
        p = out(["xcrun", "-f", name])
        if not p:
            sys.exit("xcrun can't find %s - install the Xcode command line tools: xcode-select --install" % name)
        tools[var] = p
    return tools


def remove_appledouble(*dirs):
    n = 0
    for d in dirs:
        if not d.exists():
            continue
        for p in d.rglob("._*"):
            if p.is_file():
                try:
                    p.unlink()
                    n += 1
                except OSError:
                    pass
    if n:
        print("  removed %d macOS '._*' metadata files (exFAT / FAT drive)" % n)


def doctor(build):
    print("== toolchain ==")
    print("  machine:", platform.machine(), platform.platform())
    if MAC:
        for name in ("clang++", "ar", "ranlib", "ld", "cmake", "python3"):
            print("  %-8s PATH: %s" % (name, " | ".join(out(["which", "-a", name]).splitlines()[:3]) or "-"))
        print("  xcode-select:", out(["xcode-select", "-p"]))
        print("  xcrun clang++:", out(["xcrun", "-f", "clang++"]), "-", out(["xcrun", "clang++", "--version"]).splitlines()[:1])
        mount = out(["df", str(build.parent if build.parent.exists() else ROOT)]).splitlines()[-1:]
        print("  build drive:", mount)
    cache = build / "CMakeCache.txt"
    if cache.exists():
        for line in cache.read_text(errors="replace").splitlines():
            if re.match(r"CMAKE_(AR|RANLIB|CXX_COMPILER|C_COMPILER|LINKER|OSX_ARCHITECTURES)(:|=)", line) or line.startswith("Python3_EXECUTABLE"):
                print("  cache:", line)
    lib = next(iter(build.rglob("libCarbonMath.a")), None) if build.exists() else None
    if lib and MAC:
        print("  %s members:" % lib.name, " ".join(out(["ar", "t", lib]).split()))
        print("  Inverse in it:", out(["nm", "-gU", lib]).count("Inverse") or "NOT FOUND")
    junk = list(ROOT.rglob("._*"))[:3] + (list(build.rglob("._*"))[:3] if build.exists() else [])
    print("  '._*' files:", [str(j) for j in junk] or "none")


def first_error(log):
    lines = log.splitlines()
    for i, l in enumerate(lines):
        if re.search(r"\berror\b|Undefined symbols|unresolved external", l, re.I):
            return "\n".join(lines[max(0, i - 15):i + 12])
    return "\n".join(lines[-30:])


def main():
    ap = argparse.ArgumentParser()
    default_build = Path("/Volumes/Xero/carbon_mmo/build") if MAC and Path("/Volumes/Xero").is_dir() else ROOT / "build"
    ap.add_argument("--build-dir", type=Path, default=default_build)
    ap.add_argument("--content", type=Path, default=None, help="editor content folder (default: next to the build dir)")
    ap.add_argument("--open", action="store_true", help="open the editor when the tests pass")
    ap.add_argument("--keep", action="store_true", help="reuse the build dir (default: start clean)")
    ap.add_argument("--no-tests", action="store_true")
    ap.add_argument("--no-editor", action="store_true", help="tests without the windowed editor self-test (CI)")
    ap.add_argument("--doctor", action="store_true")
    a = ap.parse_args()
    build = a.build_dir.resolve()
    if a.doctor:
        doctor(build)
        return 0

    py, ver = pick_python()
    print("Python: %s (%d.%d)" % (py, ver[0], ver[1]))
    env = dict(os.environ)
    cfg = ["cmake", "-S", ROOT, "-B", build, "-DCMAKE_BUILD_TYPE=Release", "-DPython3_EXECUTABLE=" + py]
    if MAC:
        env["COPYFILE_DISABLE"] = "1"
        tools = mac_tools()
        print("Apple tools:", tools["CMAKE_CXX_COMPILER"])
        cfg += ["-D%s=%s" % kv for kv in tools.items()]
        cfg += ["-DCMAKE_OSX_ARCHITECTURES=" + platform.machine()]
        env.pop("CC", None)
        env.pop("CXX", None)
    if not a.keep and build.exists():
        shutil.rmtree(build, ignore_errors=True)
    build.mkdir(parents=True, exist_ok=True)
    remove_appledouble(ROOT)

    print("Configuring ...")
    r = run(cfg, env=env, capture_output=True, text=True)
    (build / "configure.log").write_text(r.stdout + r.stderr)
    if r.returncode:
        print(first_error(r.stdout + r.stderr))
        sys.exit("CONFIGURE FAILED (full log: %s)" % (build / "configure.log"))
    remove_appledouble(build / "_deps")
    print("Building (a few minutes the first time) ...")
    r = run(["cmake", "--build", build, "--config", "Release", "-j", str(os.cpu_count() or 4)], env=env,
            capture_output=True, text=True)
    log = r.stdout + r.stderr
    (build / "build.log").write_text(log)
    if r.returncode:
        print("\n---- first error ----\n" + first_error(log) + "\n---------------------")
        doctor(build)
        sys.exit("BUILD FAILED (full log: %s). Paste everything above into the report." % (build / "build.log"))
    print("Built.")

    if not a.no_tests:
        r = run([py, ROOT / "run_tests.py", "--build-dir", build] + (["--no-editor"] if a.no_editor else []))
        if r.returncode:
            sys.exit("TESTS FAILED - paste the FAIL lines above into the report.")

    if a.open:
        exe = build / "bin" / ("cmmo_editor.exe" if WIN else "cmmo_editor")
        content = (a.content or build.parent / "content").resolve()
        content.mkdir(parents=True, exist_ok=True)
        layout = build.parent / "cmmo_editor_layout.ini"
        logf = open(build.parent / "editor.log", "w")
        kw = {"cwd": str(build.parent), "stdout": logf, "stderr": subprocess.STDOUT}
        if WIN:
            kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000   # detached, new group, no console window
        else:
            kw["start_new_session"] = True
        if layout.exists() and not a.keep:
            layout.unlink()
        subprocess.Popen([str(exe), "--content", str(content)], **kw)
        print("Editor opened (log: %s). File > New Starter Zone, then Play (Alt+P)." % (build.parent / "editor.log"))
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
