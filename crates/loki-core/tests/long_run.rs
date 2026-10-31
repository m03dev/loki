//! End-to-end: a scripted fake model drives a whole run through the real
//! driver - planning, a refused premature "done", a repaired text tool call,
//! a capped provider being skipped, a pause for the owner, and resuming.

use axum::{extract::State, routing::post, Json, Router};
use loki_core::agent::Driver;
use loki_core::journal::{Journal, OwnerReply, Status, TaskState};
use loki_core::pool::{ModelPool, Provider, Role};
use serde_json::{json, Value};
use std::collections::{HashMap, VecDeque};
use std::sync::atomic::AtomicBool;
use std::sync::Arc;
use tokio::sync::Mutex;

fn call(name: &str, args: Value) -> Value {
    json!({"choices":[{"message":{"content":"","tool_calls":[{"id":"c","type":"function",
        "function":{"name":name,"arguments":args.to_string()}}]}}]})
}
fn text(t: &str) -> Value { json!({"choices":[{"message":{"content":t}}]}) }

async fn serve(router: Router) -> String {
    let l = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = l.local_addr().unwrap();
    tokio::spawn(async move { axum::serve(l, router).await.unwrap() });
    format!("http://{addr}/v1")
}

fn provider(name: &str, url: &str, priority: i32) -> Provider {
    Provider { name: name.into(), base_url: url.into(), key_env: String::new(),
        models: HashMap::from([(Role::Brain, "m".to_string())]), rpm: 1000, rpd: 0, priority, local: false }
}

