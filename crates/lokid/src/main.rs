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

use axum::{
    body::Body,
    extract::{Path as AxPath, Query, State},
    http::{header, StatusCode},
    response::{Html, IntoResponse, Response},
    routing::{get, post},
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
const UI: &str = include_str!("../../../app/ui/index.html");

#[derive(Clone)]
struct App {
    home: PathBuf,
    driver: Arc<Driver>,
    live: Arc<Mutex<HashMap<String, Arc<AtomicBool>>>>,
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

fn load_pool(home: &Path) -> anyhow::Result<ModelPool> {
    std::fs::create_dir_all(home)?;
    let p = home.join("providers.toml");
    if !p.exists() {
        std::fs::write(&p, DEFAULT_PROVIDERS)?;
    }
    load_dotenv(&home.join(".env"));
    ModelPool::load(&p, &home.join("pool_state.json"))
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
        });
    }
}

#[derive(Deserialize)]
struct NewRun {
    goal: String,
    workspace: Option<PathBuf>,
    max_steps: Option<u64>,
    max_hours: Option<f64>,
}

async fn create_run(State(app): State<App>, Json(req): Json<NewRun>) -> Result<Json<Value>, (StatusCode, String)> {
    if req.goal.trim().is_empty() {
        return Err((StatusCode::BAD_REQUEST, "goal is empty".into()));
    }
    // Each run gets its own folder unless the owner points it at a project.
    let ws_root = app.home.join("work");
    let (j, mut info) = Journal::create(&app.runs_dir(), &req.goal, &ws_root, req.max_steps.unwrap_or(2000), req.max_hours.unwrap_or(12.0))
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    info.workspace = req.workspace.unwrap_or_else(|| ws_root.join(&info.id));
    let _ = std::fs::create_dir_all(&info.workspace);
    j.save_info(&info).map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    app.spawn(info.id.clone()).await;
    Ok(Json(json!(info)))
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
    if q.contains_key("refresh") || cached.is_none() {
        return match probe_all(&app.home).await {
            Ok(rows) => Json(json!(rows)),
            Err(e) => Json(json!({"error": e.to_string()})),
        };
    }
    Json(cached.unwrap_or(json!([])))
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
    Json(json!({
        "service": "lokid",
        "version": env!("CARGO_PKG_VERSION"),
        "home": app.home,
        "active_runs": app.live.lock().await.len(),
        "launcher": launcher,
    }))
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
    let pool = Arc::new(Mutex::new(pool));
    let app = App { home: home.clone(), driver: Arc::new(Driver::new(pool)), live: Arc::new(Mutex::new(HashMap::new())) };
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
        .with_state(app.clone());
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
