//! lokid - LOKI's driver daemon.
//!
//! Runs long jobs in the background, apart from any project and apart from the
//! app window, so one prompt can keep working for hours. The window (a web
//! page this daemon serves), the phone and the other machine all talk to it
//! over a small local HTTP API.
//!
//!   lokid serve            start the daemon (default)
//!   lokid probe            check which free providers answer on this machine
//!   lokid run "<goal>"     run one job in the foreground (handy over SSH)

mod link;

use axum::{
    body::Body,
    extract::{Path as AxPath, Query, Request, State},
    http::{header, HeaderMap, Method, StatusCode, Uri},
    middleware::{self, Next},
    response::{Html, IntoResponse, Response},
    routing::{any, get, post},
    Json, Router,
};
use loki_core::agent::Driver;
use loki_core::journal::{Journal, OwnerReply, Status};
use loki_core::pool::ModelPool;
use loki_core::tools::confine;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use tokio::sync::Mutex;

const DEFAULT_PROVIDERS: &str = include_str!("../providers.default.toml");
/// Local model catalog carried over from the previous LOKI (standard + abliterated builds).
const CATALOG: &str = include_str!("../models.catalog.json");
const UI: &str = include_str!("../../../app/ui/index.html");

#[derive(Clone)]
struct App {
    home: PathBuf,
    driver: Arc<Driver>,
    live: Arc<Mutex<HashMap<String, Arc<AtomicBool>>>>,
    /// model name -> download progress (Ollama pulls started from the window)
    pulls: Arc<Mutex<HashMap<String, Value>>>,
    /// The Mac <-> PC link (None when this machine has no LOKI_PEER_SECRET).
    link: Option<link::Link>,
}

fn default_settings() -> Value {
    json!({"theme": "glass", "accent": null, "interview": "always", "scale": 1.0, "thumb": 110, "notify": true})
}

impl App {
    fn settings(&self) -> Value {
        let mut base = default_settings();
        if let Some(saved) = std::fs::read_to_string(self.home.join("settings.json")).ok().and_then(|t| serde_json::from_str::<Value>(&t).ok()) {
            if let (Some(b), Some(o)) = (base.as_object_mut(), saved.as_object()) {
                for (k, v) in o {
                    b.insert(k.clone(), v.clone());
                }
            }
        }
        base
    }
}

/// LOKI_HOME holds runs, providers and pool state. The launcher points it at
/// `<checkout>/harness_data/home` (the external drive on the Mac, D: on the PC).
fn home() -> PathBuf {
    if let Ok(h) = std::env::var("LOKI_HOME") {
        return PathBuf::from(h);
    }
    let base = std::env::var("HOME").or_else(|_| std::env::var("USERPROFILE")).unwrap_or_else(|_| ".".into());
    PathBuf::from(base).join(".loki")
}

/// The LOKI checkout (playbooks, tools): LOKI_REPO from the launcher, else two levels above the binary's build dir.
fn repo_dir() -> Option<PathBuf> {
    if let Ok(r) = std::env::var("LOKI_REPO") {
        return Some(PathBuf::from(r));
    }
    let exe = std::env::current_exe().ok()?;
    exe.ancestors().find(|a| a.join("playbooks").is_dir() && a.join("crates").is_dir()).map(Path::to_path_buf)
}

/// The built-in free providers always apply (so every update brings the newest list);
/// <home>/providers.local.toml adds providers or overrides one by name. A providers.toml left by
/// an older LOKI (a copy of the defaults it shipped with) is moved aside once.
fn load_pool(home: &Path) -> anyhow::Result<ModelPool> {
    std::fs::create_dir_all(home)?;
    load_dotenv(&home.join(".env"));
    let old = home.join("providers.toml");
    if old.exists() {
        let _ = std::fs::rename(&old, home.join("providers.old.toml"));
    }
    #[derive(Deserialize)]
    struct File {
        #[serde(default)]
        provider: Vec<loki_core::pool::Provider>,
    }
    let mut list: Vec<loki_core::pool::Provider> = toml::from_str::<File>(DEFAULT_PROVIDERS)?.provider;
    let local = home.join("providers.local.toml");
    if let Ok(text) = std::fs::read_to_string(&local) {
        match toml::from_str::<File>(&text) {
            Ok(f) => {
                for p in f.provider {
                    if let Some(slot) = list.iter_mut().find(|x| x.name == p.name) { *slot = p; } else { list.push(p); }
                }
            }
            Err(e) => tracing::warn!("providers.local.toml ignored: {e}"),
        }
    }
    Ok(ModelPool::with_state(list, &home.join("pool_state.json")))
}

/// Minimal KEY=VALUE reader so keys can live next to the data, not in the shell.
fn load_dotenv(path: &Path) {
    let Ok(s) = std::fs::read_to_string(path) else { return };
    for line in s.lines() {
        let line = line.trim();
        if line.starts_with('#') {
            continue;
        }
        if let Some((k, v)) = line.split_once('=') {
            let k = k.trim().trim_start_matches("export ").trim();
            if !k.is_empty() && std::env::var(k).is_err() {
                std::env::set_var(k, v.trim().trim_matches('"').trim_matches('\''));
            }
        }
    }
}

impl App {
    fn runs_dir(&self) -> PathBuf {
        self.home.join("runs")
    }

    async fn spawn(&self, id: String) {
        if self.live.lock().await.contains_key(&id) {
            return; // already working
        }
        let stop = Arc::new(AtomicBool::new(false));
        self.live.lock().await.insert(id.clone(), stop.clone());
        let me = self.clone();
        tokio::spawn(async move {
            let j = Journal::open(&me.runs_dir().join(&id));
            match me.driver.run(&j, stop).await {
                Ok(info) => tracing::info!("run {id} -> {:?}", info.status),
                Err(e) => {
                    tracing::error!("run {id} crashed: {e}");
                    if let Ok(mut info) = j.info() {
                        info.status = Status::Failed;
                        info.last_error = Some(e.to_string());
                        let _ = j.save_info(&info);
                    }
                }
            }
            me.live.lock().await.remove(&id);
            // live sessions stay open while a job waits for the owner or rests; otherwise they close with it
            let st = Journal::open(&me.runs_dir().join(&id)).info().map(|i| i.status).ok();
            if !matches!(st, Some(Status::Waiting) | Some(Status::Resting) | Some(Status::Running)) {
                me.driver.sessions.close(&id).await;
            }
        });
    }
}

#[derive(Deserialize, Default)]
struct NewRun {
    goal: String,
    workspace: Option<PathBuf>,
    max_steps: Option<u64>,
    max_hours: Option<f64>,
    #[serde(default)]
    mode: Option<String>,
    #[serde(default)]
    prefer: Option<String>,
    #[serde(default)]
    attach: Vec<Value>,
    /// Override the interview setting for this job ("always" | "big" | "off").
    #[serde(default)]
    interview: Option<String>,
}

async fn create_run(State(app): State<App>, Json(req): Json<NewRun>) -> Result<Json<Value>, (StatusCode, String)> {
    app.new_run(req).await.map(Json)
}