#[tokio::test]
async fn full_run_with_failover_verification_and_owner_pause() {
    // Provider that is always over its free cap.
    let capped = serve(Router::new().route("/v1/chat/completions",
        post(|| async { (axum::http::StatusCode::TOO_MANY_REQUESTS, "slow down") }))).await;

    let script: VecDeque<Value> = VecDeque::from(vec![
        call("plan", json!({"tasks":[
            {"title":"Write the brief","check":"file:brief.md"},
            {"title":"Write the shot list","check":"file:shots/list.md"}]})),
        call("mark_done", json!({"task_id":1,"evidence":"done"})),              // premature: must fail
        call("write_file", json!({"path":"brief.md","content":"# Dragon ad\nRed baby dragon on gold."})),
        call("mark_done", json!({"task_id":1,"evidence":"brief written"})),
        // Free models often write the call as text; the driver must repair it.
        text("Next:\n```json\n{\"tool\":\"write_file\",\"args\":{\"path\":\"shots/list.md\",\"content\":\"1. wide\\n2. close\"},}\n```"),
        call("run", json!({"command":"rm -rf old_renders","why":"clean old renders"})), // not auto -> owner
        call("mark_done", json!({"task_id":2,"evidence":"list written"})),
    ]);
    let script = Arc::new(Mutex::new(script));
    let good = serve(Router::new().route("/v1/chat/completions", post(
        |State(s): State<Arc<Mutex<VecDeque<Value>>>>, Json(_b): Json<Value>| async move {
            Json(s.lock().await.pop_front().unwrap_or_else(|| text("nothing left")))
        })).with_state(script.clone())).await;

    let pool = ModelPool::new(vec![provider("capped", &capped, 1), provider("good", &good, 2)]);
    let driver = Driver::new(Arc::new(Mutex::new(pool)));

    let root = std::env::temp_dir().join(format!("lokitest-{}", std::process::id()));
    let ws = root.join("ws");
    let (j, _) = Journal::create(&root.join("runs"), "Make a dragon ad brief and shot list", &ws, 50, 1.0).unwrap();

    // First leg: runs until it needs the owner.
    let info = driver.run(&j, Arc::new(AtomicBool::new(false))).await.unwrap();
    assert_eq!(info.status, Status::Waiting, "should pause for the unlisted command");
    let w = info.waiting_for.as_deref().unwrap();
    assert!(w.contains("clean old renders") && w.contains("Deletes old_renders"), "plain summary, not a raw command: {w}");
    let sum = &info.pending.as_ref().unwrap()["summary"];
    assert_eq!(sum["risk"], "high");
    assert_eq!(sum["what"], "Deletes old_renders");
    let tasks = j.tasks();
    assert_eq!(tasks[0].state, TaskState::Passed, "task 1 passes only after the file exists");
    assert!(tasks[0].evidence.contains("verified"));
    assert!(ws.join("shots/list.md").exists(), "repaired text tool call was executed");
    assert!(j.progress_tail(50).contains("check failed") || std::fs::read_to_string(j.dir.join("steps.jsonl")).unwrap().contains("check failed"));

    // Owner says no; the run resumes from disk and finishes.
    let mut info = j.info().unwrap();
    info.owner_reply = Some(OwnerReply { approve: false, note: "keep them".into() });
    j.save_info(&info).unwrap();
    let info = driver.run(&Journal::open(&j.dir), Arc::new(AtomicBool::new(false))).await.unwrap();
    assert_eq!(info.status, Status::Done);
    assert!(j.tasks().iter().all(|t| t.state == TaskState::Passed));
    assert!(!ws.join("old_renders").exists());
    let log = j.progress_tail(50);
    assert!(log.contains("owner declined run"), "{log}");
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn pool_rolls_over_and_respects_daily_caps() {
    let mut a = provider("a", "http://a", 1); a.rpd = 2;
    let b = provider("b", "http://b", 2);
    let mut pool = ModelPool::new(vec![a, b]);
    assert_eq!(pool.pick(Role::Brain, &[]).unwrap().provider.name, "a");
    assert_eq!(pool.pick(Role::Brain, &[]).unwrap().provider.name, "a");
    assert_eq!(pool.pick(Role::Brain, &[]).unwrap().provider.name, "b", "a is out of daily budget");
    pool.report_fail("b", true);
    assert!(pool.pick(Role::Brain, &[]).is_none(), "b cooling down, a capped");
    assert!(pool.next_ready(Role::Brain).is_some());
    assert!(pool.pick(Role::Vision, &[]).is_none(), "no vision model configured");
}

#[test]
fn local_models_follow_what_the_machine_has() {
    let mut o = provider("ollama", "http://x", 90);
    o.models.insert(Role::Fast, "qwen3:4b".into());
    let mut pool = ModelPool::new(vec![o]);
    let have = vec!["loki-huihui_ai-qwen3-abliterated-8b:latest".to_string(), "llama3:8b".to_string()];
    let changes = pool.fit_local("ollama", &have, None);
    assert_eq!(changes.len(), 2, "{changes:?}");
    assert!(pool.providers()[0].models.values().all(|m| m == "loki-huihui_ai-qwen3-abliterated-8b:latest"));
    let changes = pool.fit_local("ollama", &have, Some("llama3:8b"));
    assert!(pool.providers()[0].models.values().all(|m| m == "llama3:8b"), "{changes:?}");
}

#[tokio::test]
async fn chat_steering_edited_image_prompt_and_finish() {
    let script: VecDeque<Value> = VecDeque::from(vec![
        call("plan", json!({"tasks":[{"title":"Concept prompt","check":"self-check"}]})),
        call("image_prompt", json!({"prompt":"a dragon","purpose":"concept art"})),          // pauses for the owner
        call("mark_done", json!({"task_id":1,"evidence":"prompt approved"})),
        call("add_task", json!({"title":"Shot list","check":"file:shots.md"})),              // after OWNER SAYS
        call("write_file", json!({"path":"shots.md","content":"1. wide"})),
        call("tell_owner", json!({"text":"Shot list ready","files":["shots.md","missing.png"]})),
        call("mark_done", json!({"task_id":2,"evidence":"written"})),
    ]);
    let seen: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(vec![]));
    let st = (Arc::new(Mutex::new(script)), seen.clone());
    let url = serve(Router::new().route("/v1/chat/completions", post(
        |State((s, seen)): State<(Arc<Mutex<VecDeque<Value>>>, Arc<Mutex<Vec<String>>>)>, Json(b): Json<Value>| async move {
            seen.lock().await.push(b["messages"].to_string());
            Json(s.lock().await.pop_front().unwrap_or_else(|| text("nothing left")))
        })).with_state(st)).await;
    let driver = Driver::new(Arc::new(Mutex::new(ModelPool::new(vec![provider("good", &url, 1)]))));
    let root = std::env::temp_dir().join(format!("lokichat-{}", std::process::id()));
    let (j, _) = Journal::create(&root.join("runs"), "Make dragon concept art", &root.join("ws"), 50, 1.0).unwrap();

    let info = driver.run(&j, Arc::new(AtomicBool::new(false))).await.unwrap();
    assert_eq!(info.status, Status::Waiting);
    assert_eq!(info.pending.as_ref().unwrap()["name"], "image_prompt");

    // owner edits the prompt and also sends a chat message asking for more work
    let mut info = j.info().unwrap();
    info.owner_reply = Some(OwnerReply { approve: true, note: "a small red baby dragon guarding gold, painterly".into() });
    j.save_info(&info).unwrap();
    j.say("owner", "also write a shot list", vec![]);
    let info = driver.run(&Journal::open(&j.dir), Arc::new(AtomicBool::new(false))).await.unwrap();
    assert_eq!(info.status, Status::Done, "{}", j.progress_tail(40));
    let prompts = seen.lock().await.join("\n");
    assert!(prompts.contains("APPROVED PROMPT (use exactly): a small red baby dragon guarding gold, painterly"), "edited prompt reached the model");
    assert!(prompts.contains("OWNER SAYS"), "owner message steered the job");
    let chat = j.chat();
    let tell = chat.iter().find(|c| c.text == "Shot list ready").unwrap_or_else(|| panic!("{:#?}\n{}", chat, j.progress_tail(40)));
    assert_eq!(tell.files, vec!["shots.md".to_string()], "only files that exist are attached");
    assert_eq!(chat.last().unwrap().from, "loki", "the job closes with a message");
    let _ = std::fs::remove_dir_all(root);
}

