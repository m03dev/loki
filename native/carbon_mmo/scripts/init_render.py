# MODULE: script-host (user hook)
# Called by the C++ host before the renderer starts. Everything here runs inside
# the engine's embedded interpreter; `cfg` is the live C++ RenderConfig.
import cmmo_engine as engine


def configure_render(cfg):
    info = engine.info()  # Python -> C++
    engine.log(f"init hook running on {info['platform']} (renderers: {', '.join(info['renderers'])})")

    cfg.title = "Carbon MMO Foundation"
    cfg.width = 1280
    cfg.height = 720
    cfg.clear_color = "#14213d"  # hex or (r, g, b[, a]) in [0, 1]
    cfg.vsync = True
    if cfg.max_frames == 0:
        cfg.max_frames = 120 if "glfw" in info["renderers"] else 3

    problems = cfg.validate()  # validation is implemented in C++
    if problems:
        raise ValueError("; ".join(problems))

    # Carbon math is available inside the host too.
    camera = engine.Vector3(0.0, 10.0, -20.0)
    engine.log(f"camera start {camera} distance-to-origin={camera.length():.2f}")

    base = cfg.clear_color

    @engine.on_frame  # C++ -> Python, every frame
    def on_frame(frame, dt):
        # Pulse the background a little to show the per-frame round trip.
        t = (frame % 60) / 60.0
        cfg.clear_color = (base[0], base[1] + 0.15 * t, base[2] + 0.2 * t, 1.0)
        if frame == 0:
            engine.log("first frame callback reached Python")
        return True