impl App {
    async fn new_run(&self, req: NewRun) -> Result<Value, (StatusCode, String)> {
    let app = self;
    if req.goal.trim().is_empty() {
        return Err((StatusCode::BAD_REQUEST, "goal is empty".into()));
    }
    // Each run gets its own folder unless the owner points it at a project.
    let ws_root = app.home.join("work");
    let (j, mut info) = Journal::create(&app.runs_dir(), &req.goal, &ws_root, req.max_steps.unwrap_or(2000), req.max_hours.unwrap_or(12.0))
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    info.workspace = req.workspace.unwrap_or_else(|| ws_root.join(&info.id));
    info.mode = match req.mode.as_deref() { Some("smart") | Some("hard") => "smart", _ => "auto" }.into();
    info.interview = req.interview.clone().filter(|v| matches!(v.as_str(), "always" | "big" | "off"))
        .unwrap_or_else(|| app.settings()["interview"].as_str().unwrap_or("always").to_string());
    info.prefer = req.prefer.filter(|p| !p.is_empty());
    let _ = std::fs::create_dir_all(&info.workspace);
    let files = app.attach(&info.workspace, &req.attach);
    if !files.is_empty() {
        // the goal message carries the attachments so the model and the chat both see them
        let _ = std::fs::remove_file(j.dir.join("chat.jsonl"));
        let goal = format!("{}\n\nAttached references: {}", req.goal.trim(), files.join(", "));
        info.goal = goal.clone();
        j.say("owner", &goal, files);
    }
    j.save_info(&info).map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    app.spawn(info.id.clone()).await;
    Ok(json!(info))
    }

    /// Copy attachments into the job's `refs/` folder: `{"upload": "<id>/<name>"}` from a drop,
    /// or `{"run": "<id>", "path": "..."}` for an image dragged from the library.
    fn attach(&self, ws: &Path, list: &[Value]) -> Vec<String> {
        let mut out = Vec::new();
        let refs = ws.join("refs");
        for a in list {
            let src = if let Some(u) = a["upload"].as_str() {
                confine(&self.home.join("uploads"), u).ok()
            } else if let Some(m) = a["mirror"].as_str() {
                confine(&self.home.join("mirror"), m).ok()
            } else if let (Some(run), Some(p)) = (a["run"].as_str(), a["path"].as_str()) {
                Journal::open(&self.runs_dir().join(safe_name(run))).info().ok().and_then(|i| confine(&i.workspace, p).ok())
            } else {
                None
            };
            let Some(src) = src.filter(|s| s.is_file()) else { continue };
            let name = safe_name(&src.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default());
            let mut dest = refs.join(&name);
            let mut n = 1;
            while dest.exists() && std::fs::metadata(&dest).map(|m| m.len()).ok() != std::fs::metadata(&src).map(|m| m.len()).ok() {
                n += 1;
                dest = refs.join(format!("{n}-{name}"));
            }
            if std::fs::create_dir_all(&refs).is_ok() && (dest.exists() || std::fs::copy(&src, &dest).is_ok()) {
                out.push(format!("refs/{}", dest.file_name().unwrap().to_string_lossy()));
            }
        }
        out
    }

    async fn say(&self, id: &str, text: &str) -> StatusCode {
        self.say_with(id, text, vec![]).await
    }

    /// An owner chat message: steer a working job, answer a question, or reopen a finished one.
    async fn say_with(&self, id: &str, text: &str, files: Vec<String>) -> StatusCode {
        let j = Journal::open(&self.runs_dir().join(id));
        let Ok(mut info) = j.info() else { return StatusCode::NOT_FOUND };
        let mut text = text.trim().to_string();
        if !files.is_empty() {
            text = format!("{text}\n\nAttached references: {}", files.join(", ")).trim().to_string();
        }
        if text.is_empty() {
            return StatusCode::BAD_REQUEST;
        }
        let text = text.as_str();
        j.say("owner", text, files);
        if info.status == Status::Waiting {
            let is_question = info.pending.as_ref().and_then(|p| p["name"].as_str()) == Some("ask_owner");
            if is_question || info.pending.is_none() {
                // typing in the chat answers the question; the message is also counted as read
                info.owner_seen += 1;
                info.owner_reply = Some(OwnerReply { approve: true, note: text.into() });
                let _ = j.save_info(&info);
                self.spawn(id.to_string()).await;
            }
            return StatusCode::OK; // an approval card still waits for its own button
        }
        if !self.live.lock().await.contains_key(id) {
            info.status = Status::Running;
            let _ = j.save_info(&info);
            self.spawn(id.to_string()).await;
        }
        StatusCode::OK
    }
}

#[derive(Deserialize)]
struct SayReq {
    text: String,
    #[serde(default)]
    attach: Vec<Value>,
}

async fn say_run(State(app): State<App>, AxPath(id): AxPath<String>, Json(r): Json<SayReq>) -> StatusCode {
    let j = Journal::open(&app.runs_dir().join(&id));
    let Ok(info) = j.info() else { return StatusCode::NOT_FOUND };
    let files = app.attach(&info.workspace, &r.attach);
    app.say_with(&id, &r.text, files).await
}

/// Raw file upload (drag and drop from the computer): POST /upload?name=<file name>, body = the bytes.
async fn upload(State(app): State<App>, Query(q): Query<HashMap<String, String>>, body: axum::body::Bytes) -> Result<Json<Value>, StatusCode> {
    let name = q.get("name").map(|n| safe_name(n)).filter(|n| !n.is_empty()).unwrap_or_else(|| "file".into());
    let id = format!("{}", std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_millis()).unwrap_or(0));
    let dir = app.home.join("uploads").join(&id);
    std::fs::create_dir_all(&dir).map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    std::fs::write(dir.join(&name), &body).map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    Ok(Json(json!({"upload": format!("{id}/{name}"), "name": name, "bytes": body.len()})))
}

fn safe_name(n: &str) -> String {
    let base = n.rsplit(['/', '\\']).next().unwrap_or(n);
    base.chars().map(|c| if c.is_alphanumeric() || matches!(c, '.' | '-' | '_' | ' ') { c } else { '_' }).collect::<String>().trim().trim_start_matches('.').to_string()
}

/// The chat timeline: messages and tool cards in time order.
async fn chat_run(State(app): State<App>, AxPath(id): AxPath<String>) -> Result<Json<Value>, StatusCode> {
    let j = Journal::open(&app.runs_dir().join(&id));
    let info = j.info().map_err(|_| StatusCode::NOT_FOUND)?;
    let mut items: Vec<Value> = j.chat().into_iter().map(|c| json!({"kind": "msg", "t": c.t, "from": c.from, "text": c.text, "files": c.files})).collect();
    for s in j.steps() {
        let Some(tool) = s["tool"].as_str() else { continue };
        if matches!(tool, "tell_owner" | "finish") {
            continue; // shown as messages
        }
        let result = s["result"].as_str().unwrap_or("");
        let ok = !result.starts_with("ERROR") && !result.contains("check failed");
        items.push(json!({"kind": "tool", "t": s["t"], "step": s["step"], "tool": tool, "args": s["args"],
            "result": result, "ok": ok, "model": s["model"], "provider": s["provider"], "owner": s["owner"],
            "tin": s["tin"], "tout": s["tout"], "secs": s["secs"]}));
    }
    items.sort_by(|a, b| a["t"].as_str().unwrap_or("").cmp(b["t"].as_str().unwrap_or("")));
    let active = app.live.lock().await.contains_key(&id);
    Ok(Json(json!({"run": info, "active": active, "tasks": j.tasks(), "items": items})))
}

#[derive(Deserialize)]
struct Page {
    page: Option<usize>,
    per: Option<usize>,
    /// only this machine's own pictures (what the other machine mirrors)
    own: Option<u8>,
}