#[tokio::test]
async fn a_plain_question_finishes_without_a_plan() {
    let script = Arc::new(Mutex::new(VecDeque::from(vec![
        call("finish", json!({"summary":"I can model, render and approve-gate images."})),
    ])));
    let url = serve(Router::new().route("/v1/chat/completions", post(
        |State(s): State<Arc<Mutex<VecDeque<Value>>>>, Json(_b): Json<Value>| async move {
            Json(s.lock().await.pop_front().unwrap_or_else(|| text("nothing left")))
        })).with_state(script)).await;
    let driver = Driver::new(Arc::new(Mutex::new(ModelPool::new(vec![provider("good", &url, 1)]))));
    let root = std::env::temp_dir().join(format!("lokiq-{}", std::process::id()));
    let (j, _) = Journal::create(&root.join("runs"), "What can you do?", &root.join("ws"), 10, 1.0).unwrap();
    let info = driver.run(&j, Arc::new(AtomicBool::new(false))).await.unwrap();
    assert_eq!(info.status, Status::Done);
    assert_eq!(info.steps, 1);
    assert!(j.chat().last().unwrap().text.contains("I can model"));
    let _ = std::fs::remove_dir_all(root);
}

#[tokio::test]
async fn a_model_that_never_progresses_runs_to_its_budget_without_pausing() {
    let url = serve(Router::new().route("/v1/chat/completions", post(|| async { Json(call("note", json!({"text":"thinking"}))) }))).await;
    let driver = Driver::new(Arc::new(Mutex::new(ModelPool::new(vec![provider("good", &url, 1)]))));
    let root = std::env::temp_dir().join(format!("lokistuck-{}", std::process::id()));
    let (j, _) = Journal::create(&root.join("runs"), "Do something", &root.join("ws"), 60, 1.0).unwrap();
    let info = driver.run(&j, Arc::new(AtomicBool::new(false))).await.unwrap();
    // owner 2026-10-30: no stall question - a job works until it is done or out of budget
    assert_eq!(info.status, Status::Stopped);
    assert!(info.waiting_for.is_none());
    let _ = std::fs::remove_dir_all(root);
}

