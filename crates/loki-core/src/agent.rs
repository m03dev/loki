//! The long-running driver loop.
//!
//! One agent, one loop, one tool call per turn. A run plans a checklist once,
//! then works task by task, checkpointing after every step so it can go for
//! hours, survive restarts, and rest (not die) when free providers hit caps.
//! The model never decides a task is done on its own word: the driver re-runs
//! the task's check.

use crate::journal::{Journal, RunInfo, Status, Task, TaskState};
use crate::llm::{Llm, LlmError, Msg, ToolCall};
use crate::pool::{ModelPool, Role};
use crate::tools::{self, Outcome, Policy};
use serde_json::{json, Value};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Mutex;

const SYSTEM: &str = "You are LOKI's driver: a patient production artist and technical director working \
on a long job by yourself. You work in a workspace folder on the owner's machine.\n\
Rules:\n\
- Reply with exactly ONE tool call per turn. No chit-chat.\n\
- If there is no checklist yet, call `plan` first: 2-12 tasks, each producing something real. Every task's check \
proves its OUTPUT exists: 'file:<output path>' (best) or 'cmd:<command that verifies>'. Never plan tasks just to \
create folders: write_file creates missing folders itself.\n\
- `run` takes ONE program per call: no &&, ;, |, > or < (those need the owner's OK). Use the commands of the \
machine described under MACHINE (on Windows: cmd.exe, not bash).\n\
- Work only on the CURRENT TASK. When its check should hold, call `mark_done`; the driver verifies it.\n\
- If something fails, read the error, change your approach. Never repeat the exact same action.\n\
- If a task is impossible right now, `block_task` with the reason and move on.\n\
- Use `note` for decisions worth remembering. Use `ask_owner` only when a choice is truly the owner's.\n\
- Never claim results you did not produce.";

pub struct DriverConfig {
    /// Recent tool exchanges kept verbatim; older ones are compacted.
    pub window: usize,
    /// Give up on one task after this many failed attempts.
    pub max_task_attempts: u32,
    /// Longest single rest when every provider is busy.
    pub rest_cap: Duration,
    pub policy: Policy,
}

impl Default for DriverConfig {
    fn default() -> Self {
        Self { window: 8, max_task_attempts: 12, rest_cap: Duration::from_secs(300), policy: Policy::default() }
    }
}

pub struct Driver {
    pub pool: Arc<Mutex<ModelPool>>,
    pub llm: Llm,
    pub cfg: DriverConfig,
    /// What this machine is and which programs it has (OS, shell, Blender, Python...).
    pub machine: String,
}

struct Exchange {
    call: ToolCall,
    result: String,
}

fn current_task(tasks: &[Task]) -> Option<&Task> {
    tasks.iter().find(|t| t.state == TaskState::Todo)
}

fn render_tasks(tasks: &[Task]) -> String {
    if tasks.is_empty() {
        return "(no checklist yet - call `plan`)".into();
    }
    tasks
        .iter()
        .map(|t| {
            let mark = match t.state { TaskState::Passed => "[x]", TaskState::Blocked => "[!]", TaskState::Todo => "[ ]" };
            format!("{mark} #{} {} (check: {})", t.id, t.title, t.check)
        })
        .collect::<Vec<_>>()
        .join("\n")
}

impl Driver {
    pub fn new(pool: Arc<Mutex<ModelPool>>) -> Self {
        Self { pool, llm: Llm::new(), cfg: DriverConfig::default(), machine: machine_note() }
    }

    fn context(&self, j: &Journal, info: &RunInfo, tasks: &[Task], recent: &[Exchange], nudge: Option<&str>) -> Vec<Msg> {
        let mut state = format!("MACHINE:\n{}\nWorkspace: {}\n\nGOAL:\n{}\n\nCHECKLIST:\n{}\n", self.machine, info.workspace.display(), info.goal, render_tasks(tasks));
        if let Some(t) = current_task(tasks) {
            state.push_str(&format!("\nCURRENT TASK: #{} {}\nCheck: {}\n", t.id, t.title, t.check));
        }
        let summary = j.summary();
        if !summary.trim().is_empty() {
            state.push_str(&format!("\nEARLIER WORK (compacted):\n{summary}\n"));
        }
        let tail = j.progress_tail(12);
        if !tail.is_empty() {
            state.push_str(&format!("\nRECENT LOG:\n{tail}\n"));
        }
        let mut msgs = vec![Msg::system(SYSTEM), Msg::user(state)];
        for ex in recent {
            msgs.push(Msg::assistant(json!({"tool": ex.call.name, "args": ex.call.args}).to_string()));
            msgs.push(Msg::user(format!("RESULT of {}:\n{}", ex.call.name, ex.result)));
        }
        if let Some(n) = nudge {
            msgs.push(Msg::user(n.to_string()));
        }
        msgs
    }