/// Every image every job made, newest first, in pages.
async fn library(State(app): State<App>, Query(q): Query<Page>) -> Json<Value> {
    let per = q.per.unwrap_or(48).clamp(1, 200);
    let page = q.page.unwrap_or(0);
    let mut all: Vec<Value> = Vec::new();
    for info in Journal::list(&app.runs_dir()) {
        for f in list_files(&info.workspace, 2000) {
            let lower = f.path.to_ascii_lowercase();
            if [".png", ".jpg", ".jpeg", ".webp", ".gif"].iter().any(|e| lower.ends_with(e)) {
                all.push(json!({"run": info.id, "title": info.title, "path": f.path, "bytes": f.bytes, "modified": f.modified}));
            }
        }
    }
    if q.own.unwrap_or(0) == 0 {
        all.extend(mirror_items(&app.home.join("mirror")));
    }
    all.sort_by(|a, b| b["modified"].as_u64().cmp(&a["modified"].as_u64()));
    let total = all.len();
    let items: Vec<Value> = all.into_iter().skip(page * per).take(per).collect();
    Json(json!({"total": total, "page": page, "per": per, "items": items}))
}

/// Pictures copied from the other machines: `<mirror>/<machine>/<run>/<path>`.
fn mirror_items(root: &Path) -> Vec<Value> {
    let mut out = Vec::new();
    let Ok(rd) = std::fs::read_dir(root) else { return out };
    for m in rd.flatten().filter(|e| e.path().is_dir()) {
        let machine = m.file_name().to_string_lossy().to_string();
        let titles: HashMap<String, String> = std::fs::read_to_string(m.path().join("titles.json")).ok()
            .and_then(|t| serde_json::from_str(&t).ok()).unwrap_or_default();
        for f in list_files(&m.path(), 5000) {
            let lower = f.path.to_ascii_lowercase();
            if ![".png", ".jpg", ".jpeg", ".webp", ".gif"].iter().any(|e| lower.ends_with(e)) { continue; }
            let (run, path) = f.path.split_once('/').unwrap_or(("", &f.path));
            let rel = format!("{machine}/{}", f.path);
            out.push(json!({"run": run, "title": titles.get(run).cloned().unwrap_or_default(), "path": path, "bytes": f.bytes,
                "modified": f.modified, "machine": machine, "mirror": rel, "src": format!("/mirror/file?path={}", link::enc(&rel))}));
        }
    }
    out
}

async fn mirror_file(State(app): State<App>, Query(q): Query<FileQuery>) -> Response {
    let Ok(p) = confine(&app.home.join("mirror"), &q.path) else { return StatusCode::FORBIDDEN.into_response() };
    match tokio::fs::read(&p).await {
        Ok(bytes) => ([(header::CONTENT_TYPE, mime(&q.path)), (header::CACHE_CONTROL, "max-age=3600")], Body::from(bytes)).into_response(),
        Err(_) => StatusCode::NOT_FOUND.into_response(),
    }
}

// ------------------------------------------------------------- the link (Mac <-> PC)

/// Every request on the peer port must carry this machine pair's signature.
async fn peer_auth(State(app): State<App>, req: Request, next: Next) -> Response {
    let Some(l) = app.link.clone() else { return StatusCode::NOT_FOUND.into_response() };
    let (parts, body) = req.into_parts();
    let Ok(bytes) = axum::body::to_bytes(body, 512 * 1024 * 1024).await else { return StatusCode::PAYLOAD_TOO_LARGE.into_response() };
    let h = |k: &str| parts.headers.get(k).and_then(|v| v.to_str().ok()).unwrap_or("").to_string();
    let pq = parts.uri.path_and_query().map(|p| p.as_str().to_string()).unwrap_or_else(|| "/".into());
    match l.verify(parts.method.as_str(), &pq, &h(link::H_NAME), &h(link::H_TIME), &h(link::H_SIG), &bytes) {
        Ok(_) => next.run(Request::from_parts(parts, Body::from(bytes))).await,
        Err(e) => {
            tracing::warn!("link: refused {} {pq}: {e}", parts.method);
            (StatusCode::UNAUTHORIZED, e).into_response()
        }
    }
}

/// The last lines of this machine's logs (driver, launcher, build) - shared with the other machine and the window.
async fn logs(State(app): State<App>, Query(q): Query<HashMap<String, String>>) -> Json<Value> {
    let n: usize = q.get("lines").and_then(|v| v.parse().ok()).unwrap_or(200).min(2000);
    let mut out = serde_json::Map::new();
    for name in ["lokid.log", "launcher.log", "build.log"] {
        let text = std::fs::read_to_string(app.home.join(name)).unwrap_or_default();
        let lines: Vec<&str> = text.lines().collect();
        out.insert(name.into(), json!(lines[lines.len().saturating_sub(n)..].join("\n")));
    }
    Json(Value::Object(out))
}

async fn hello(State(app): State<App>) -> Json<Value> {
    let gpu = std::env::var("LOKI_GPU").ok();
    Json(json!({"name": app.link.as_ref().map(|l| l.name.clone()), "version": env!("CARGO_PKG_VERSION"), "os": std::env::consts::OS,
        "active_runs": app.live.lock().await.len(), "gpu": gpu}))
}

async fn link_status(State(app): State<App>) -> Json<Value> {
    match &app.link {
        Some(l) => Json(l.status().await),
        None => Json(json!({"off": true, "why": "LOKI_PEER_SECRET is not set in harness_data/.env on this machine"})),
    }
}

/// The window talks to the other machine through here: /peer/<name>/<any peer path>.
async fn peer_proxy(State(app): State<App>, AxPath((name, _rest)): AxPath<(String, String)>, method: Method, uri: Uri, headers: HeaderMap, body: axum::body::Bytes) -> Response {
    let Some(l) = app.link.clone() else { return (StatusCode::NOT_FOUND, "the link is off").into_response() };
    // keep the raw (still encoded) path so the signature matches what is sent
    let raw = uri.path();
    let after = raw.trim_start_matches("/peer/");
    let rest = after.find('/').map(|i| &after[i..]).unwrap_or("/");
    let mut pq = rest.to_string();
    if let Some(q) = uri.query() {
        pq.push('?');
        pq.push_str(q);
    }
    let ctype = headers.get(header::CONTENT_TYPE).and_then(|v| v.to_str().ok()).map(str::to_string);
    match l.call(&name, method.as_str(), &pq, body.to_vec(), ctype.as_deref()).await {
        Ok(r) => {
            let st = StatusCode::from_u16(r.status().as_u16()).unwrap_or(StatusCode::BAD_GATEWAY);
            let ct = r.headers().get(reqwest::header::CONTENT_TYPE).and_then(|v| v.to_str().ok()).unwrap_or("application/octet-stream").to_string();
            match r.bytes().await {
                Ok(b) => (st, [(header::CONTENT_TYPE, ct)], Body::from(b)).into_response(),
                Err(e) => (StatusCode::BAD_GATEWAY, e.to_string()).into_response(),
            }
        }
        Err(e) => (StatusCode::BAD_GATEWAY, e).into_response(),
    }
}

/// Every driver knob: what each one is, its default, and this machine's value.
async fn tuning() -> Json<Value> {
    let t = loki_core::tuning::Tuning::load();
    Json(json!({"knobs": loki_core::tuning::Tuning::describe(), "defaults": loki_core::tuning::Tuning::default(), "values": t}))
}

async fn get_settings(State(app): State<App>) -> Json<Value> {
    Json(app.settings())
}