#[tokio::test]
async fn interview_first_then_plan_with_the_owners_choices() {
    let script = Arc::new(Mutex::new(VecDeque::from(vec![
        call("plan", json!({"tasks":[{"title":"a","check":"self-check"},{"title":"b","check":"self-check"}]})), // refused once
        call("interview", json!({"questions":[{"header":"Style","question":"Which look?","options":[{"label":"Painterly"},{"label":"Pixel art"}]}]})),
        call("plan", json!({"tasks":[{"title":"Concept","check":"self-check"}]})),
        call("mark_done", json!({"task_id":1,"evidence":"ok"})),
    ])));
    let seen: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(vec![]));
    let st = (script, seen.clone());
    let url = serve(Router::new().route("/v1/chat/completions", post(
        |State((s, seen)): State<(Arc<Mutex<VecDeque<Value>>>, Arc<Mutex<Vec<String>>>)>, Json(b): Json<Value>| async move {
            seen.lock().await.push(b["messages"].to_string());
            Json(s.lock().await.pop_front().unwrap_or_else(|| text("nothing left")))
        })).with_state(st)).await;
    let driver = Driver::new(Arc::new(Mutex::new(ModelPool::new(vec![provider("good", &url, 1)]))));
    let root = std::env::temp_dir().join(format!("lokiiv-{}", std::process::id()));
    let (j, mut info) = Journal::create(&root.join("runs"), "Paint a red baby dragon", &root.join("ws"), 30, 1.0).unwrap();
    info.interview = "always".into();
    j.save_info(&info).unwrap();
    let info = driver.run(&j, Arc::new(AtomicBool::new(false))).await.unwrap();
    assert_eq!(info.status, Status::Waiting);
    assert_eq!(info.pending.as_ref().unwrap()["name"], "interview");
    let mut info = j.info().unwrap();
    info.owner_reply = Some(OwnerReply { approve: true, note: "Style: Painterly".into() });
    j.save_info(&info).unwrap();
    let info = driver.run(&Journal::open(&j.dir), Arc::new(AtomicBool::new(false))).await.unwrap();
    assert_eq!(info.status, Status::Done, "{}", j.progress_tail(30));
    assert!(seen.lock().await.join("").contains("OWNER'S CHOICES (from the interview): Style: Painterly"));
    let _ = std::fs::remove_dir_all(root);
}

#[tokio::test]
async fn a_checked_step_cannot_be_dropped_before_three_tries() {
    let script = Arc::new(Mutex::new(VecDeque::from(vec![
        call("plan", json!({"tasks":[{"title":"Render","check":"file:r.png"}]})),
        call("block_task", json!({"task_id":1,"reason":"hard"})),      // refused
        call("write_file", json!({"path":"r.png","content":"x"})),
        call("mark_done", json!({"task_id":1,"evidence":"made"})),
    ])));
    let url = serve(Router::new().route("/v1/chat/completions", post(
        |State(s): State<Arc<Mutex<VecDeque<Value>>>>, Json(_b): Json<Value>| async move {
            Json(s.lock().await.pop_front().unwrap_or_else(|| text("nothing left")))
        })).with_state(script)).await;
    let driver = Driver::new(Arc::new(Mutex::new(ModelPool::new(vec![provider("good", &url, 1)]))));
    let root = std::env::temp_dir().join(format!("lokiblock-{}", std::process::id()));
    let (j, _) = Journal::create(&root.join("runs"), "Render it", &root.join("ws"), 20, 1.0).unwrap();
    let info = driver.run(&j, Arc::new(AtomicBool::new(false))).await.unwrap();
    assert_eq!(info.status, Status::Done);
    assert_eq!(j.tasks()[0].state, TaskState::Passed, "the step was fixed, not dropped");
    let _ = std::fs::remove_dir_all(root);
}
