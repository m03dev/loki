# Text-to-video and render repos for the PC (RTX 3070 Ti, 8 GB) - 2026-10-27

Owner: "really work a lot on the render ... type something and it renders a video. look for more repo we could use".
What LOKI uses now: Wan VACE 14B Q4 GGUF, text only (engine/forge_workflows/wan_t2v.json), 640x368, 3 s - it works on
8 GB but is slow (14B). These would make it faster or better; all run in ComfyUI, which LOKI already drives.

| Repo / model | Why | Fit on 8 GB | Licence |
| --- | --- | --- | --- |
| Wan2.2 TI2V-5B, GGUF (huggingface.co/QuantStack/Wan2.2-TI2V-5B-GGUF) | text AND image to video, 720p 24 fps, one small model | yes (Q4-Q6) | Apache-2.0 |
| Wan2.2 Lightning / lightx2v LoRAs (huggingface.co/lightx2v/Wan2.2-Lightning) | 4 sampling steps instead of 20-40: several times faster | yes | Apache-2.0 |
| LTX-2 / LTX-2.3 (github.com/Lightricks/ComfyUI-LTXVideo, ComfyUI-native) | very fast, video with audio; NVIDIA has an RTX guide | with FP8/GGUF and offload | LTX-2 Community License - check before shipping |
| FramePack (github.com/lllyasviel/FramePack) | long videos (up to a minute) at constant memory, 6 GB minimum | yes | Apache-2.0 |

Next for LOKI (LOKI_TASKS.md): add Wan2.2 TI2V-5B Q5 + the Lightning LoRA on the PC as a second wan_t2v graph, time
both on the same prompt, keep the faster one that looks as good as the default.
