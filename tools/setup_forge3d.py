"""Install Forge's best 3D backend, TripoSR, on this computer (macOS and Windows).

    python tools/setup_forge3d.py            torch for this machine + TripoSR's code and packages
    python tools/setup_forge3d.py online     only gradio_client (the free online Space fallback)
    python tools/setup_forge3d.py check      what Forge can use here

TripoSR (github.com/VAST-AI-Research/TripoSR, MIT; weights stabilityai/TripoSR, MIT, ~1.7 GB, downloaded
on first use to the Hugging Face cache). The code goes to harness_data/tools/TripoSR (never the repo);
the packages into the Python running this script - use LOKI's own:
    macOS:   harness_data/.venv/bin/python tools/setup_forge3d.py
    Windows: harness_data\\.venv\\Scripts\\python.exe tools\\setup_forge3d.py
GPU: CUDA (the PC's RTX 3070 Ti, ~6 GB) or Apple MPS; CPU works but takes minutes.
Nothing runs a shell string; every step is shown before it runs.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
TRIPOSR_ZIP = "https://github.com/VAST-AI-Research/TripoSR/archive/refs/heads/main.zip"
# TripoSR's requirements.txt minus torchmcubes (a CUDA build that often fails on Windows); PyMCubes is
# used instead through the shim below.
PACKAGES = ["omegaconf==2.3.0", "Pillow", "einops", "transformers", "trimesh", "rembg", "huggingface-hub",
            "imageio", "xatlas", "moderngl", "PyMCubes"]
MCUBES_SHIM = '''"""LOKI: torchmcubes replaced by PyMCubes (pip), the same marching_cubes(volume, level) call."""
import mcubes
import torch


def marching_cubes(volume, level):
    v, f = mcubes.marching_cubes(volume.detach().cpu().numpy(), float(level))
    return torch.from_numpy(v.astype("float32")), torch.from_numpy(f.astype("int64"))
'''


def run(argv: list) -> bool:
    print("  $ " + " ".join(argv), flush=True)
    try:
        return subprocess.run(argv, check=False).returncode == 0
    except OSError as exc:
        print("    could not run: %s" % exc)
        return False


def pip(*packages: str, index: str = "") -> bool:
    argv = [sys.executable, "-m", "pip", "install", "-U", *packages]
    if index:
        argv += ["--index-url", index]
    return run(argv)


def torch_for_this_machine() -> bool:
    if shutil.which("nvidia-smi"):
        return pip("torch", "torchvision", index="https://download.pytorch.org/whl/cu128")
    return pip("torch", "torchvision")      # macOS wheels include MPS; elsewhere CPU


def fetch_triposr(target: Path) -> bool:
    if (target / "tsr" / "system.py").is_file():
        print("  TripoSR code already in %s" % target)
        return True
    print("  downloading %s" % TRIPOSR_ZIP)
    try:
        with urllib.request.urlopen(TRIPOSR_ZIP, timeout=120) as resp:
            data = resp.read()
    except OSError as exc:
        print("    download failed: %s" % exc)
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        top = zf.namelist()[0].split("/")[0]
        tmp = target.parent / (target.name + ".part")
        shutil.rmtree(tmp, ignore_errors=True)
        zf.extractall(tmp)
        shutil.rmtree(target, ignore_errors=True)
        os.replace(tmp / top, target)
        shutil.rmtree(tmp, ignore_errors=True)
    shim = target / "torchmcubes.py"
    if not shim.exists():
        shim.write_text(MCUBES_SHIM, encoding="utf-8")
    print("  TripoSR code in %s (MIT, LICENSE kept there)" % target)
    return True


def check() -> None:
    import forge3d  # pylint: disable=import-outside-toplevel
    for key, value in forge3d.status().items():
        print("  %-8s %s" % (key, value))
    print("  order    %s" % " -> ".join(forge3d.plan("auto")))


def main(argv: list) -> int:
    what = argv[0] if argv else "triposr"
    if what == "check":
        check()
        return 0
    if what == "online":
        ok = pip("gradio_client")
        check()
        return 0 if ok else 1
    if what != "triposr":
        print(__doc__)
        return 2
    import forge3d  # pylint: disable=import-outside-toplevel
    ok = torch_for_this_machine() and pip(*PACKAGES) and fetch_triposr(forge3d.triposr_dir())
    print("done - Forge now uses TripoSR first" if ok else "failed - Forge still works with its offline lift")
    check()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