async fn put_settings(State(app): State<App>, Json(v): Json<Value>) -> StatusCode {
    let mut cur = app.settings();
    if let (Some(c), Some(n)) = (cur.as_object_mut(), v.as_object()) {
        for (k, val) in n {
            c.insert(k.clone(), val.clone());
        }
    }
    match serde_json::to_vec_pretty(&cur).map(|b| loki_core::journal::atomic_write(&app.home.join("settings.json"), &b)) {
        Ok(Ok(())) => StatusCode::OK,
        _ => StatusCode::INTERNAL_SERVER_ERROR,
    }
}

fn run_out(prog: &str, args: &[&str]) -> Option<String> {
    let mut c = std::process::Command::new(prog);
    c.args(args);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        c.creation_flags(0x0800_0000);
    }
    c.output().ok().filter(|o| o.status.success()).map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
}

fn which(prog: &str) -> Option<String> {
    let exts: &[&str] = if cfg!(windows) { &[".exe", ".cmd", ".bat"] } else { &[""] };
    for dir in std::env::split_paths(&std::env::var_os("PATH")?) {
        for e in exts {
            let c = dir.join(format!("{prog}{e}"));
            if c.is_file() {
                return Some(c.to_string_lossy().to_string());
            }
        }
    }
    None
}

/// System scan: hardware, creative tools, local AI, and what to install or change.
async fn system(State(app): State<App>) -> Json<Value> {
    use sysinfo::{Disks, System};
    let mut sys = System::new_all();
    sys.refresh_all();
    let ram_gb = sys.total_memory() as f64 / 1e9;
    let cpu = sys.cpus().first().map(|c| c.brand().trim().to_string()).unwrap_or_default();
    let cores = sys.cpus().len();
    // the drive LOKI keeps its data on
    let disks = Disks::new_with_refreshed_list();
    let home_s = app.home.to_string_lossy().to_ascii_lowercase();
    let disk = disks.list().iter().filter(|d| home_s.starts_with(&d.mount_point().to_string_lossy().to_ascii_lowercase())).max_by_key(|d| d.mount_point().as_os_str().len());
    let (disk_free, disk_total) = disk.map(|d| (d.available_space() as f64 / 1e9, d.total_space() as f64 / 1e9)).unwrap_or((0.0, 0.0));
    // GPU
    let mut gpu = json!(null);
    let mut vram_gb = 0.0;
    if let Some(o) = run_out("nvidia-smi", &["--query-gpu=name,memory.total,memory.used,driver_version", "--format=csv,noheader,nounits"]) {
        let f: Vec<&str> = o.lines().next().unwrap_or("").split(',').map(|x| x.trim()).collect();
        if f.len() >= 3 {
            vram_gb = f[1].parse::<f64>().unwrap_or(0.0) / 1024.0;
            gpu = json!({"name": f[0], "vram_gb": vram_gb, "used_gb": f[2].parse::<f64>().unwrap_or(0.0) / 1024.0, "driver": f.get(3)});
        }
    }
    let mac = cfg!(target_os = "macos");
    if mac && gpu.is_null() {
        let chip = run_out("sysctl", &["-n", "machdep.cpu.brand_string"]).unwrap_or_default();
        gpu = json!({"name": format!("{chip} (unified memory)"), "vram_gb": ram_gb, "unified": true});
    }
    // How much model fits: a dedicated GPU's memory; on the Mac a careful share of unified memory
    // (owner 2026-10-26: a heavy local model next to Blender crashed it).
    let budget = if vram_gb > 0.0 { vram_gb } else if mac { ram_gb * 0.4 } else { ram_gb * 0.5 };
    // tools
    let blender = std::env::var("LOKI_BLENDER").ok().filter(|b| Path::new(b).is_file()).or_else(|| which("blender"));
    let http = reqwest::Client::builder().timeout(std::time::Duration::from_secs(3)).build().unwrap();
    let comfy = http.get("http://127.0.0.1:8188/system_stats").send().await.map(|r| r.status().is_success()).unwrap_or(false);
    let ollama_models: Vec<String> = match http.get(format!("{}/api/tags", ollama_base())).send().await {
        Ok(r) => r.json::<Value>().await.ok().and_then(|v| v["models"].as_array().map(|a| a.iter().filter_map(|m| m["name"].as_str().map(String::from)).collect())).unwrap_or_default(),
        Err(_) => vec![],
    };
    let ollama_up = which("ollama").is_some() || !ollama_models.is_empty();
    let tools = json!({
        "blender": blender, "ffmpeg": which("ffmpeg"), "python": which("python").or_else(|| which("python3")),
        "git": which("git"), "ollama": ollama_up, "comfyui": comfy,
    });
    // model picks that fit this machine
    let catalog: Vec<Value> = serde_json::from_str(CATALOG).unwrap_or_default();
    let installed = |tag: &str| ollama_models.iter().any(|m| m == tag || m.trim_end_matches(":latest") == tag || m.ends_with(&format!("/{tag}")) || m.contains(tag));
    let fits = |m: &Value| m["need"].as_f64().unwrap_or(99.0) <= budget + 0.01;
    let pick = |family: &dyn Fn(&Value) -> bool| -> Vec<Value> {
        let mut v: Vec<Value> = catalog.iter().filter(|m| family(m) && fits(m)).cloned().collect();
        v.sort_by(|a, b| b["score"].as_f64().unwrap_or(0.0).partial_cmp(&a["score"].as_f64().unwrap_or(0.0)).unwrap());
        v.truncate(4);
        for m in v.iter_mut() {
            let tag = m["tag"].as_str().unwrap_or("").to_string();
            m["installed"] = json!(installed(&tag));
        }
        v
    };
    let standard = pick(&|m| m["family"] == "standard");
    let uncensored = pick(&|m| matches!(m["family"].as_str(), Some("abliterated" | "uncensored")));
    let fast = pick(&|m| m["roles"].as_array().is_some_and(|r| r.iter().any(|x| x == "fast")));
    // what to do next, most useful first
    let mut advice: Vec<Value> = Vec::new();
    let mut tip = |level: &str, text: String| advice.push(json!({"level": level, "text": text}));
    if blender.is_none() { tip("high", "Blender was not found - LOKI's 3D work needs it. Install it from blender.org (or set LOKI_BLENDER).".into()); }
    if tools["ffmpeg"].is_null() { tip("mid", "ffmpeg was not found - needed to turn renders into videos (winget install ffmpeg / brew install ffmpeg).".into()); }
    if !comfy && vram_gb >= 6.0 { tip("mid", "ComfyUI is not running - start it for AI images, image-to-3D (TRELLIS / Hunyuan3D) and video on this GPU.".into()); }
    if !ollama_up { tip("mid", "No local AI (Ollama) - install it from ollama.com so LOKI keeps working offline.".into()); }
    if let Some(best) = standard.first() {
        if !best["installed"].as_bool().unwrap_or(false) {
            tip("low", format!("Best local model for this machine: {} - {}", best["tag"].as_str().unwrap_or(""), best["why"].as_str().unwrap_or("")));
        }
    }
    if let Some(best) = uncensored.first() {
        if !best["installed"].as_bool().unwrap_or(false) {
            tip("low", format!("Best abliterated (uncensored) model that fits: {} - {}", best["tag"].as_str().unwrap_or(""), best["why"].as_str().unwrap_or("")));
        }
    }
    if mac && std::env::var("OLLAMA_MODELS").is_err() {
        tip("high", "On the Mac, set OLLAMA_MODELS to a folder on the external drive before downloading models - the internal disk is full.".into());
    }
    if disk_total > 0.0 && disk_free < 20.0 { tip("high", format!("Only {disk_free:.0} GB free where LOKI keeps its data.")); }
    let missing: Vec<&str> = ["GROQ_API_KEY", "OPENROUTER_API_KEY", "MISTRAL_API_KEY"].into_iter()
        .filter(|k| std::env::var(k).map(|v| v.trim().is_empty()).unwrap_or(true)).collect();
    if !missing.is_empty() {
        tip("low", format!("More free model capacity: add {} to harness_data/.env (free signups).", missing.join(", ")));
    }
    Json(json!({
        "machine": std::env::var("COMPUTERNAME").or_else(|_| std::env::var("HOSTNAME")).unwrap_or_default(),
        "os": format!("{} {}", System::name().unwrap_or_default(), System::os_version().unwrap_or_default()),
        "cpu": cpu, "cores": cores, "ram_gb": ram_gb, "gpu": gpu, "model_budget_gb": budget,
        "disk": {"free_gb": disk_free, "total_gb": disk_total},
        "tools": tools, "local_models": ollama_models,
        "recommend": {"standard": standard, "uncensored": uncensored, "fast": fast},
        "advice": advice,
    }))
}

