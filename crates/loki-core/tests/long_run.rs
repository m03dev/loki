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
    assert!(info.waiting_for.as_deref().unwrap().contains("rm -rf old_renders"));
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