    /// Fold the oldest exchanges into summary.md so context stays small forever.
    async fn compact(&self, j: &Journal, recent: &mut Vec<Exchange>) {
        if recent.len() <= self.cfg.window {
            return;
        }
        let spill: Vec<Exchange> = recent.drain(..recent.len() - self.cfg.window).collect();
        let raw: String = spill
            .iter()
            .map(|e| format!("- {} {} -> {}", e.call.name, short(&e.call.args.to_string(), 160), short(&e.result, 200)))
            .collect::<Vec<_>>()
            .join("\n");
        let prev = j.summary();
        let ask = vec![
            Msg::system("Compress an agent's work log into at most 12 terse bullet points: facts learned, files made, what failed and why. No preamble."),
            Msg::user(format!("EXISTING SUMMARY:\n{prev}\n\nNEW LOG:\n{raw}")),
        ];
        let merged = match self.llm.chat(&self.pool, Role::Fast, &ask, &json!([])).await {
            Ok(r) if !r.text.trim().is_empty() => r.text,
            // No fast model free right now: keep a mechanical summary instead of losing it.
            _ => format!("{prev}\n{raw}").lines().rev().take(40).collect::<Vec<_>>().into_iter().rev().collect::<Vec<_>>().join("\n"),
        };
        j.save_summary(&merged);
    }

    /// Run until done, stopped, out of budget, or waiting on the owner.
    pub async fn run(&self, j: &Journal, stop: Arc<AtomicBool>) -> anyhow::Result<RunInfo> {
        let mut info = j.info()?;
        let started = std::time::Instant::now();
        let mut recent: Vec<Exchange> = Vec::new();
        let mut nudge: Option<String> = None;
        let mut silent_turns = 0u32;

        // Coming back from a pause: apply the owner's answer first.
        if let Some(reply) = info.owner_reply.take() {
            if let Some(p) = info.pending.take() {
                let call = ToolCall { name: p["name"].as_str().unwrap_or("").into(), args: p["args"].clone() };
                let result = if reply.approve {
                    match self.exec(j, &mut info, &call, true).await { Outcome::Ok(s) | Outcome::Err(s) | Outcome::NeedsOwner(s) => s }
                } else {
                    format!("Owner declined. {}", reply.note)
                };
                j.progress(&format!("owner {} {}", if reply.approve { "approved" } else { "declined" }, call.name));
                recent.push(Exchange { call, result });
            } else {
                nudge = Some(format!("OWNER ANSWERED: {}", reply.note));
                j.progress(&format!("owner answered: {}", reply.note));
            }
            info.waiting_for = None;
        }
        info.status = if j.tasks().is_empty() { Status::Planning } else { Status::Running };
        j.save_info(&info)?;

        loop {
            if stop.load(Ordering::SeqCst) {
                info.status = Status::Stopped;
                j.progress("stopped by owner");
                break;
            }
            if info.steps >= info.max_steps {
                info.status = Status::Stopped;
                j.progress(&format!("step budget reached ({})", info.max_steps));
                break;
            }
            if started.elapsed().as_secs_f64() / 3600.0 >= info.max_hours {
                info.status = Status::Stopped;
                j.progress(&format!("time budget reached ({}h)", info.max_hours));
                break;
            }
            let tasks = j.tasks();
            if !tasks.is_empty() && current_task(&tasks).is_none() {
                let blocked = tasks.iter().filter(|t| t.state == TaskState::Blocked).count();
                info.status = Status::Done;
                j.progress(&format!("all tasks finished ({} passed, {blocked} blocked)", tasks.len() - blocked));
                break;
            }

            self.compact(j, &mut recent).await;
            let msgs = self.context(j, &info, &tasks, &recent, nudge.as_deref());
            nudge = None;
            let reply = match self.llm.chat(&self.pool, Role::Brain, &msgs, &tools::schemas()).await {
                Ok(r) => r,
                Err(LlmError::AllBusy { retry_in_secs }) => {
                    info.status = Status::Resting;
                    j.save_info(&info)?;
                    let wait = Duration::from_secs(retry_in_secs.max(1) as u64).min(self.cfg.rest_cap);
                    j.progress(&format!("all free providers busy, resting {}s", wait.as_secs()));
                    tokio::time::sleep(wait).await;
                    info.status = Status::Running;
                    continue;
                }
                Err(LlmError::Other(e)) => {
                    info.last_error = Some(e);
                    tokio::time::sleep(Duration::from_secs(2)).await;
                    continue;
                }
            };
            info.steps += 1;
            info.status = if tasks.is_empty() { Status::Planning } else { Status::Running };

            let Some(call) = reply.call else {
                silent_turns += 1;
                j.log_step(&json!({"step": info.steps, "provider": reply.provider, "text": short(&reply.text, 400)}));
                nudge = Some(if silent_turns >= 3 {
                    "You have answered 3 times without a tool call. Reply ONLY with JSON like {\"tool\":\"note\",\"args\":{\"text\":\"...\"}}.".into()
                } else {
                    "Reply with exactly one tool call.".into()
                });
                j.save_info(&info)?;
                continue;
            };
            silent_turns = 0;

            // Stall guard: the same action three times in a row means it's stuck.
            let repeats = recent.iter().rev().take(2).filter(|e| e.call == call).count();
            if repeats == 2 {
                nudge = Some("You just repeated the same action three times. Do something different, or block_task.".into());
                self.bump_attempt(j);
            }

            let outcome = self.exec(j, &mut info, &call, false).await;
            let (result, paused) = match outcome {
                Outcome::Ok(s) => (s, false),
                Outcome::Err(s) => {
                    self.bump_attempt(j);
                    (format!("ERROR: {s}"), false)
                }
                Outcome::NeedsOwner(s) => {
                    info.pending = Some(json!({"name": call.name, "args": call.args}));
                    info.waiting_for = Some(s.clone());
                    info.status = Status::Waiting;
                    (s, true)
                }
            };
            j.log_step(&json!({"step": info.steps, "provider": reply.provider, "model": reply.model,
                "tool": call.name, "args": call.args, "result": short(&result, 2000)}));
            j.save_info(&info)?;
            if paused {
                j.progress(&format!("waiting for owner: {}", short(&result, 200)));
                return Ok(info);
            }
            recent.push(Exchange { call, result });
        }
        j.save_info(&info)?;
        Ok(info)
    }