/// Download a local model with Ollama in the background; progress at GET /local-models/pulls.
async fn pull_model(State(app): State<App>, Json(m): Json<ModelName>) -> StatusCode {
    let name = m.name.trim().to_string();
    if name.is_empty() || name.contains(char::is_whitespace) {
        return StatusCode::BAD_REQUEST;
    }
    if cfg!(target_os = "macos") && std::env::var("OLLAMA_MODELS").is_err() {
        return StatusCode::PRECONDITION_FAILED; // the Mac's internal disk is full: set OLLAMA_MODELS first
    }
    app.pulls.lock().await.insert(name.clone(), json!({"status": "starting", "pct": 0}));
    let pulls = app.pulls.clone();
    tokio::spawn(async move {
        let c = reqwest::Client::builder().timeout(std::time::Duration::from_secs(6 * 3600)).build().unwrap();
        let resp = c.post(format!("{}/api/pull", ollama_base())).json(&json!({"model": name, "name": name, "stream": true})).send().await;
        let mut resp = match resp {
            Ok(r) if r.status().is_success() => r,
            Ok(r) => { pulls.lock().await.insert(name.clone(), json!({"status": format!("failed: http {}", r.status().as_u16()), "pct": 0})); return; }
            Err(e) => { pulls.lock().await.insert(name.clone(), json!({"status": format!("failed: {e}"), "pct": 0})); return; }
        };
        let mut buf = String::new();
        while let Ok(Some(chunk)) = resp.chunk().await {
            buf.push_str(&String::from_utf8_lossy(&chunk));
            while let Some(i) = buf.find('\n') {
                let line: String = buf.drain(..=i).collect();
                if let Ok(v) = serde_json::from_str::<Value>(line.trim()) {
                    let pct = match (v["completed"].as_f64(), v["total"].as_f64()) { (Some(a), Some(b)) if b > 0.0 => (a / b * 100.0).round(), _ => -1.0 };
                    let status = v["status"].as_str().unwrap_or("").to_string();
                    let mut p = pulls.lock().await;
                    let prev = p.get(&name).and_then(|x| x["pct"].as_f64()).unwrap_or(0.0);
                    p.insert(name.clone(), json!({"status": if v.get("error").is_some() { format!("failed: {}", v["error"]) } else { status }, "pct": if pct >= 0.0 { pct } else { prev }}));
                }
            }
        }
    });
    StatusCode::OK
}

async fn pulls(State(app): State<App>) -> Json<Value> {
    Json(json!(app.pulls.lock().await.clone()))
}

/// The owner's panel layout for this machine (pywebview does not keep browser storage).
async fn get_layout(State(app): State<App>) -> Json<Value> {
    Json(std::fs::read_to_string(app.home.join("ui_layout.json")).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(json!(null)))
}

async fn put_layout(State(app): State<App>, Json(v): Json<Value>) -> StatusCode {
    match serde_json::to_vec_pretty(&v).map(|b| loki_core::journal::atomic_write(&app.home.join("ui_layout.json"), &b)) {
        Ok(Ok(())) => StatusCode::OK,
        _ => StatusCode::INTERNAL_SERVER_ERROR,
    }
}

fn ollama_base() -> String {
    let h = std::env::var("OLLAMA_HOST").unwrap_or_else(|_| "http://127.0.0.1:11434".into());
    let h = if h.starts_with("http") { h } else { format!("http://{h}") };
    h.trim_end_matches('/').to_string()
}

/// Local models on this machine (Ollama), with sizes.
async fn local_models() -> Json<Value> {
    let c = reqwest::Client::builder().timeout(std::time::Duration::from_secs(5)).build().unwrap();
    match c.get(format!("{}/api/tags", ollama_base())).send().await {
        Ok(r) => Json(r.json::<Value>().await.unwrap_or(json!({"models": []}))),
        Err(_) => Json(json!({"models": [], "error": "Ollama is not running on this machine"})),
    }
}

#[derive(Deserialize)]
struct ModelName {
    name: String,
}

async fn remove_local_model(Json(m): Json<ModelName>) -> StatusCode {
    let c = reqwest::Client::builder().timeout(std::time::Duration::from_secs(60)).build().unwrap();
    match c.delete(format!("{}/api/delete", ollama_base())).json(&json!({"model": m.name, "name": m.name})).send().await {
        Ok(r) if r.status().is_success() => StatusCode::OK,
        Ok(r) => StatusCode::from_u16(r.status().as_u16()).unwrap_or(StatusCode::BAD_GATEWAY),
        Err(_) => StatusCode::BAD_GATEWAY,
    }
}

/// Jobs and messages dropped into <home>/inbox as JSON files (the other machine, a script, a phone):
///   {"goal": "...", "mode": "smart"}            start a job
///   {"run": "<id>", "say": "..."}              chat message
///   {"run": "<id>", "reply": {"approve": true, "note": "..."}}
///   {"run": "<id>", "stop": true}
/// Each file moves to inbox/done/ with a .result.json next to it.
async fn inbox_loop(app: App) {
    let dir = app.home.join("inbox");
    let done = dir.join("done");
    let _ = std::fs::create_dir_all(&done);
    loop {
        tokio::time::sleep(std::time::Duration::from_secs(2)).await;
        let Ok(rd) = std::fs::read_dir(&dir) else { continue };
        let mut files: Vec<PathBuf> = rd.flatten().map(|e| e.path()).filter(|p| p.extension().is_some_and(|x| x == "json")).collect();
        files.sort();
        for f in files {
            let name = f.file_name().unwrap().to_string_lossy().to_string();
            let Ok(text) = std::fs::read_to_string(&f) else { continue };
            let result: Value = match serde_json::from_str::<Value>(&text) {
                Err(e) => json!({"ok": false, "error": format!("not JSON: {e}")}),
                Ok(v) => {
                    if let Some(goal) = v["goal"].as_str() {
                        let req = NewRun { goal: goal.into(), mode: v["mode"].as_str().map(String::from), prefer: v["prefer"].as_str().map(String::from),
                            max_hours: v["max_hours"].as_f64(), max_steps: v["max_steps"].as_u64(), workspace: None, attach: vec![], interview: v["interview"].as_str().map(String::from) };
                        match app.new_run(req).await {
                            Ok(info) => json!({"ok": true, "run": info["id"]}),
                            Err((_, e)) => json!({"ok": false, "error": e}),
                        }
                    } else if let Some(id) = v["run"].as_str() {
                        if let Some(t) = v["say"].as_str() {
                            json!({"ok": app.say(id, t).await.is_success()})
                        } else if v.get("reply").is_some() {
                            let r: OwnerReply = serde_json::from_value(v["reply"].clone()).unwrap_or(OwnerReply { approve: false, note: String::new() });
                            json!({"ok": reply_run(State(app.clone()), AxPath(id.to_string()), Json(r)).await.is_success()})
                        } else if v["stop"].as_bool() == Some(true) {
                            json!({"ok": stop_run(State(app.clone()), AxPath(id.to_string())).await.is_success()})
                        } else {
                            json!({"ok": false, "error": "nothing to do"})
                        }
                    } else {
                        json!({"ok": false, "error": "need 'goal' or 'run'"})
                    }
                }
            };
            tracing::info!("inbox {name}: {result}");
            let _ = std::fs::rename(&f, done.join(&name));
            let _ = std::fs::write(done.join(format!("{name}.result.json")), result.to_string());
        }
    }
}

