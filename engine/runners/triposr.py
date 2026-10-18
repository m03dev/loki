"""TripoSR: one cut-out picture -> one textured-by-vertex-colour mesh. stdin/stdout JSON, like every runner.

    {"image": "<cut-out RGBA png>", "out": "<path without extension>", "repo": "<TripoSR checkout>",
     "resolution": 256}
    -> {"ok", "glb", "obj", "device"}

TripoSR (github.com/VAST-AI-Research/TripoSR, MIT; weights stabilityai/TripoSR, MIT) is installed by
`python tools/setup_forge3d.py` into harness_data/tools/TripoSR, with torch for this machine (CUDA on
the PC, MPS on the Mac). It runs here, in its own process, so the engine never loads torch.
About 6 GB of GPU memory at resolution 256; CPU works but takes minutes.
"""
import json
import sys


def main():
    job = json.loads(sys.stdin.read() or "{}")
    try:
        sys.path.insert(0, str(job["repo"]))
        import numpy as np  # pylint: disable=import-outside-toplevel
        import torch  # pylint: disable=import-outside-toplevel
        from PIL import Image  # pylint: disable=import-outside-toplevel
        from tsr.system import TSR  # pylint: disable=import-outside-toplevel
        from tsr.utils import resize_foreground  # pylint: disable=import-outside-toplevel

        if torch.cuda.is_available():
            device = "cuda:0"
        elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"
        model = TSR.from_pretrained("stabilityai/TripoSR", config_name="config.yaml", weight_name="model.ckpt")
        model.renderer.set_chunk_size(8192)
        model.to(device)
        image = resize_foreground(Image.open(job["image"]).convert("RGBA"), 0.85)
        arr = np.array(image).astype(np.float32) / 255.0
        arr = arr[:, :, :3] * arr[:, :, 3:4] + (1 - arr[:, :, 3:4]) * 0.5     # grey background, as TripoSR expects
        image = Image.fromarray((arr * 255.0).astype(np.uint8))
        with torch.no_grad():
            codes = model([image], device=device)
        mesh = model.extract_mesh(codes, True, resolution=int(job.get("resolution") or 256))[0]
        out = str(job["out"])
        mesh.export(out + ".glb")
        mesh.export(out + ".obj")
        print(json.dumps({"ok": True, "glb": out + ".glb", "obj": out + ".obj", "device": device}), flush=True)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": "%s: %s" % (type(exc).__name__, str(exc)[:400])}), flush=True)


if __name__ == "__main__":
    main()