    fn bump_attempt(&self, j: &Journal) {
        let mut tasks = j.tasks();
        let max = self.cfg.max_task_attempts;
        if let Some(t) = tasks.iter_mut().find(|t| t.state == TaskState::Todo) {
            t.attempts += 1;
            if t.attempts >= max {
                t.state = TaskState::Blocked;
                t.evidence = format!("auto-blocked after {max} failed attempts");
                j.progress(&format!("task #{} auto-blocked after {max} failed attempts", t.id));
            }
        }
        let _ = j.save_tasks(&tasks);
    }

    async fn exec(&self, j: &Journal, info: &mut RunInfo, call: &ToolCall, approved: bool) -> Outcome {
        let ws = info.workspace.clone();
        let a = &call.args;
        match call.name.as_str() {
            "plan" => {
                let Some(list) = a["tasks"].as_array() else { return Outcome::Err("'tasks' must be a list".into()) };
                let mut tasks = j.tasks();
                if tasks.iter().any(|t| t.state == TaskState::Passed) {
                    return Outcome::Err("a checklist already exists; use add_task".into());
                }
                tasks = list
                    .iter()
                    .enumerate()
                    .filter_map(|(i, t)| {
                        let title = t["title"].as_str()?.to_string();
                        let check = t["check"].as_str().unwrap_or("self-check").to_string();
                        Some(Task { id: i as u32 + 1, title, check, state: TaskState::Todo, evidence: String::new(), attempts: 0 })
                    })
                    .collect();
                if tasks.is_empty() {
                    return Outcome::Err("plan needs at least one task with a title".into());
                }
                let _ = j.save_tasks(&tasks);
                j.progress(&format!("planned {} tasks", tasks.len()));
                info.status = Status::Running;
                Outcome::Ok(format!("checklist saved:\n{}", render_tasks(&tasks)))
            }
            "add_task" => {
                let mut tasks = j.tasks();
                let Some(title) = a["title"].as_str() else { return Outcome::Err("missing 'title'".into()) };
                let id = tasks.iter().map(|t| t.id).max().unwrap_or(0) + 1;
                tasks.push(Task { id, title: title.into(), check: a["check"].as_str().unwrap_or("self-check").into(), state: TaskState::Todo, evidence: String::new(), attempts: 0 });
                let _ = j.save_tasks(&tasks);
                j.progress(&format!("added task #{id} {title}"));
                Outcome::Ok(format!("added task #{id}"))
            }
            "mark_done" => {
                let mut tasks = j.tasks();
                let id = a["task_id"].as_u64().unwrap_or(0) as u32;
                let Some(t) = tasks.iter_mut().find(|t| t.id == id) else { return Outcome::Err(format!("no task #{id}")) };
                match tools::verify(&ws, &self.cfg.policy, &t.check).await {
                    Ok(proof) => {
                        t.state = TaskState::Passed;
                        t.evidence = format!("{} | verified: {}", a["evidence"].as_str().unwrap_or(""), short(&proof, 200));
                        let title = t.title.clone();
                        let _ = j.save_tasks(&tasks);
                        j.progress(&format!("PASSED #{id} {title}"));
                        Outcome::Ok(format!("task #{id} verified and passed"))
                    }
                    Err(why) => Outcome::Err(format!("check failed for #{id}: {why}. Fix it, then mark_done again.")),
                }
            }
            "block_task" => {
                let mut tasks = j.tasks();
                let id = a["task_id"].as_u64().unwrap_or(0) as u32;
                let Some(t) = tasks.iter_mut().find(|t| t.id == id) else { return Outcome::Err(format!("no task #{id}")) };
                t.state = TaskState::Blocked;
                t.evidence = a["reason"].as_str().unwrap_or("").into();
                let _ = j.save_tasks(&tasks);
                j.progress(&format!("blocked #{id}: {}", a["reason"].as_str().unwrap_or("")));
                Outcome::Ok(format!("task #{id} blocked; moving on"))
            }
            "note" => {
                j.progress(&format!("note: {}", a["text"].as_str().unwrap_or("")));
                Outcome::Ok("noted".into())
            }
            "ask_owner" => {
                let q = a["question"].as_str().unwrap_or("?");
                let opts: Vec<String> = a["options"].as_array().map(|o| o.iter().filter_map(|x| x.as_str().map(String::from)).collect()).unwrap_or_default();
                if approved {
                    return Outcome::Ok("owner was asked".into());
                }
                Outcome::NeedsOwner(if opts.is_empty() { q.to_string() } else { format!("{q} Options: {}", opts.join(" / ")) })
            }
            "list_dir" => tools::list_dir(&ws, a),
            "read_file" => tools::read_file(&ws, a),
            "write_file" => {
                let r = tools::write_file(&ws, a);
                if let Outcome::Ok(s) = &r { j.progress(s); }
                r
            }
            "run" => tools::run(&ws, &self.cfg.policy, a, approved).await,
            other => Outcome::Err(format!("unknown tool '{other}'. Available: plan, list_dir, read_file, write_file, run, mark_done, block_task, add_task, note, ask_owner")),
        }
    }
}