async fn list_runs(State(app): State<App>) -> Json<Value> {
    let live = app.live.lock().await;
    let runs: Vec<Value> = Journal::list(&app.runs_dir())
        .into_iter()
        .map(|r| {
            let active = live.contains_key(&r.id);
            let mut v = json!(r);
            v["active"] = json!(active);
            v
        })
        .collect();
    Json(json!(runs))
}

async fn get_run(State(app): State<App>, AxPath(id): AxPath<String>) -> Result<Json<Value>, StatusCode> {
    let j = Journal::open(&app.runs_dir().join(&id));
    let info = j.info().map_err(|_| StatusCode::NOT_FOUND)?;
    let files = list_files(&info.workspace, 400);
    Ok(Json(json!({"run": info, "tasks": j.tasks(), "progress": j.progress_tail(60), "files": files})))
}

async fn stop_run(State(app): State<App>, AxPath(id): AxPath<String>) -> StatusCode {
    match app.live.lock().await.get(&id) {
        Some(flag) => {
            flag.store(true, Ordering::SeqCst);
            StatusCode::OK
        }
        None => StatusCode::NOT_FOUND,
    }
}

async fn resume_run(State(app): State<App>, AxPath(id): AxPath<String>) -> StatusCode {
    let j = Journal::open(&app.runs_dir().join(&id));
    let Ok(info) = j.info() else { return StatusCode::NOT_FOUND };
    if matches!(info.status, Status::Waiting | Status::Done) {
        return StatusCode::CONFLICT;
    }
    app.spawn(id).await;
    StatusCode::OK
}

async fn reply_run(State(app): State<App>, AxPath(id): AxPath<String>, Json(r): Json<OwnerReply>) -> StatusCode {
    let j = Journal::open(&app.runs_dir().join(&id));
    let Ok(mut info) = j.info() else { return StatusCode::NOT_FOUND };
    if info.status != Status::Waiting {
        return StatusCode::CONFLICT;
    }
    info.owner_reply = Some(r);
    if j.save_info(&info).is_err() {
        return StatusCode::INTERNAL_SERVER_ERROR;
    }
    app.spawn(id).await;
    StatusCode::OK
}

#[derive(Serialize)]
struct FileEntry {
    path: String,
    bytes: u64,
    modified: u64,
}

/// Files a run produced, newest first (images show as thumbnails in the window).
fn list_files(root: &Path, cap: usize) -> Vec<FileEntry> {
    let mut out = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let Ok(rd) = std::fs::read_dir(&dir) else { continue };
        for e in rd.flatten() {
            let p = e.path();
            let name = e.file_name().to_string_lossy().to_string();
            if name.starts_with('.') || name == "__pycache__" || name == "node_modules" {
                continue;
            }
            if p.is_dir() {
                stack.push(p);
            } else if let Ok(m) = e.metadata() {
                let rel = p.strip_prefix(root).unwrap_or(&p).to_string_lossy().replace('\\', "/");
                let modified = m.modified().ok().and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok()).map(|d| d.as_secs()).unwrap_or(0);
                out.push(FileEntry { path: rel, bytes: m.len(), modified });
            }
            if out.len() >= cap * 4 {
                break;
            }
        }
    }
    out.sort_by(|a, b| b.modified.cmp(&a.modified));
    out.truncate(cap);
    out
}

#[derive(Deserialize)]
struct FileQuery {
    path: String,
}

fn mime(path: &str) -> &'static str {
    let ext = path.rsplit('.').next().unwrap_or("").to_ascii_lowercase();
    match ext.as_str() {
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "webp" => "image/webp",
        "gif" => "image/gif",
        "svg" => "image/svg+xml",
        "mp4" => "video/mp4",
        "webm" => "video/webm",
        "glb" => "model/gltf-binary",
        "gltf" => "model/gltf+json",
        "json" => "application/json",
        "html" => "text/plain; charset=utf-8", // never run a page a model wrote
        _ => "text/plain; charset=utf-8",
    }
}

async fn run_file(State(app): State<App>, AxPath(id): AxPath<String>, Query(q): Query<FileQuery>) -> Response {
    let j = Journal::open(&app.runs_dir().join(&id));
    let Ok(info) = j.info() else { return StatusCode::NOT_FOUND.into_response() };
    let Ok(p) = confine(&info.workspace, &q.path) else { return StatusCode::FORBIDDEN.into_response() };
    match tokio::fs::read(&p).await {
        Ok(bytes) => ([(header::CONTENT_TYPE, mime(&q.path)), (header::CACHE_CONTROL, "no-cache")], Body::from(bytes)).into_response(),
        Err(_) => StatusCode::NOT_FOUND.into_response(),
    }
}

#[derive(Serialize, Deserialize, Clone)]
struct ProbeRow {
    provider: String,
    role: String,
    model: String,
    ok: bool,
    ms: u128,
    note: String,
}

/// Ask every configured provider/model for a one-word answer, all at once.
async fn probe_all(home: &Path) -> anyhow::Result<Vec<ProbeRow>> {
    let mut pool = load_pool(home)?;
    fit_local_models(&mut pool).await;
    discover_vision(&mut pool, home).await;
    let http = reqwest::Client::builder().timeout(std::time::Duration::from_secs(40)).build()?;
    let mut jobs = Vec::new();
    for p in pool.providers().iter().cloned() {
        let key = if p.key_env.is_empty() { None } else { std::env::var(&p.key_env).ok().filter(|k| !k.trim().is_empty()) };
        for (role, model) in p.models.clone() {
            let role = format!("{role:?}").to_lowercase();
            if !p.key_env.is_empty() && key.is_none() {
                jobs.push(tokio::spawn({
                    let (name, env) = (p.name.clone(), p.key_env.clone());
                    async move { ProbeRow { provider: name, role, model, ok: false, ms: 0, note: format!("no key: set {env}") } }
                }));
                continue;
            }
            let (http, key, url, name) = (http.clone(), key.clone(), format!("{}/chat/completions", p.base_url.trim_end_matches('/')), p.name.clone());
            jobs.push(tokio::spawn(async move {
                let mut req = http.post(url).json(&json!({"model": model, "max_tokens": 8,
                    "messages": [{"role":"user","content":"Reply with the single word: ok"}]}));
                if let Some(k) = &key {
                    req = req.bearer_auth(k);
                }
                let t = std::time::Instant::now();
                let (ok, note) = match req.send().await {
                    Ok(r) if r.status().is_success() => (true, "answered".to_string()),
                    Ok(r) => {
                        let code = r.status().as_u16();
                        let body: String = r.text().await.unwrap_or_default().chars().take(120).collect();
                        (false, format!("http {code} {body}"))
                    }
                    Err(e) if e.is_connect() => (false, "not running / unreachable".into()),
                    Err(e) if e.is_timeout() => (false, "timed out".into()),
                    Err(e) => (false, e.to_string()),
                };
                ProbeRow { provider: name, role, model, ok, ms: t.elapsed().as_millis(), note }
            }));
        }
    }
    let mut rows = Vec::new();
    for j in jobs {
        if let Ok(r) = j.await {
            rows.push(r);
        }
    }
    let _ = loki_core::journal::atomic_write(&home.join("probe.json"), serde_json::to_string_pretty(&rows)?.as_bytes());
    Ok(rows)
}

