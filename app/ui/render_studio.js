// Render Studio - the Render tab (owner, 2026-10-21: "Render Studio is a new top-level tab ... the home screen previews
// renders"). Left: every render job (path traced here, AI on the PC's ComfyUI), status, progress, cancel / retry.
// Centre: the big preview - the input passes frame by frame or the result video. Right: the settings, two engines:
//   Path traced   Forge's own path tracer (window.ForgeRender, app/ui/forge_render.js) over the Time Slider's frames
//   AI Renderer   Forge's depth + line-art passes (app/ui/forge_passes.js) -> ComfyUI on the PC: Wan VACE with the
//                 VACE / SkyReels V3 R2V merge as GGUF (engine/ai_renderer.py, engine/ai_renderer_workflows/,
//                 docs/AI_RENDERER.md). Every control maps to a verified input of LOKI's own graph.
// Icons with a hover tooltip (name + what it does, app/ui/icons.js); sizes in % so the panes follow the window.
// Jobs land in harness_data/renders/<job>/manifest.json, which the Home screen lists.
"use strict";

const LokiRenderStudio = (() => {
  const S = { built: false, pane: null, jobs: [], sel: null, wf: null, wfs: [], settings: null, timer: 0, passes: null,
    previewKind: "lineart", frame: 0, engine: "ai", startImage: null, running: null, report: null, cache: {},
    node: false, graph: null };
  const STORE = "loki-render-studio";
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const call = (path, body) => (typeof api === "function" ? api(path, body) : Promise.reject(new Error("not ready")));
  const token = () => (typeof state !== "undefined" && state ? state.token : "");
  const $ = (id) => document.getElementById(id);
  const fmtGB = (b) => (b ? (b / 1e9).toFixed(1) + " GB" : "");

  function btn(icon, name, what, fn, id, cls) {
    const b = mk("button", "rs-btn" + (cls ? " " + cls : "")); b.type = "button";
    b.dataset.icon = icon; b.dataset.tipName = name; b.dataset.tipWhat = what; b.setAttribute("aria-label", name);
    if (typeof iconSvg === "function") b.innerHTML = iconSvg(icon); else b.textContent = name;
    if (id) b.id = id;
    b.addEventListener("click", fn);
    return b;
  }
  function field(label, input, tip) {
    const l = mk("label", "rs-field"); const s = mk("span", "rs-label", label);
    if (tip) { l.title = tip; }
    l.append(s, input); return l;
  }
  function num(id, val, min, max, step) {
    const i = mk("input"); i.type = "number"; i.id = id; i.value = String(val);
    if (min != null) i.min = String(min); if (max != null) i.max = String(max); if (step != null) i.step = String(step);
    i.addEventListener("keydown", (e) => e.stopPropagation());
    return i;
  }
  function sel(id, opts, val) {
    const s = mk("select"); s.id = id;
    for (const o of opts) { const [v, t] = Array.isArray(o) ? o : [o, o]; s.append(new Option(t, v)); }
    if (val != null) s.value = val;
    return s;
  }
  function saveLocal() {
    try { localStorage.setItem(STORE, JSON.stringify(collect())); } catch (_) { /* private window */ }
  }
  function loadLocal() { try { return JSON.parse(localStorage.getItem(STORE) || "null"); } catch (_) { return null; } }

  // ------------------------------------------------------------------ build
  function build(p) {
    S.pane = p; S.built = true;
    p.classList.add("rs-pane");
    const root = mk("div", "rs-root"); root.id = "render-studio";
    const left = mk("aside", "rs-jobs"); left.id = "rs-jobs";
    const lhead = mk("div", "rs-head");
    lhead.append(mk("h3", "", "Jobs"), btn("update", "Refresh", "Read the job list again (all machines' jobs that wrote a manifest here).", refresh));
    const list = mk("div", "rs-joblist"); list.id = "rs-joblist";
    left.append(lhead, list);

    const centre = mk("section", "rs-centre"); centre.id = "rs-centre";
    const viewbar = mk("div", "rs-viewbar"); viewbar.id = "rs-viewbar";               // the Render View's own menu bar
    const ptabs = mk("div", "rs-ptabs"); ptabs.id = "rs-ptabs";
    const stage = mk("div", "rs-stage"); stage.id = "rs-stage";
    const img = mk("img", "rs-img"); img.id = "rs-img"; img.alt = "";
    const cv = mk("canvas", "rs-canvas"); cv.id = "rs-canvas";
    const vid = mk("video", "rs-video"); vid.id = "rs-video"; vid.controls = true; vid.loop = true; vid.hidden = true;
    const empty = mk("p", "rs-empty", "Render the passes from a Forge camera, or pick a job on the left.");
    empty.id = "rs-empty";
    const prog = mk("div", "rs-progress"); prog.id = "rs-progress"; prog.hidden = true;
    const ptop = mk("div", "rs-progress-top");
    const pname = mk("span", "rs-progress-name", ""); pname.id = "rs-progress-name";
    const ppct = mk("span", "rs-progress-pct", ""); ppct.id = "rs-progress-pct";
    ptop.append(pname, ppct);
    const ptrack = mk("div", "rs-bar rs-progress-track"); const pfill = mk("i"); pfill.id = "rs-progress-bar"; ptrack.append(pfill);
    const plast = mk("div", "rs-progress-last", ""); plast.id = "rs-progress-last";
    prog.append(ptop, ptrack, plast, btn("stop", "Cancel", "Stop this job (ComfyUI is asked to interrupt it).",
      () => { const j = liveJob(); if (j) cancelJob(j.job); }, "rs-progress-cancel"));
    const graphwrap = mk("div", "rs-graphwrap"); graphwrap.id = "rs-graphwrap"; graphwrap.hidden = true;
    stage.append(img, cv, vid, empty, graphwrap, prog);
    const scrub = mk("div", "rs-scrub");
    const slider = mk("input"); slider.type = "range"; slider.id = "rs-frame"; slider.min = "0"; slider.max = "0"; slider.value = "0";
    slider.title = "Scrub the frames";
    slider.addEventListener("input", () => { S.frame = +slider.value; showPreview(); });
    const flabel = mk("span", "rs-flabel", ""); flabel.id = "rs-flabel";
    scrub.append(slider, flabel);
    const info = mk("div", "rs-info"); info.id = "rs-info";
    centre.append(viewbar, ptabs, stage, scrub, info);
    buildViewBar(viewbar);

    const right = mk("aside", "rs-settings"); right.id = "rs-settings";
    root.append(left, centre, right);
    p.replaceChildren(root);
    buildSettings(right);
    const saved = loadLocal();
    if (saved) apply(saved);
    syncEngine();
  }

  function buildSettings(right) {
    const engines = mk("div", "rs-engines");
    const eAI = btn("brain", "AI Renderer", "Forge's depth + line-art passes guide a video model (Wan VACE + SkyReels, GGUF) in ComfyUI on your PC.", () => { S.engine = "ai"; syncEngine(); }, "rs-eng-ai");
    const ePT = btn("image", "Path traced", "Forge's own path tracer renders every frame of the range here, in this window.", () => { S.engine = "path"; syncEngine(); }, "rs-eng-path");
    engines.append(eAI, ePT);

    // the scene: camera, range, size
    const scene = mk("fieldset", "rs-group"); scene.append(mk("legend", "", "Scene"));
    const t = forgeTime();
    scene.append(
      field("Camera", sel("rs-camera", [["current", "Current view"], "persp", "top", "front", "side"], "current"), "Forge's camera the frames are rendered from (a copy: the viewport never moves)."),
      row(field("Start", num("rs-start", t.start, -100000, 100000, 1)), field("End", num("rs-end", t.end, -100000, 100000, 1)), field("Step", num("rs-step", 1, 1, 100, 1))),
      row(field("Width", num("rs-width", 832, 16, 4096, 16)), field("Height", num("rs-height", 480, 16, 4096, 16)), field("FPS", num("rs-fps", 16, 1, 120, 1))),
      row(field("Aspect", sel("rs-aspect", [["", "free"], ["16:9", "16:9"], ["9:16", "9:16"], ["1:1", "1:1"], ["4:3", "4:3"], ["832:480", "Wan 832x480"]], "")),
        field("Name", (() => { const i = mk("input"); i.id = "rs-name"; i.placeholder = "my shot"; i.addEventListener("keydown", (e) => e.stopPropagation()); return i; })())),
    );
    $("rs-aspect") || 0;
    const passes = mk("fieldset", "rs-group"); passes.append(mk("legend", "", "Control passes"));
    const pbox = mk("div", "rs-checks");
    for (const [k, label, tip, on] of [["depth", "Depth", "White = near, black = far, normalised to the visible meshes.", true],
      ["lineart", "Line art", "White outlines and creases on black (edge detection on depth + normals).", true],
      ["normal", "Normals", "View-space normals as colour (for preview; the graph does not use them).", false],
      ["beauty", "Beauty", "The viewport's shaded look (for the Canny preprocess graph or a quick look).", false]]) {
      const l = mk("label", "rs-check"); l.title = tip;
      const c = mk("input"); c.type = "checkbox"; c.id = "rs-pass-" + k; c.checked = on;
      l.append(c, mk("span", "", label)); pbox.append(l);
    }
    const lw = num("rs-linew", 1, 1, 4, 1);
    passes.append(pbox, row(field("Line width", lw, "Line width in pixels."), field("Crease", num("rs-crease", 0.35, 0.02, 2, 0.01), "How sharp a fold must be to draw a line (1 - cos of the angle).")),
      mk("div", "rs-actions"));
    passes.lastChild.append(
      btn("layers", "Render passes", "Render the checked passes from the camera over the range and show them here (nothing in the scene changes).", () => renderPasses(false), "rs-passes-go"),
      btn("eye", "Send to Render Studio", "Use Forge's current camera and Time Slider range.", () => { const tt = forgeTime(); $("rs-start").value = tt.start; $("rs-end").value = tt.end; $("rs-camera").value = "current"; }, "rs-from-forge"));

    // AI
    const ai = mk("div", "rs-ai"); ai.id = "rs-ai";
    const server = mk("fieldset", "rs-group"); server.append(mk("legend", "", "ComfyUI"));
    const url = mk("input"); url.id = "rs-url"; url.placeholder = "http://127.0.0.1:8188"; url.addEventListener("keydown", (e) => e.stopPropagation());
    const consent = mk("label", "rs-check"); const cc = mk("input"); cc.type = "checkbox"; cc.id = "rs-consent";
    consent.title = "Needed only when ComfyUI is on a computer that is not this one or one of LOKI's linked machines: your passes and start image are sent there.";
    consent.append(cc, mk("span", "", "Allow uploads to this server"));
    const where = mk("p", "rs-note"); where.id = "rs-where";
    server.append(field("Address", url, "Where ComfyUI runs: the PC's address and port 8188 (tools/setup_comfyui.py starts it)."), consent, where,
      wrap(btn("plug", "Test connection", "Ask ComfyUI for its version and GPU (GET /system_stats).", testConn, "rs-test"),
        btn("check", "Save address", "Remember this address (and the upload choice) on this machine.", saveServer, "rs-save-url")));

    const wfset = mk("fieldset", "rs-group"); wfset.append(mk("legend", "", "Workflow"));
    wfset.append(field("Graph", sel("rs-wf", [["vace_render", "AI Renderer (Wan VACE + SkyReels, GGUF)"]], "vace_render"), "LOKI's own ComfyUI graph (engine/ai_renderer_workflows/)."),
      field("Model", sel("rs-model", [], ""), "The GGUF size: Q4_K_M is the model card's balance; Q3_K_M needs less memory (an 8 GB card offloads part of either)."),
      field("Guide", sel("rs-control", [["both", "Line art + depth"], ["lineart", "Line art only"], ["depth", "Depth only"]], "both"), "Which passes steer the video."),
      row(field("Depth share", num("rs-depthshare", 0.2, 0, 1, 0.05), "How much depth is mixed into the line art (the creator's example: line art with 20% depth)."),
        field("Strength", num("rs-strength", 1, 0, 10, 0.05), "How strongly VACE follows the guide (WanVaceToVideo strength).")));

    const gen = mk("fieldset", "rs-group"); gen.append(mk("legend", "", "Generation"));
    const prompt = mk("textarea"); prompt.id = "rs-prompt"; prompt.rows = 3; prompt.placeholder = "Describe the shot: subject, style, light, camera move";
    const neg = mk("textarea"); neg.id = "rs-negative"; neg.rows = 2; neg.placeholder = "(the graph's default negative prompt)";
    for (const x of [prompt, neg]) x.addEventListener("keydown", (e) => e.stopPropagation());
    const seedIn = num("rs-seed", Math.floor(Math.random() * 1e9), 0, 18446744073709551615, 1);
    gen.append(field("Prompt", prompt), field("Negative", neg),
      row(field("Seed", seedIn), wrap(btn("dice", "New seed", "A random seed.", () => { seedIn.value = String(Math.floor(Math.random() * 1e12)); }))),
      row(field("Frames", num("rs-frames", 33, 1, 2001, 4), "Wan needs 4n+1 frames (33, 49, 81 ...)."), wrap(btn("sliders", "Fit frames", "Set Frames to the 4n+1 count that covers the range.", fitFrames))),
      row(field("Steps", num("rs-steps", 20, 1, 200, 1)), field("CFG", num("rs-cfg", 6, 0, 30, 0.1)), field("Shift", num("rs-shift", 8, 0, 100, 0.1), "ModelSamplingSD3 shift.")),
      row(field("Sampler", sel("rs-sampler", ["uni_pc", "euler", "dpmpp_2m", "lcm"], "uni_pc")), field("Scheduler", sel("rs-scheduler", ["simple", "normal", "karras", "beta"], "simple"))));

    const start = mk("fieldset", "rs-group"); start.append(mk("legend", "", "Start image"));
    const file = mk("input"); file.type = "file"; file.accept = "image/png,image/jpeg,image/webp"; file.hidden = true; file.id = "rs-startfile";
    file.addEventListener("change", () => { if (file.files[0]) loadStartFile(file.files[0]); });
    const thumb = mk("img", "rs-startthumb"); thumb.id = "rs-startthumb"; thumb.alt = ""; thumb.hidden = true;
    start.append(thumb, wrap(
      btn("image", "Start image from a file", "Pick a picture that sets the look of the whole video (PNG, JPEG, WebP).", () => file.click(), "rs-start-file"),
      btn("eye", "Start image from Forge", "Use what Forge's camera sees now (without grid and manipulator).", startFromForge, "rs-start-forge"),
      btn("close", "No start image", "Generate from the prompt and the passes alone.", () => setStart(null), "rs-start-none")), file);

    const presets = mk("fieldset", "rs-group"); presets.append(mk("legend", "", "Presets"));
    const proj = mk("input"); proj.id = "rs-project"; proj.value = "forge"; proj.addEventListener("keydown", (e) => e.stopPropagation());
    const pname = mk("input"); pname.id = "rs-preset-name"; pname.placeholder = "preset name"; pname.addEventListener("keydown", (e) => e.stopPropagation());
    presets.append(row(field("Project", proj, "Presets are saved per project."), field("Preset", sel("rs-preset", [["", "-"]], ""))), field("Save as", pname),
      wrap(btn("check", "Save preset", "Save every setting here under that name for this project.", savePreset, "rs-preset-save"),
        btn("enter", "Load preset", "Put the chosen preset's settings back.", loadPreset, "rs-preset-load"),
        btn("broom", "Delete preset", "Remove the chosen preset.", deletePreset, "rs-preset-del")));
    proj.addEventListener("change", loadPresets);

    const go = mk("div", "rs-go");
    go.append(btn("check", "Preflight", "Check everything before a run: ComfyUI reachable, node classes, model files, frame count, passes, disk, uploads.", runPreflight, "rs-preflight"),
      btn("play", "Render", "Start the job (AI: render the passes, upload them and queue the graph; path traced: render every frame here).", startJob, "rs-render", "primary"));
    const rep = mk("div", "rs-report"); rep.id = "rs-report";
    ai.append(server, wfset, gen, start, presets);

    const pt = mk("div", "rs-pt"); pt.id = "rs-pt";
    const ptg = mk("fieldset", "rs-group"); ptg.append(mk("legend", "", "Path tracer"));
    ptg.append(row(field("Samples", num("rs-samples", 64, 1, 4096, 1)), field("Bounces", num("rs-bounces", 4, 1, 16, 1))),
      mk("p", "rs-note", window.ForgeRender ? "Forge's path tracer renders each frame here; keep the window open." : "Forge's path tracer is not in this window."));
    pt.append(ptg);

    right.append(engines, scene, passes, ai, pt, go, rep);
    $("rs-aspect").addEventListener("change", () => {
      const a = $("rs-aspect").value; if (!a) return;
      const [x, y] = a.split(":").map(Number);
      if (a === "832:480") { $("rs-width").value = 832; $("rs-height").value = 480; return; }
      const w = +$("rs-width").value || 832; $("rs-height").value = String(Math.max(16, Math.round(w * y / x / 16) * 16));
    });
    right.addEventListener("change", saveLocal);
  }
  const row = (...kids) => { const d = mk("div", "rs-row"); d.append(...kids); return d; };
  const wrap = (...kids) => { const d = mk("div", "rs-actions"); d.append(...kids); return d; };

  function syncEngine() {
    $("rs-eng-ai").classList.toggle("on", S.engine === "ai");
    $("rs-eng-path").classList.toggle("on", S.engine === "path");
    $("rs-ai").hidden = S.engine !== "ai";
    $("rs-pt").hidden = S.engine !== "path";
    $("rs-preflight").hidden = S.engine !== "ai";
  }

  function forgeTime() {
    const v = typeof forge !== "undefined" && forge ? forge.view : null;
    const t = v && v.tree && v.tree.time;
    return t ? { start: t.start, end: t.end, frame: t.frame, fps: t.fps } : { start: 1, end: 24, frame: 1, fps: 24 };
  }

  function collect() {
    const g = (id) => ($(id) ? $(id).value : undefined);
    return { engine: S.engine, camera: g("rs-camera"), start: +g("rs-start"), end: +g("rs-end"), step: +g("rs-step"), width: +g("rs-width"), height: +g("rs-height"),
      fps: +g("rs-fps"), name: g("rs-name"), passes: ["depth", "lineart", "normal", "beauty"].filter((k) => $("rs-pass-" + k) && $("rs-pass-" + k).checked),
      lineWidth: +g("rs-linew"), crease: +g("rs-crease"), workflow: g("rs-wf"), model: g("rs-model"), control: g("rs-control"),
      depth_share: +g("rs-depthshare"), strength: +g("rs-strength"), prompt: g("rs-prompt"), negative: g("rs-negative"), seed: g("rs-seed"),
      frames: +g("rs-frames"), steps: +g("rs-steps"), cfg: +g("rs-cfg"), shift: +g("rs-shift"), sampler: g("rs-sampler"), scheduler: g("rs-scheduler"),
      samples: +g("rs-samples"), bounces: +g("rs-bounces") };
  }
  function apply(s) {
    if (!s) return;
    const set = (id, v) => { if ($(id) && v != null && v !== "" && !Number.isNaN(v)) $(id).value = String(v); };
    if (s.engine) S.engine = s.engine;
    for (const [id, k] of [["rs-camera", "camera"], ["rs-step", "step"], ["rs-width", "width"], ["rs-height", "height"], ["rs-fps", "fps"],
      ["rs-linew", "lineWidth"], ["rs-crease", "crease"], ["rs-model", "model"], ["rs-control", "control"], ["rs-depthshare", "depth_share"],
      ["rs-strength", "strength"], ["rs-prompt", "prompt"], ["rs-negative", "negative"], ["rs-seed", "seed"], ["rs-frames", "frames"], ["rs-steps", "steps"],
      ["rs-cfg", "cfg"], ["rs-shift", "shift"], ["rs-sampler", "sampler"], ["rs-scheduler", "scheduler"], ["rs-samples", "samples"], ["rs-bounces", "bounces"]]) set(id, s[k]);
    if (Array.isArray(s.passes)) for (const k of ["depth", "lineart", "normal", "beauty"]) if ($("rs-pass-" + k)) $("rs-pass-" + k).checked = s.passes.includes(k);
    syncEngine();
  }
  // only the graph's verified parameters go to the engine (engine/ai_renderer_workflows/vace_render.json "params")
  function aiParams(s) {
    const p = { prompt: s.prompt, seed: s.seed, steps: s.steps, cfg: s.cfg, sampler: s.sampler, scheduler: s.scheduler, shift: s.shift,
      frames: s.frames, width: s.width, height: s.height, strength: s.strength, depth_share: s.depth_share, fps: s.fps };
    if (s.negative) p.negative = s.negative;
    if (s.model) p.model = s.model;
    const allowed = S.wf ? Object.keys(S.wf.params || {}) : Object.keys(p);
    return Object.fromEntries(Object.entries(p).filter(([k, v]) => allowed.includes(k) && v !== "" && v != null && !(typeof v === "number" && Number.isNaN(v))));
  }

  function fitFrames() {
    const s = collect();
    const n = Math.floor((s.end - s.start) / Math.max(1, s.step)) + 1;
    const f = Math.max(1, Math.ceil((n - 1) / 4) * 4 + 1);
    $("rs-frames").value = String(f);
    say("Frames " + f + " (4n+1) for " + n + " frames in the range" + (f !== n ? "; render the passes over " + f + " frames, or VACE pads the end with grey." : "."));
  }

  // ------------------------------------------------------------------ server, workflows, presets
  async function refresh() {
    let r;
    try { r = await call("/render/status"); } catch (e) { r = { ok: false, error: e.message }; }
    if (!r || !r.ok) { say((r && r.error) || "LOKI's engine does not answer.", true); return; }
    S.jobs = Array.isArray(r.jobs) ? r.jobs : []; S.wfs = Array.isArray(r.workflows) ? r.workflows : [];
    S.wf = S.wfs.find((w) => w.name === ($("rs-wf").value || "vace_render")) || S.wfs[0] || null;
    const st = S.settings = r.settings || null;
    if (st) {   // an older engine (or none) answers without settings: leave the fields as they are
      if (document.activeElement !== $("rs-url")) $("rs-url").value = st.url || "";
      $("rs-consent").checked = !!st.consent_remote;
      const w = st.where || {};
      $("rs-where").textContent = "ComfyUI at " + (st.url_shown || st.url || "?") + ": " + (w.note || "?") + (w.own ? "." : " - uploads need your OK.");
    }
    const wsel = $("rs-wf"), keep = wsel.value;
    const usable = S.wfs.filter((w) => w && w.name && ((w.uploads && Object.keys(w.uploads).length) || w.name.startsWith("zimage")));
    if (usable.length) wsel.replaceChildren(...usable.map((w) => new Option(w.label || w.name, w.name)));
    if ([...wsel.options].some((o) => o.value === keep)) wsel.value = keep;
    const msel = $("rs-model"), mkeep = msel.value;
    const m = S.wf && (S.wf.models || []).find((x) => x.input === "unet_name");
    if (m) {
      msel.replaceChildren(new Option(m.file + " (" + fmtGB(m.size) + ")", m.file), ...(m.alternatives || []).map((a) => new Option(a.file + " (" + fmtGB(a.size) + ")", a.file)));
      if ([...msel.options].some((o) => o.value === mkeep)) msel.value = mkeep;
    }
    renderJobs();
  }

  function renderJobs() {
    const list = $("rs-joblist"); if (!list) return;
    list.replaceChildren();
    if (!S.jobs.length) list.append(mk("p", "rs-note", "No renders yet."));
    for (const j of S.jobs) {
      if (!j || !j.job) continue;
      const r = mk("div", "rs-job rs-" + j.status + (S.sel === j.job ? " on" : "")); r.dataset.job = j.job; r.tabIndex = 0;
      const top = mk("div", "rs-jobtop");
      top.append(mk("span", "rs-kind", j.kind === "ai" ? "AI" : "PT"), mk("span", "rs-jobname", j.name), mk("span", "rs-status", j.status));
      const bar = mk("div", "rs-bar"); const fill = mk("i"); fill.style.width = Math.round((j.progress || 0) * 100) + "%"; bar.append(fill);
      const act = mk("div", "rs-jobact");
      if (!["succeeded", "failed", "cancelled", "idle"].includes(j.status)) act.append(btn("stop", "Cancel", "Stop this job (ComfyUI is asked to interrupt it).", (e) => { e.stopPropagation(); cancelJob(j.job); }));
      if (["failed", "cancelled"].includes(j.status)) act.append(btn("update", "Retry", "Run it again with the same passes and settings as a new job.", (e) => { e.stopPropagation(); retryJob(j.job); }));
      r.append(top, bar, mk("div", "rs-last", j.last || ""), act);
      r.addEventListener("click", () => select(j.job));
      list.append(r);
    }
    updateProgress();
  }

  async function select(job) {
    S.sel = job; renderJobs();
    const r = await call("/render/job?id=" + encodeURIComponent(job));
    if (!r || !r.ok || !r.manifest) return;
    const m = r.manifest;
    S.passes = null;
    const kinds = [...((m.outputs || []).length ? ["result"] : []), ...Object.keys(m.passes || {})];
    tabs(kinds, kinds[0]);
    S.jobView = m; S.jobId = job; S.frame = 0;
    $("rs-info").textContent = [m.name, m.status, (m.size || []).join("x"), m.frames ? m.frames + " frames" : "", m.fps ? m.fps + " fps" : "", m.camera, m.machine || ""]
      .filter(Boolean).join(" · ") + ((m.log || []).length ? "\n" + m.log.slice(-6).map((l) => new Date(l.t * 1000).toLocaleTimeString() + "  " + l.msg).join("\n") : "");
    showPreview();
  }

  async function fileURL(job, name) {
    const key = job + "/" + name;
    if (S.cache[key]) return S.cache[key];
    const r = await fetch("/render/file?job=" + encodeURIComponent(job) + "&name=" + encodeURIComponent(name), { headers: { Authorization: "Bearer " + token() } });
    if (!r.ok) return null;
    const blob = await r.blob();
    let url;
    if (/^video\//.test(blob.type)) url = URL.createObjectURL(blob);   // media-src allows blob:
    else url = await new Promise((res) => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(blob); });   // img-src: data:
    S.cache[key] = url;
    return url;
  }

  function tabs(kinds, current) {
    const t = $("rs-ptabs"); t.replaceChildren();
    S.previewKind = current;
    for (const k of kinds) {
      const b = mk("button", "rs-ptab" + (k === current ? " on" : ""), { result: "Result", depth: "Depth", lineart: "Line art", normal: "Normals", beauty: "Beauty", start: "Start" }[k] || k);
      b.type = "button"; b.dataset.kind = k;
      b.addEventListener("click", () => { S.previewKind = k; for (const x of t.children) x.classList.toggle("on", x === b); showPreview(); });
      t.append(b);
    }
  }

  async function showPreview() {
    if (S.node) return;   // the Nodes view owns the stage
    const img = $("rs-img"), cv = $("rs-canvas"), vid = $("rs-video"), slider = $("rs-frame"), empty = $("rs-empty");
    img.hidden = cv.hidden = vid.hidden = true; empty.hidden = true;
    const k = S.previewKind;
    if (S.passes && S.passes.frames.length && (k !== "start" || S.startImage)) {   // fresh passes in memory
      if (k === "start") { img.src = S.startImage; img.hidden = false; return; }
      const n = S.passes.frames.length;
      slider.max = String(n - 1); S.frame = Math.min(S.frame, n - 1); slider.value = String(S.frame);
      const src = S.passes.frames[S.frame][k];
      if (!src) { empty.hidden = false; return; }
      cv.width = src.width; cv.height = src.height; cv.getContext("2d").drawImage(src, 0, 0); cv.hidden = false;
      $("rs-flabel").textContent = "frame " + S.passes.frames[S.frame].frame + " (" + (S.frame + 1) + "/" + n + ")";
      return;
    }
    const m = S.jobView;
    if (!m) { empty.hidden = false; slider.max = "0"; $("rs-flabel").textContent = ""; return; }
    if (k === "result") {
      const name = (m.outputs || [])[0];
      if (!name) { empty.hidden = false; return; }
      const url = await fileURL(S.jobId, name);
      if (/\.(webm|mp4)$/i.test(name)) { vid.src = url; vid.hidden = false; } else { img.src = url; img.hidden = false; }
      slider.max = "0"; $("rs-flabel").textContent = name;
      return;
    }
    const p = (m.passes || {})[k];
    if (!p) { empty.hidden = false; return; }
    slider.max = String(Math.max(0, p.frames - 1)); S.frame = Math.min(S.frame, p.frames - 1); slider.value = String(S.frame);
    const url = await fileURL(S.jobId, "passes/" + k + "/" + String(S.frame).padStart(4, "0") + ".png");
    if (url) { img.src = url; img.hidden = false; }
    $("rs-flabel").textContent = k + " " + (S.frame + 1) + "/" + p.frames;
  }

  async function testConn() {
    const r = await call("/render/test", { url: $("rs-url").value.trim() });
    say(r.ok ? "Connected: ComfyUI " + (r.version || "?") + " on " + (r.os || "?") + ", " + (r.gpu || "no GPU reported") + (r.vram_total ? " (" + fmtGB(r.vram_total) + ")" : "") + " - " + r.where.note + "." : (r.error || "no answer"), !r.ok);
    return r;
  }
  async function saveServer() {
    const r = await call("/render/settings", { url: $("rs-url").value.trim(), consent_remote: $("rs-consent").checked });
    say(r.ok ? "Saved: " + r.settings.url_shown + " (" + r.settings.where.note + ")." : r.error, !r.ok);
    refresh();
  }
  async function loadPresets() {
    const r = await call("/render/presets?project=" + encodeURIComponent($("rs-project").value || "forge"));
    const s = $("rs-preset"); s.replaceChildren(new Option("-", ""));
    for (const n of Object.keys((r && r.presets) || {})) s.append(new Option(n, n));
    S.presets = (r && r.presets) || {};
  }
  async function savePreset() {
    const name = $("rs-preset-name").value.trim() || $("rs-preset").value;
    if (!name) { say("Give the preset a name.", true); return; }
    const r = await call("/render/presets", { project: $("rs-project").value || "forge", name, params: collect() });
    say(r.ok ? "Preset '" + name + "' saved." : r.error, !r.ok); loadPresets();
  }
  function loadPreset() { const n = $("rs-preset").value; if (n && S.presets && S.presets[n]) { apply(S.presets[n]); say("Preset '" + n + "' loaded."); } }
  async function deletePreset() {
    const n = $("rs-preset").value; if (!n) return;
    if (!window.confirm("Delete the preset '" + n + "'?")) return;
    await call("/render/presets", { project: $("rs-project").value || "forge", name: n, params: null }); loadPresets();
  }

  // ------------------------------------------------------------------ start image
  function setStart(url) {
    S.startImage = url;
    const t = $("rs-startthumb"); t.hidden = !url; if (url) t.src = url;
  }
  function loadStartFile(f) {
    if (!/^image\/(png|jpeg|webp)$/.test(f.type)) { say("Pick a PNG, JPEG or WebP picture.", true); return; }
    const fr = new FileReader();
    fr.onload = () => {   // re-encode as PNG (ComfyUI's upload is stored as given; one format keeps it simple)
      const im = new Image();
      im.onload = () => { const c = document.createElement("canvas"); c.width = im.naturalWidth; c.height = im.naturalHeight; c.getContext("2d").drawImage(im, 0, 0); setStart(c.toDataURL("image/png")); };
      im.src = fr.result;
    };
    fr.readAsDataURL(f);
  }
  async function ensureForge() {
    if (typeof forge !== "undefined" && forge && forge.view) return forge.view;
    if (typeof forgeBuild === "function" && typeof forgeViewer === "function") {
      try { forgeBuild(); const v = await forgeViewer(); if (v && v.start) v.start(); return v; } catch (e) { console.warn("render studio: forge", e); }
    }
    return null;
  }
  async function startFromForge() {
    if (!(await ensureForge())) { say("Open Forge first.", true); return; }
    const s = collect();
    const c = await window.ForgePasses.snapshot(s.width, s.height);
    if (c) { setStart(c.toDataURL("image/png")); say("Start image taken from Forge's view."); }
  }

  // ------------------------------------------------------------------ passes, preflight, jobs
  async function renderPasses(forJob) {
    if (!window.ForgePasses) { say("Forge's pass renderer is not loaded.", true); return null; }
    if (!(await ensureForge())) { say("Open Forge first: the passes come from its scene.", true); return null; }
    const s = collect();
    if (!s.passes.length) { say("Tick at least one pass.", true); return null; }
    say("Rendering passes...");
    const res = await window.ForgePasses.render({ camera: s.camera, passes: s.passes, width: s.width, height: s.height, start: s.start, end: s.end, step: s.step,
      lineWidth: s.lineWidth, normalEdge: s.crease, onProgress: (f) => say("Rendering passes... " + Math.round(f * 100) + "%") });
    S.passes = res; S.frame = 0; S.jobView = null;
    tabs(res.passes.concat(S.startImage ? ["start"] : []), res.passes.includes("lineart") ? "lineart" : res.passes[0]);
    showPreview();
    say("Passes: " + res.frames.length + " frames at " + res.width + "x" + res.height + " from " + res.camera + " (depth " + res.near.toFixed(2) + " - " + res.far.toFixed(2) + ").");
    return forJob ? res : res;
  }

  async function runPreflight() {
    const s = collect();
    const r = await call("/render/preflight", { workflow: s.workflow, params: aiParams(s), control: s.control, job: S.lastAiJob || null });
    showReport(r.ok ? r.report : { blockers: [r.error || "no answer"], warnings: [], checked: [] });
    return r;
  }
  function showReport(rep) {
    S.report = rep;
    const box = $("rs-report"); box.replaceChildren();
    box.className = "rs-report " + (rep.ok ? "good" : "bad");
    box.append(mk("h4", "", rep.ok ? "Ready" : "Not ready yet"));
    const ul = mk("ul");
    for (const b of rep.blockers || []) ul.append(mk("li", "blk", b));
    for (const w of rep.warnings || []) ul.append(mk("li", "wrn", w));
    for (const c of rep.checked || []) ul.append(mk("li", "okk", c));
    box.append(ul);
    for (const mm of rep.missing_models || []) {
      const d = mk("div", "rs-missing");
      d.append(mk("b", "", mm.file), mk("span", "", " -> ComfyUI/" + mm.folder + (mm.size ? " (" + fmtGB(mm.size) + ")" : "") + (mm.license ? " · licence: " + mm.license : "")));
      if (mm.url) { const a = mk("a", "", " download"); a.href = mm.url; a.target = "_blank"; a.rel = "noopener noreferrer"; d.append(a); }
      box.append(d);
    }
    for (const mn of rep.missing_nodes || []) {
      const d = mk("div", "rs-missing"); d.append(mk("b", "", mn.class), mk("span", "", mn.pack ? " from " + mn.pack + (mn.license ? " (" + mn.license + ")" : "") + " -> ComfyUI/custom_nodes" : " (a core node: update ComfyUI)"));
      box.append(d);
    }
    if (rep.gpu && rep.gpu.name) box.append(mk("p", "rs-note", "GPU: " + rep.gpu.name + (rep.gpu.vram_total ? " · " + fmtGB(rep.gpu.vram_total) : "")));
  }

  function dataURLtoBlob(u) {
    const [head, b64] = u.split(","); const bin = atob(b64); const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    return new Blob([arr], { type: (head.match(/data:([^;]+)/) || [])[1] || "image/png" });
  }

  async function startJob() {
    const s = collect();
    if (S.engine === "path") return startPathJob(s);
    const needs = s.control === "depth" ? ["depth"] : s.control === "lineart" ? ["lineart"] : ["depth", "lineart"];
    for (const k of needs) if ($("rs-pass-" + k)) $("rs-pass-" + k).checked = true;
    const made = await call("/render/new", { kind: "ai", name: s.name || "", workflow: s.workflow, params: aiParams(s), control: s.control, fps: s.fps,
      size: [s.width, s.height], frames: s.frames, camera: s.camera, range: { start: s.start, end: s.end, step: s.step }, project: $("rs-project").value });
    if (!made.ok) { say(made.error, true); return; }
    const job = made.job; S.lastAiJob = job;
    try {
      const res = (S.passes && S.passes.width === s.width && S.passes.height === s.height && needs.every((k) => S.passes.passes.includes(k))) ? S.passes : await renderPasses(true);
      if (!res) return;
      const only = Object.assign({}, res, { passes: res.passes.filter((p) => needs.includes(p) || p === "beauty") });
      await window.ForgePasses.upload(job, only, (f) => say("Sending passes... " + Math.round(f * 100) + "%"));
      if (S.startImage) {
        const r = await fetch("/render/upload-pass?job=" + encodeURIComponent(job) + "&pass=start&index=0", { method: "POST", headers: { Authorization: "Bearer " + token(), "Content-Type": "image/png" }, body: dataURLtoBlob(S.startImage) });
        const j = await r.json(); if (!j.ok) throw new Error(j.error);
      }
    } catch (e) { say("Could not prepare the job: " + e.message, true); await call("/render/cancel", { job }); refresh(); return; }
    const pf = await call("/render/preflight", { workflow: s.workflow, params: aiParams(s), control: s.control, job });
    if (pf.ok) showReport(pf.report);
    if (!pf.ok || !pf.report.ok) { say("Preflight found problems; the job waits (fix them and press Render again).", true); await call("/render/cancel", { job }); refresh(); return; }
    const st = await call("/render/start", { job });
    say(st.ok ? "Queued. Progress shows on the left." : st.error, !st.ok);
    S.sel = job; refresh();
  }

  async function startPathJob(s) {
    if (!window.ForgeRender || !window.ForgeRender.isAvailable || !window.ForgeRender.isAvailable()) { say("Forge's path tracer is not available in this window (it needs WebGL2 with float targets).", true); return; }
    if (!(await ensureForge())) { say("Open Forge first.", true); return; }
    const made = await call("/render/new", { kind: "path", name: s.name || "", fps: s.fps, size: [s.width, s.height], camera: s.camera,
      frames: Math.floor((s.end - s.start) / Math.max(1, s.step)) + 1, range: { start: s.start, end: s.end, step: s.step }, project: $("rs-project").value });
    if (!made.ok) { say(made.error, true); return; }
    const job = made.job; let i = 0;
    S.sel = job; refresh();
    const seq = window.ForgeRender.renderSequence({ start: s.start, end: s.end, step: s.step, width: s.width, height: s.height, res: "custom",
      camera: s.camera, samples: s.samples, bounces: s.bounces,
      onFrame: async (res) => {
        const blob = res.dataURL ? dataURLtoBlob(res.dataURL) : await new Promise((r) => res.canvas.toBlob(r, "image/png"));
        await fetch("/render/upload-pass?job=" + encodeURIComponent(job) + "&pass=beauty&index=" + (i++), { method: "POST", headers: { Authorization: "Bearer " + token(), "Content-Type": "image/png" }, body: blob });
      } });
    S.running = { job, seq };
    let status = "succeeded"; const log = [];
    try { await seq.done; if (seq.stopped) status = "cancelled"; } catch (e) { status = "failed"; log.push(e.message); }
    await new Promise((r) => setTimeout(r, 200));
    await call("/render/finish", { job, status, log });
    S.running = null; refresh(); select(job);
  }

  async function cancelJob(job) {
    if (S.running && S.running.job === job) { S.running.seq.stop(); return; }
    const r = await call("/render/cancel", { job }); if (!r.ok) say(r.error, true); refresh();
  }
  async function retryJob(job) { const r = await call("/render/retry", { job }); if (!r.ok) { say(r.error, true); return; } S.sel = r.job; await call("/render/start", { job: r.job }); refresh(); }

  function say(text, bad) {
    const i = $("rs-info"); if (!i) return;
    i.textContent = text; i.classList.toggle("bad", !!bad);
  }

  // ------------------------------------------------------------------ the tab
  function open(p, opts) {
    if (!S.built || S.pane !== p) build(p);
    refresh(); loadPresets();
    clearInterval(S.timer);
    S.timer = setInterval(() => { if (S.pane && !S.pane.hidden && !document.hidden) refresh(); }, 2500);
    show(opts);
  }
  function show(opts) {
    if (opts && opts.job) select(opts.job);
    if (opts && opts.fromForge && $("rs-start")) { const t = forgeTime(); $("rs-start").value = t.start; $("rs-end").value = t.end; $("rs-camera").value = "current"; }
  }
  function leave() { clearInterval(S.timer); S.timer = 0; }

  // ------------------------------------------------------------------ the Render View: its own menu bar and a
  // batch-render progress panel, the way a 3D app's render view carries File / View / Render.
  function menu(label, items, id) {
    const wrap = mk("div", "rs-menu"); wrap.id = id;
    const b = mk("button", "rs-menubtn", label); b.type = "button"; b.dataset.menu = label.toLowerCase();
    const list = mk("div", "rs-menulist"); list.hidden = true; list.dataset.for = label.toLowerCase();
    for (const it of items) {
      if (!it) { list.append(mk("div", "rs-menusep")); continue; }
      const mi = mk("button", "rs-menuitem", it[0]); mi.type = "button"; mi.dataset.item = it[0];
      if (it[2]) mi.dataset.kind = it[2];
      mi.addEventListener("click", (e) => { e.stopPropagation(); closeMenus(); it[1](); });
      list.append(mi);
    }
    b.addEventListener("click", (e) => { e.stopPropagation(); const was = !list.hidden; closeMenus(); list.hidden = was; });
    wrap.append(b, list);
    return wrap;
  }
  function closeMenus() { for (const l of document.querySelectorAll(".rs-menulist")) l.hidden = true; }
  if (!window.__rsMenuClose) { window.__rsMenuClose = true; document.addEventListener("click", closeMenus); document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenus(); }); }

  function liveJob() {
    const live = (S.jobs || []).filter((j) => j && !["succeeded", "failed", "cancelled", "idle"].includes(j.status));
    return live.find((j) => j.job === S.sel) || live[0] || null;
  }
  function updateProgress() {
    const el = $("rs-progress"); if (!el) return;
    const j = liveJob();
    el.hidden = !j;
    if (!j) { S.pt0 = null; S.ptjob = null; return; }
    if (!S.pt0 || S.ptjob !== j.job) { S.pt0 = Date.now(); S.ptjob = j.job; }
    const p = Math.max(0, Math.min(1, Number(j.progress) || 0));
    $("rs-progress-name").textContent = (j.name || j.job) + " - " + j.status;
    $("rs-progress-bar").style.width = Math.round(p * 100) + "%";
    $("rs-progress-pct").textContent = Math.round(p * 100) + "%";
    const secs = Math.max(0, Math.round((Date.now() - S.pt0) / 1000));
    $("rs-progress-last").textContent = (j.last || "") + (secs > 1 ? "   (" + Math.floor(secs / 60) + "m " + (secs % 60) + "s)" : "");
  }
  function setFit(on) { const st = $("rs-stage"); if (st) st.classList.toggle("rs-actual", !on); }
  function shownSrc() {
    const im = $("rs-img"), v = $("rs-video");
    if (v && !v.hidden && v.getAttribute("src")) return v.getAttribute("src");
    return (im && !im.hidden && im.getAttribute("src")) || null;
  }
  function clearKeep() { S.keep = null; const box = $("rs-held"); if (box) { box.hidden = true; box.removeAttribute("src"); } }
  function toggleKeep() {
    if (S.keep) { clearKeep(); say("Let go of the kept image."); return; }
    const src = shownSrc(); if (!src) { say("Nothing is shown to keep yet.", true); return; }
    S.keep = src;
    const box = $("rs-held"); if (box) { box.src = src; box.hidden = false; }
    say("Kept this image - Keep image again lets go of it.");
  }
  function saveImage() {
    const src = shownSrc();
    if (!src) { say("Nothing is shown to save yet - render, or pick a job on the left.", true); return; }
    const a = document.createElement("a");
    a.href = src;
    a.download = String((S.sel || "render") + (/[.](webm|mp4)([?#]|$)/.test(src) ? ".webm" : ".png")).replace(/[^\w.-]+/g, "_");
    document.body.append(a); a.click(); a.remove();
    say("Saving " + a.download + ".");
  }
  function showEmpty() {
    const e = $("rs-empty"); if (e) e.hidden = false;
    const i = $("rs-img"); if (i) i.hidden = true;
    const v = $("rs-video"); if (v) v.hidden = true;
  }
  // ------------------------------------------------------------------ the Nodes view: the workflow drawn as a node
  // graph (like a ComfyUI canvas), so the render reads as a pipeline, not a form. Node colours come from the last
  // Preflight report: red = a missing node class or model file, green = ready, grey = not checked yet.
  function toggleNodes() {
    S.node = !S.node;
    const b = $("rs-nodes"); if (b) b.classList.toggle("on", S.node);
    if (S.node) { showNodes(); } else { const w = $("rs-graphwrap"); if (w) w.hidden = true; showPreview(); }
  }
  function shortTitle(t) { t = String(t || "?"); return t.length > 22 ? t.slice(0, 21) + "…" : t; }
  function showNodeInfo(n) {
    const lines = [n.class + "  (" + n.title + ")"];
    const ins = Object.entries(n.inputs || {});
    if (ins.length) lines.push("inputs: " + ins.map(([k, v]) => k + "=" + String(v).slice(0, 24)).join(", "));
    for (const m of n.models || []) lines.push("model: " + m.file + "  -> ComfyUI/" + m.folder);
    say(lines.join("\n"));
  }
  async function showNodes() {
    const wrap = $("rs-graphwrap"); if (!wrap) return;
    $("rs-img").hidden = true; $("rs-canvas").hidden = true; $("rs-video").hidden = true; $("rs-empty").hidden = true;
    wrap.hidden = false;
    const wf = ($("rs-wf") && $("rs-wf").value) || "vace_render";
    if (!S.graph || S.graph.workflow !== wf) {
      const r = await call("/render/graph?workflow=" + encodeURIComponent(wf));
      if (!r || !r.ok) { wrap.replaceChildren(mk("p", "rs-note", (r && r.error) || "Could not read the graph.")); return; }
      S.graph = r;
    }
    drawGraph(wrap, S.graph);
    say("Nodes: " + S.graph.nodes.length + " blocks (" + wf + "). Click a block for its inputs. " +
        (S.report ? "Green = ready, red = missing." : "Press Preflight to colour it."));
  }
  function drawGraph(wrap, g) {
    const NS = "http://www.w3.org/2000/svg";
    const nodes = g.nodes || [], byId = new Map(nodes.map((n) => [n.id, n]));
    const rank = {}; for (const n of nodes) rank[n.id] = 0;
    for (let it = 0; it < nodes.length + 2; it++) {
      let moved = false;
      for (const n of nodes) for (const l of n.links) if (byId.has(l.from) && rank[l.from] + 1 > rank[n.id]) { rank[n.id] = rank[l.from] + 1; moved = true; }
      if (!moved) break;
    }
    const cols = {};
    for (const n of nodes) { const r = rank[n.id]; if (!cols[r]) cols[r] = []; cols[r].push(n); }
    const NW = 172, NH = 62, GX = 74, GY = 24, M = 22;
    const pos = {}; let maxX = 0, maxY = 0;
    for (const r of Object.keys(cols).map(Number).sort((a, b) => a - b)) {
      let y = M;
      for (const n of cols[r]) { const x = M + r * (NW + GX); pos[n.id] = { x, y }; y += NH + GY; maxY = Math.max(maxY, y); }
      maxX = Math.max(maxX, M + r * (NW + GX) + NW);
    }
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("width", String(maxX + M)); svg.setAttribute("height", String(maxY + M));
    svg.setAttribute("class", "rs-graph");
    const badClasses = new Set(((S.report && S.report.missing_nodes) || []).map((m) => m.class));
    const badModels = new Set(((S.report && S.report.missing_models) || []).map((m) => m.file));
    const hasReport = !!S.report;
    for (const n of nodes) for (const l of n.links) {
      if (!byId.has(l.from)) continue;
      const a = pos[l.from], b = pos[n.id], x1 = a.x + NW, y1 = a.y + NH / 2, x2 = b.x, y2 = b.y + NH / 2, mx = (x1 + x2) / 2;
      const path = document.createElementNS(NS, "path");
      path.setAttribute("d", "M " + x1 + " " + y1 + " C " + mx + " " + y1 + ", " + mx + " " + y2 + ", " + x2 + " " + y2);
      path.setAttribute("class", "rs-graph-edge"); svg.append(path);
    }
    for (const n of nodes) {
      const q = pos[n.id];
      const bad = badClasses.has(n.class) || (n.models || []).some((m) => badModels.has(m.file));
      const grp = document.createElementNS(NS, "g");
      grp.setAttribute("class", "rs-graph-node " + (hasReport ? (bad ? "bad" : "ok") : ""));
      grp.dataset.id = n.id;
      const rect = document.createElementNS(NS, "rect");
      rect.setAttribute("x", q.x); rect.setAttribute("y", q.y); rect.setAttribute("rx", 9);
      rect.setAttribute("width", NW); rect.setAttribute("height", NH);
      const t1 = document.createElementNS(NS, "text");
      t1.setAttribute("x", q.x + 11); t1.setAttribute("y", q.y + 22); t1.textContent = shortTitle(n.title);
      const t2 = document.createElementNS(NS, "text");
      t2.setAttribute("x", q.x + 11); t2.setAttribute("y", q.y + 39); t2.setAttribute("class", "rs-graph-sub"); t2.textContent = n.class;
      const t3 = document.createElementNS(NS, "text");
      t3.setAttribute("x", q.x + 11); t3.setAttribute("y", q.y + 54); t3.setAttribute("class", "rs-graph-sub");
      t3.textContent = (n.models || []).length ? "model: " + shortTitle((n.models[0].file || "").replace(/\.(gguf|safetensors)$/, "")) : Object.keys(n.inputs || {}).length + " inputs";
      grp.append(rect, t1, t2, t3);
      grp.addEventListener("click", () => showNodeInfo(n));
      svg.append(grp);
    }
    const inner = mk("div", "rs-graph-inner"); inner.append(svg);
    wrap.replaceChildren(inner);
  }

  function buildViewBar(bar) {
    const held = mk("img", "rs-held"); held.id = "rs-held"; held.alt = "kept image"; held.hidden = true;
    bar.append(
      menu("File", [["Save image...", saveImage, "save"], null,
                    ["Reload", () => refresh(), "reload"],
                    ["Close the view", () => { clearKeep(); S.sel = null; renderJobs(); showEmpty(); }, "close"]], "rs-menu-file"),
      menu("View", [["Fit to window", () => setFit(true), "fit"],
                    ["Actual size", () => setFit(false), "actual"], null,
                    ["Keep image", toggleKeep, "keep"],
                    ["Let go of the kept image", clearKeep, "unkeep"]], "rs-menu-view"),
      menu("Render", [["Render", () => startJob(), "render"],
                      ["Preflight", () => runPreflight(), "preflight"], null,
                      ["Cancel", () => { const j = liveJob(); if (j) cancelJob(j.job); }, "cancel"],
                      ["Retry", () => { if (S.sel) retryJob(S.sel); }, "retry"]], "rs-menu-render"),
      btn("connections", "Nodes", "Show this workflow as a node graph: the blocks it runs, how they are wired and what is missing.", toggleNodes, "rs-nodes"),
      held);
  }

  return { open, show, leave, enter: open, refresh, renderPasses, collect, apply, aiParams, state: S, select, startJob, runPreflight };
})();
window.LokiRenderStudio = LokiRenderStudio;
if (window.LokiModeBar && typeof window.LokiModeBar.register === "function") {
  window.LokiModeBar.register("render", { enter: (p, o) => LokiRenderStudio.open(p, o), leave: () => LokiRenderStudio.leave() });
}