/// OS, shell and the creative tools found on PATH, so the model uses the right commands.
pub fn machine_note() -> String {
    let os = match std::env::consts::OS { "windows" => "Windows", "macos" => "macOS", "linux" => "Linux", o => o };
    let shell = if cfg!(windows) { "cmd.exe (Windows commands: dir, copy, mkdir without -p)" } else { "sh" };
    let mut have = Vec::new();
    for prog in ["blender", "python", "python3", "ffmpeg", "magick", "git", "node"] {
        if let Some(p) = which(prog) {
            have.push(format!("{prog} ({})", p.display()));
        }
    }
    format!("{os} {}, shell for `run`: {shell}\nPrograms available: {}", std::env::consts::ARCH,
        if have.is_empty() { "none found".into() } else { have.join(", ") })
}

fn which(prog: &str) -> Option<std::path::PathBuf> {
    let exts: Vec<String> = if cfg!(windows) { vec![".exe".into(), ".cmd".into(), ".bat".into()] } else { vec![String::new()] };
    let path = std::env::var_os("PATH")?;
    for dir in std::env::split_paths(&path) {
        for e in &exts {
            let c = dir.join(format!("{prog}{e}"));
            if c.is_file() {
                return Some(c);
            }
        }
    }
    None
}

fn short(s: &str, n: usize) -> String {
    if s.chars().count() <= n { s.to_string() } else { format!("{}…", s.chars().take(n).collect::<String>()) }
}

/// Convenience for callers that only have a JSON value for a tool call.
pub fn call_from(v: &Value) -> Option<ToolCall> {
    Some(ToolCall { name: v["name"].as_str()?.to_string(), args: v["args"].clone() })
}