async fn models(State(app): State<App>, Query(q): Query<HashMap<String, String>>) -> Json<Value> {
    let cached = std::fs::read_to_string(app.home.join("probe.json")).ok().and_then(|s| serde_json::from_str::<Value>(&s).ok());
    let mut rows = if q.contains_key("refresh") || cached.is_none() {
        match probe_all(&app.home).await {
            Ok(rows) => json!(rows),
            Err(e) => return Json(json!({"error": e.to_string()})),
        }
    } else {
        cached.unwrap_or(json!([]))
    };
    // real speed measured on this machine's jobs (tokens/s), when known
    let speeds = app.driver.pool.lock().await.speeds();
    if let Some(a) = rows.as_array_mut() {
        for r in a.iter_mut() {
            let key = format!("{}|{}", r["provider"].as_str().unwrap_or(""), r["model"].as_str().unwrap_or(""));
            if let Some(sp) = speeds.get(&key) {
                r["tps"] = json!((sp.tps * 10.0).round() / 10.0);
                r["latency_ms"] = json!(sp.latency_ms.round());
                r["samples"] = json!(sp.samples);
            }
        }
    }
    Json(rows)
}

async fn knowledge(State(app): State<App>) -> Json<Value> {
    let k = &app.driver.knowledge;
    Json(json!({"playbooks": k.playbooks.iter().map(|p| json!({"name": p.name, "description": p.description})).collect::<Vec<_>>(),
        "lessons": k.lessons()}))
}

/// "Update everything": the launcher watches for this file and does the update.
async fn request_update(State(app): State<App>) -> StatusCode {
    match std::fs::write(app.home.join("update.request"), chrono_now()) {
        Ok(_) => StatusCode::OK,
        Err(_) => StatusCode::INTERNAL_SERVER_ERROR,
    }
}

fn chrono_now() -> String {
    format!("{:?}", std::time::SystemTime::now())
}

async fn status(State(app): State<App>) -> Json<Value> {
    let launcher = std::fs::read_to_string(app.home.join("launcher_status.json")).ok().and_then(|s| serde_json::from_str::<Value>(&s).ok());
    let repo = repo_dir();
    let version = repo.as_ref().and_then(|r| std::fs::read_to_string(r.join("VERSION")).ok()).map(|v| v.trim().to_string()).unwrap_or_else(|| env!("CARGO_PKG_VERSION").into());
    let commit_time = repo.as_ref().and_then(|r| {
        let mut c = std::process::Command::new("git");
        c.args(["-C", &r.to_string_lossy(), "log", "-1", "--format=%h|%cI|%s"]);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            c.creation_flags(0x0800_0000);
        }
        c.output().ok().filter(|o| o.status.success()).map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
    }).unwrap_or_default();
    let mut parts = commit_time.splitn(3, '|');
    let commit = parts.next().unwrap_or("").to_string();
    let when = parts.next().unwrap_or("").to_string();
    let subject = parts.next().unwrap_or("").to_string();
    Json(json!({
        "service": "lokid",
        "version": version,
        "commit": commit,
        "commit_time": when,
        "commit_subject": subject,
        "home": app.home,
        "active_runs": app.live.lock().await.len(),
        "machine": std::env::var("COMPUTERNAME").or_else(|_| std::env::var("HOSTNAME")).unwrap_or_default(),
        "os": std::env::consts::OS,
        "launcher": launcher,
    }))
}

/// Vision model families, best first (matched against the ids a provider really serves).
const VISION_FAMILIES: &[&str] = &["qwen3-vl", "qwen3.5-vl", "qwen2.5-vl", "llama-4-maverick", "llama-4-scout", "gemma-4", "gemma-3-27b",
    "pixtral", "nemotron-nano-vl", "nemotron-nano-12b-v2-vl", "phi-4-multimodal", "llama-3.2-90b-vision", "llama-3.2-11b-vision", "-vl", "vision"];

/// Model ids drift: ask each online provider which models it serves (GET /models), and give the pool
/// working vision models from that list (up to 2 per endpoint) when the configured one is gone.
async fn discover_vision(pool: &mut ModelPool, home: &Path) {
    use loki_core::pool::{Provider, Role};
    let http = match reqwest::Client::builder().timeout(std::time::Duration::from_secs(15)).build() { Ok(c) => c, Err(_) => return };
    let mut seen: HashMap<String, Vec<String>> = HashMap::new();
    let base: Vec<Provider> = pool.providers().iter().filter(|p| !p.local).cloned().collect();
    for p in &base {
        let key = if p.key_env.is_empty() { None } else { match std::env::var(&p.key_env) { Ok(k) if !k.trim().is_empty() => Some(k), _ => continue } };
        if seen.contains_key(&p.base_url) { continue; }
        let mut req = http.get(format!("{}/models", p.base_url.trim_end_matches('/')));
        if let Some(k) = &key { req = req.bearer_auth(k); }
        let ids: Vec<String> = match req.send().await {
            Ok(r) if r.status().is_success() => r.json::<Value>().await.ok().and_then(|v| v["data"].as_array().map(|a| a.iter().filter_map(|m| m["id"].as_str().map(String::from)).collect())).unwrap_or_default(),
            _ => vec![],
        };
        seen.insert(p.base_url.clone(), ids);
    }
    let _ = std::fs::write(home.join("models_available.json"), serde_json::to_string_pretty(&seen).unwrap_or_default());
    for (url, ids) in &seen {
        if ids.is_empty() { continue; }
        let lower: Vec<(String, String)> = ids.iter().map(|i| (i.to_ascii_lowercase(), i.clone())).collect();
        let mut picks: Vec<String> = Vec::new();
        for fam in VISION_FAMILIES {
            for (l, id) in &lower {
                if l.contains(fam) && !l.contains("embed") && !l.contains("guard") && !picks.contains(id) {
                    picks.push(id.clone());
                }
            }
            if picks.len() >= 2 { break; }
        }
        picks.truncate(2);
        let Some(tpl) = base.iter().find(|p| &p.base_url == url).cloned() else { continue };
        let configured: Vec<String> = pool.providers().iter().filter(|p| &p.base_url == url).filter_map(|p| p.models.get(&Role::Vision).cloned()).collect();
        // drop configured vision models this endpoint no longer serves
        for p in pool.providers_mut().iter_mut().filter(|p| &p.base_url == url) {
            if let Some(m) = p.models.get(&Role::Vision).cloned() {
                if !ids.contains(&m) {
                    tracing::info!("vision model {m} is gone from {}", p.name);
                    p.models.remove(&Role::Vision);
                }
            }
        }
        for (i, id) in picks.into_iter().enumerate() {
            if configured.contains(&id) && ids.contains(&id) { continue; }
            let mut np = tpl.clone();
            np.name = format!("{}-vision{}", tpl.name, i + 1);
            np.models = HashMap::from([(Role::Vision, id.clone())]);
            np.priority = tpl.priority + 1 + i as i32;
            tracing::info!("vision model found: {} ({})", id, np.name);
            pool.providers_mut().retain(|p| p.name != np.name);
            pool.providers_mut().push(np);
        }
    }
}

