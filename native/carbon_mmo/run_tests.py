#!/usr/bin/env python3
# MODULE: tests (runner)
"""Runs every phase test with a hard 60 s cap each.

    python run_tests.py                 # uses ./build
    python run_tests.py --build-dir out # custom build folder
    python run_tests.py --skip-host     # Python-only (before the C++ build exists)
"""
import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
CAP = 60


def host_exe(build_dir):
    name = "cmmo_host.exe" if os.name == "nt" else "cmmo_host"
    return os.path.join(build_dir, "bin", name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-dir", default=os.path.join(ROOT, "build"))
    ap.add_argument("--skip-host", action="store_true")
    args = ap.parse_args()
    env = dict(os.environ, CMMO_BUILD_DIR=os.path.abspath(args.build_dir))
    py = sys.executable
    # Use the Python the build was made for (macOS: `python3` is often Apple's 3.9, CMake picks Homebrew's)
    marker = os.path.join(args.build_dir, "python_exe.txt")
    if os.path.isfile(marker):
        built = open(marker, encoding="utf-8").read().strip()
        if built and os.path.isfile(built) and os.path.realpath(built) != os.path.realpath(py):
            print(f"using the build's Python: {built}")
            py = built
    t = os.path.join(ROOT, "tests")

    suite = []
    if not args.skip_host:
        suite.append(("phase 1  C++ <-> Python render hook", [host_exe(args.build_dir)]))
        suite.append(("world    terrain, levels, Play (C++)", [host_exe(args.build_dir).replace("cmmo_host", "test_world")]))
        editor = host_exe(args.build_dir).replace("cmmo_host", "cmmo_editor")
        if os.path.isfile(editor):
            shots = os.path.join(args.build_dir, "selftest")
            os.makedirs(shots, exist_ok=True)
            suite.append(("editor   self-test (real UI, screenshots in build/selftest)",
                          [editor, "--selftest", "--screenshot", os.path.join(shots, "editor.png"), "--content", os.path.join(shots, "content")]))
    suite += [
        ("phase 2  networking (binary codec)", [py, os.path.join(t, "test_phase2_net.py")]),
        ("phase 2  networking (json codec)", [py, os.path.join(t, "test_phase2_net.py"), "--codec", "json"]),
        ("phase 3  click-to-move", [py, os.path.join(t, "test_phase3_click_to_move.py")]),
        ("carbon   adapter contracts", [py, os.path.join(t, "test_carbon_contracts.py")]),
    ]

    failed = 0
    for name, cmd in suite:
        start = time.monotonic()
        try:
            r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=CAP)
            ok, out = r.returncode == 0, r.stdout + r.stderr
        except FileNotFoundError:
            ok, out = False, f"not found: {cmd[0]} (build first, or pass --skip-host)"
        except subprocess.TimeoutExpired:
            ok, out = False, f"timed out after {CAP} s"
        print(f"{'PASS' if ok else 'FAIL'}  {name}  ({time.monotonic() - start:.1f}s)")
        if not ok:
            failed += 1
            print("      " + out.strip().replace("\n", "\n      ")[-3000:])
    print("ALL OK" if not failed else f"{failed} FAILED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
