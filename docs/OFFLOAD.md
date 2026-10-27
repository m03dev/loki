# Giving heavy work to the PC (engine/offload.py)

Owner 2026-10-26: "the mac isnt the power house ... the mac should always try to give windows work thats the entire
thing it needs to give windows work without pushing git".

| Work | Where it goes from the Mac | Falls back to |
| --- | --- | --- |
| pictures (`image`) | hosted models first (NVIDIA FLUX the owner liked), then the PC's sd.cpp | error that names the PC's state |
| area edits (`img2img`) | always the PC (sd.cpp inpaint with the mask) | error: "area edits run on your PC, but ..." |
| 3D models (`make_3d`) | the PC (ComfyUI Pixal3D / TRELLIS.2, Hunyuan3D, TripoSR); `auto` then the online Space | the online Space |
| Blender clean-ups (`polish`) | the PC's Blender; files and the sidecar land in the Mac's folders | the Mac's Blender only when no PC is linked |

How: the peer link (`engine/peers.py`, LAN or the bore relay, every request and relay answer signed). The Mac uploads
inputs in 4 MB chunks (`POST /peer/work op=put`), starts the job (`op=start`, kind + only that kind's settings), polls
(`op=status`), downloads the results (`op=get`, sha256 checked), then `op=done` removes the PC's copy. The PC serves
only the kinds its hello lists in `work` (what is really installed there); anything else is refused with why.

Switches: `LOKI_MACHINE_ROLE=light|main`, `LOKI_OFFLOAD=auto|off|always`, `LOKI_OFFLOAD_SERVE=off` (the PC takes no
work), `LOKI_COMFY_AUTOSTART=force` (start ComfyUI on a light machine anyway). Status: `GET /offload/status`, and the
"Your PC" button on Home. Tests: `tests/test_offload.py` (a real peer server on loopback), `tests/js/test_home_pc.js`.