/// Ask the local Ollama which models it has, so the offline fallback uses a real one.
async fn fit_local_models(pool: &mut ModelPool) {
    let url = std::env::var("OLLAMA_HOST").map(|h| format!("{}/api/tags", h.trim_end_matches('/'))).unwrap_or_else(|_| "http://127.0.0.1:11434/api/tags".into());
    let url = if url.starts_with("http") { url } else { format!("http://{url}") };
    let Ok(client) = reqwest::Client::builder().timeout(std::time::Duration::from_secs(3)).build() else { return };
    let names: Vec<String> = match client.get(&url).send().await {
        Ok(r) => r.json::<Value>().await.ok()
            .and_then(|v| v["models"].as_array().map(|a| a.iter().filter_map(|m| m["name"].as_str().map(String::from)).collect()))
            .unwrap_or_default(),
        Err(_) => return,
    };
    let pinned = std::env::var("LOKI_LOCAL_MODEL").ok();
    for c in pool.fit_local("ollama", &names, pinned.as_deref()) {
        tracing::info!("local model: {c}");
    }
}

async fn serve(home: PathBuf) -> anyhow::Result<()> {
    let mut pool = load_pool(&home)?;
    fit_local_models(&mut pool).await;
    discover_vision(&mut pool, &home).await;
    let pool = Arc::new(Mutex::new(pool));
    let mut driver = Driver::new(pool);
    driver.knowledge = loki_core::knowledge::Knowledge::load(repo_dir().map(|r| r.join("playbooks")).as_deref(), Some(&home.join("lessons.md")));
    tracing::info!("playbooks: {}, lessons: {}", driver.knowledge.playbooks.len(), driver.knowledge.lessons().len());
    let link = link::Link::from_env(&home);
    let app = App { home: home.clone(), driver: Arc::new(driver), live: Arc::new(Mutex::new(HashMap::new())), pulls: Arc::new(Mutex::new(HashMap::new())), link: link.clone() };
    let router = Router::new()
        .route("/", get(|| async { Html(UI) }))
        .route("/health", get(|| async { Json(json!({"ok": true, "service": "lokid", "version": env!("CARGO_PKG_VERSION")})) }))
        .route("/status", get(status))
        .route("/models", get(models))
        .route("/update", post(request_update))
        .route("/runs", get(list_runs).post(create_run))
        .route("/runs/:id", get(get_run))
        .route("/runs/:id/file", get(run_file))
        .route("/runs/:id/stop", post(stop_run))
        .route("/runs/:id/resume", post(resume_run))
        .route("/runs/:id/reply", post(reply_run))
        .route("/runs/:id/say", post(say_run))
        .route("/runs/:id/chat", get(chat_run))
        .route("/library", get(library))
        .route("/upload", post(upload).layer(axum::extract::DefaultBodyLimit::max(512 * 1024 * 1024)))
        .route("/layout", get(get_layout).put(put_layout))
        .route("/local-models", get(local_models))
        .route("/local-models/remove", post(remove_local_model))
        .route("/local-models/pull", post(pull_model))
        .route("/local-models/pulls", get(pulls))
        .route("/settings", get(get_settings).put(put_settings))
        .route("/system", get(system))
        .route("/knowledge", get(knowledge))
        .route("/link", get(link_status))
        .route("/logs", get(logs))
        .route("/tuning", get(tuning))
        .route("/mirror/file", get(mirror_file))
        .route("/peer/:name/*rest", any(peer_proxy).layer(axum::extract::DefaultBodyLimit::max(512 * 1024 * 1024)))
        .with_state(app.clone());
    if let Some(l) = link {
        // The peer port: only what the other machine needs, every request signed.
        let peer = Router::new()
            .route("/hello", get(hello))
            .route("/logs", get(logs))
            .route("/status", get(status))
            .route("/models", get(models))
            .route("/runs", get(list_runs).post(create_run))
            .route("/runs/:id", get(get_run))
            .route("/runs/:id/file", get(run_file))
            .route("/runs/:id/stop", post(stop_run))
            .route("/runs/:id/resume", post(resume_run))
            .route("/runs/:id/reply", post(reply_run))
            .route("/runs/:id/say", post(say_run))
            .route("/runs/:id/chat", get(chat_run))
            .route("/library", get(library))
            .route("/upload", post(upload))
            .layer(middleware::from_fn_with_state(app.clone(), peer_auth))
            .layer(axum::extract::DefaultBodyLimit::max(512 * 1024 * 1024))
            .with_state(app.clone());
        let pport: u16 = std::env::var("LOKI_LINK_PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(7718);
        match tokio::net::TcpListener::bind(("127.0.0.1", pport)).await {
            Ok(pl) => {
                tracing::info!("link: {} serving the other machine on 127.0.0.1:{pport}", l.name);
                tokio::spawn(async move { let _ = axum::serve(pl, peer).await; });
                if std::env::var("LOKI_LINK_TUNNEL").map(|v| v != "0").unwrap_or(true) {
                    tokio::spawn(l.clone().run_tunnel(pport));
                }
                tokio::spawn(l.clone().run_discovery());
                tokio::spawn(l.clone().run_mirror());
            }
            Err(e) => tracing::warn!("link: port {pport} is busy ({e}); the link is off"),
        }
    } else {
        tracing::info!("link: off (no LOKI_PEER_SECRET)");
    }
    tokio::spawn(inbox_loop(app.clone()));
    let port: u16 = std::env::var("LOKI_DRIVER_PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(7717);
    let listener = tokio::net::TcpListener::bind(("127.0.0.1", port)).await?;
    tracing::info!("lokid {} on http://127.0.0.1:{port}, home {}", env!("CARGO_PKG_VERSION"), home.display());
    // Pick up runs that were working when the machine slept, crashed or updated.
    for info in Journal::list(&app.runs_dir()) {
        if matches!(info.status, Status::Running | Status::Planning | Status::Resting) {
            tracing::info!("resuming run {}", info.id);
            app.spawn(info.id).await;
        }
    }
    axum::serve(listener, router).await?;
    Ok(())
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt().with_target(false).with_ansi(false).init();
    let home = home();
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        None | Some("serve") => serve(home).await,
        Some("probe") => {
            for r in probe_all(&home).await? {
                println!("{:<16} {:<7} {:<45} {} {:>6}ms {}", r.provider, r.role, r.model, if r.ok { "OK  " } else { "FAIL" }, r.ms, r.note);
            }
            Ok(())
        }
        Some("run") => {
            let goal = args[1..].join(" ");
            let pool = Arc::new(Mutex::new(load_pool(&home)?));
            let (j, _) = Journal::create(&home.join("runs"), &goal, &home.join("work").join("cli"), 2000, 12.0)?;
            println!("run folder: {}", j.dir.display());
            let info = Driver::new(pool).run(&j, Arc::new(AtomicBool::new(false))).await?;
            println!("finished: {:?}\n{}", info.status, j.progress_tail(30));
            Ok(())
        }
        Some("--version") | Some("version") => {
            println!("lokid {}", env!("CARGO_PKG_VERSION"));
            Ok(())
        }
        Some(other) => anyhow::bail!("unknown command '{other}' (serve | probe | run \"<goal>\" | version)"),
    }
}
