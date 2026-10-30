//! The long-running driver loop.
//!
//! One agent, one loop, one tool call per turn. A run plans a checklist once,
//! then works task by task, checkpointing after every step so it can go for
//! hours, survive restarts, and rest (not die) when free providers hit caps.
//! The model never decides a task is done on its own word: the driver re-runs
//! the task's check.

use crate::journal::{Journal, RunInfo, Status, Task, TaskState};
use crate::knowledge::Knowledge;
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
- Work only on the CURRENT TASK. When its check should hold, call `mark_done` right away; the driver verifies \
the files itself, so never list folders just to check your own work.\n\
- If something fails, read the error, change your approach. Never repeat the exact same action.\n\
- If a task is impossible right now, `block_task` with the reason and move on.\n\
- Use `note` for decisions worth remembering. Use `ask_owner` only when a choice is truly the owner's.\n\
- The owner chats with you while you work. OWNER SAYS messages come first: change course, add_task, or answer \
with tell_owner. A plain question that needs no work: answer with `finish`.\n\
- Before generating ANY AI image, call `image_prompt` and then use exactly the prompt it returns.\n\
- When you produce something worth seeing (a render, an image, a model), `tell_owner` with the file attached.\n\
- Never claim results you did not produce.";

/// Steps without a passed check before the job stops and asks the owner.
const STALL_ASK: u32 = 30;

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
    /// Playbooks and the lessons notebook.
    pub knowledge: Knowledge,
    /// Blender for the scene inspector.
    pub blender: Option<String>,
    /// A `look:` check passes at this vision score or above.
    pub look_pass: f64,
}

/// LOKI's scene inspector, shipped inside the driver so every machine has the same one.
const INSPECT_SCRIPT: &str = include_str!("../../../tools/blender/inspect_scene.py");
/// The Blender helper library every job gets in scripts/ (placing, hinging, framing, rendering).
const LOKI_BPY: &str = include_str!("../../../tools/blender/loki_bpy.py");
const CAD_RENDER: &str = include_str!("../../../tools/cad/cad_render.py");

/// CAD tools the launcher installed into harness_data/cad after this driver started (found without a restart).
fn find_cad(key: &str) -> Option<String> {
    let cad = std::path::PathBuf::from(std::env::var("LOKI_HOME").ok()?).parent()?.join("cad");
    let found = if key == "LOKI_CAD_PY" {
        [cad.join("b123/Scripts/python.exe"), cad.join("b123/bin/python")].into_iter().find(|p| p.is_file())
    } else {
        let names = ["freecadcmd.exe", "FreeCADCmd.exe", "freecadcmd", "FreeCADCmd"];
        let mut hit = None;
        if let Ok(rd) = std::fs::read_dir(cad.join("freecad")) {
            'outer: for e in rd.flatten() {
                for sub in ["bin", "usr/bin", "Contents/Resources/bin", "Contents/MacOS"] {
                    for n in names {
                        let p = e.path().join(sub).join(n);
                        if p.is_file() { hit = Some(p); break 'outer; }
                    }
                }
            }
        }
        hit
    };
    found.map(|p| p.to_string_lossy().to_string())
}

/// The tools this machine really has, with exact paths (how to use each lives in its playbook, not here).
fn machine_tools(blender: Option<&str>) -> String {
    let mut lines = vec![];
    if let Some(b) = blender {
        lines.push(format!("Blender: \"{b}\" (scripts/loki_bpy.py helpers are in the job folder)"));
    }
    for (k, what) in [("LOKI_CAD_PY", "build123d (CAD): run scripts with"), ("LOKI_FREECAD", "FreeCAD (CAD, headless): run scripts with")] {
        if let Some(p) = std::env::var(k).ok().filter(|p| std::path::Path::new(p).is_file()).or_else(|| find_cad(k)) {
            lines.push(format!("{what} \"{p}\""));
        }
    }
    if lines.is_empty() { return String::new(); }
    format!("\nMACHINE TOOLS (exact paths):\n- {}\n- scripts/cad_render.py renders CAD parts (parts/<material>.stl) in Blender.\n", lines.join("\n- "))
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
        let blender = std::env::var("LOKI_BLENDER").ok().filter(|b| std::path::Path::new(b).is_file())
            .or_else(|| which("blender").map(|p| p.to_string_lossy().to_string()));
        Self { pool, llm: Llm::new(), cfg: DriverConfig::default(), machine: machine_note(), knowledge: Knowledge::default(), blender, look_pass: 7.0 }
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
        let chat = j.chat();
        if chat.len() > 1 {
            let conv: Vec<String> = chat[chat.len().saturating_sub(8)..]
                .iter()
                .map(|c| format!("{}: {}", if c.from == "owner" { "OWNER" } else { "YOU" }, short(&c.text, 400)))
                .collect();
            state.push_str(&format!("\nCONVERSATION (latest last):\n{}\n", conv.join("\n")));
        }
        let tail = j.progress_tail(12);
        if !tail.is_empty() {
            state.push_str(&format!("\nRECENT LOG:\n{tail}\n"));
        }
        let mut system = SYSTEM.to_string();
        if !info.interviewed && info.interview != "off" {
            system.push_str(&format!("\nINTERVIEW ({}): before `plan`, if the goal makes or changes something and leaves real \
choices open, call `interview` once with 1-3 questions (skip anything the goal already says). Good questions by kind - \
image: Style, Framing, Shape (16:9 / 1:1 / 9:16); turnaround: Views, Pose (T / A); 3D model: Use (game asset / hero detail / \
blockout), Start from (concept / Blender from scratch); video: Length, Shape, Look; writing: Length, Tone. {}\n",
                info.interview,
                if info.interview == "big" { "Only for big jobs (several outputs or hours of work)." } else { "Plain questions are never interviewed." }));
        }
        system.push_str(&machine_tools(self.blender.as_deref()));
        system.push_str("\n- 3D / render work: after building, call inspect_scene on the .blend and fix every error; plan checks as \
'blend:<file.blend>' and 'look:<render.png>' so the work is judged on what it made. After fixing a real error, call `learn`.\n");
        for pb in self.knowledge.pick(&info.goal, 2) {
            let body: String = pb.body.chars().take(2800).collect();
            system.push_str(&format!("\nPLAYBOOK {} - {}\n{}\n", pb.name, pb.description, body));
        }
        let lessons = self.knowledge.lessons_for(&info.goal, 14);
        if !lessons.is_empty() {
            system.push_str(&format!("\nLESSONS (learned from real errors - follow them):\n- {}\n", lessons.join("\n- ")));
        }
        let mut msgs = vec![Msg::system(system), Msg::user(state)];
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
        // An owner request stays in front of the model until it acts on it.
        let mut owner_request: Option<String> = None;
        // Turns in a row that changed nothing (notes, looking around, errors, no tool call),
        // kept in run.json so pauses and approvals don't reset it.
        let mut idle_turns = info.idle_turns;
        // jobs from before this counter existed: count from the journal
        if info.since_pass == 0 && info.steps > 0 {
            let steps = j.steps();
            let last = steps.iter().rposition(|s| s["tool"] == "mark_done" && s["result"].as_str().is_some_and(|r| r.contains("passed")));
            info.since_pass = (steps.len() - last.map(|i| i + 1).unwrap_or(0)) as u32;
        }
        // the first error line of the last failed run, to ask for a lesson once it is fixed
        let mut fixed_error: Option<String> = None;

        // Coming back from a pause: apply the owner's answer first.
        if let Some(reply) = info.owner_reply.take() {
            if info.since_pass >= STALL_ASK {
                info.since_pass = STALL_ASK / 2; // the owner answered the stall question: another round, not forever
            }
            if let Some(p) = info.pending.take() {
                let mut call = ToolCall { name: p["name"].as_str().unwrap_or("").into(), args: p["args"].clone() };
                let note = reply.note.trim().to_string();
                if call.name == "image_prompt" && reply.approve && !note.is_empty() {
                    call.args["prompt"] = json!(note); // the owner edited the prompt
                }
                if reply.approve && call.name == "run" {
                    if let Some(c) = call.args["command"].as_str() {
                        if !info.approved_commands.iter().any(|x| x == c) {
                            info.approved_commands.push(c.to_string());
                        }
                    }
                }
                if call.name == "interview" {
                    info.interviewed = true;
                }
                let result = if call.name == "interview" {
                    if reply.approve && !note.is_empty() {
                        format!("OWNER'S CHOICES (from the interview): {note}\nPlan the job around these choices.")
                    } else {
                        "The owner chose 'go as written': use your best judgement and plan.".to_string()
                    }
                } else if call.name == "ask_owner" {
                    format!("OWNER ANSWERED: {}", if note.is_empty() { if reply.approve { "yes" } else { "no" } } else { &note })
                } else if reply.approve {
                    match self.exec(j, &mut info, &call, true).await { Outcome::Ok(s) | Outcome::Err(s) | Outcome::NeedsOwner(s) => s }
                } else {
                    format!("Owner declined. {}", reply.note)
                };
                let failed = result.starts_with("exit Some") || result.starts_with("Owner declined") || result.contains("timed out");
                idle_turns = if failed { idle_turns + 1 } else { 0 };
                j.progress(&format!("owner {} {}", if reply.approve { "approved" } else { "declined" }, call.name));
                j.log_step(&json!({"step": info.steps, "provider": "owner", "model": "", "tool": call.name, "args": call.args,
                    "result": short(&result, 2000), "owner": if reply.approve { "approved" } else { "declined" }}));
                recent.push(Exchange { call, result });
            } else {
                nudge = Some(format!("OWNER ANSWERED: {}", reply.note));
                j.progress(&format!("owner answered: {}", reply.note));
            }
            info.waiting_for = None;
        }
        info.status = if j.tasks().is_empty() { Status::Planning } else { Status::Running };
        j.save_info(&info)?;
        // every job gets the newest Blender helpers next to its scripts
        let scripts = info.workspace.join("scripts");
        if std::fs::create_dir_all(&scripts).is_ok() {
            let _ = std::fs::write(scripts.join("loki_bpy.py"), LOKI_BPY);
            let _ = std::fs::write(scripts.join("cad_render.py"), CAD_RENDER);
        }

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
            // New chat messages from the owner steer the job right away.
            let owner_msgs: Vec<String> = j.chat().into_iter().filter(|c| c.from == "owner").map(|c| c.text).collect();
            let fresh: Vec<String> = owner_msgs.iter().skip(info.owner_seen as usize).cloned().collect();
            if !fresh.is_empty() {
                info.owner_seen = owner_msgs.len() as u64;
                // the first message is the goal itself, already in the prompt
                let new: Vec<String> = if info.steps == 0 && fresh.len() == owner_msgs.len() { fresh[1..].to_vec() } else { fresh };
                if !new.is_empty() {
                    let text = new.join("\n");
                    j.progress(&format!("owner says: {}", short(&text, 200)));
                    owner_request = Some(match owner_request.take() { Some(old) => format!("{old}\n{text}"), None => text });
                    j.save_info(&info)?;
                }
            }
            if let Some(req) = &owner_request {
                let lead = format!("OWNER SAYS (act on it now: add_task for new work, tell_owner to answer, or finish if that is all): {req}");
                nudge = Some(match nudge.take() { Some(n) => format!("{lead}\n{n}"), None => lead });
            }
            let tasks = j.tasks();
            if !tasks.is_empty() && current_task(&tasks).is_none() && nudge.is_none() {
                let blocked = tasks.iter().filter(|t| t.state == TaskState::Blocked).count();
                info.status = Status::Done;
                j.progress(&format!("all tasks finished ({} passed, {blocked} blocked)", tasks.len() - blocked));
                self.wrap_up(j, &info, &tasks, None, vec![]);
                break;
            }

            self.compact(j, &mut recent).await;
            let msgs = self.context(j, &info, &tasks, &recent, nudge.as_deref());
            nudge = None;
            let schemas = tools::schemas();
            info.ctx_tokens = ((msgs.iter().map(|m| m.content.len()).sum::<usize>() + schemas.to_string().len()) / 4) as u64;
            let exclude: Vec<String> = if info.mode == "hard" {
                self.pool.lock().await.providers().iter().filter(|p| p.local).map(|p| p.name.clone()).collect()
            } else {
                vec![]
            };
            let reply = match self.llm.chat_pref(&self.pool, Role::Brain, &msgs, &schemas, info.prefer.as_deref(), &exclude).await {
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
                idle_turns += 1;
                j.log_step(&json!({"step": info.steps, "provider": reply.provider, "text": short(&reply.text, 3000)}));
                nudge = Some(if silent_turns >= 3 {
                    "You have answered 3 times without a tool call. Reply ONLY with JSON like {\"tool\":\"note\",\"args\":{\"text\":\"...\"}}.".into()
                } else {
                    "Reply with exactly one tool call.".into()
                });
                j.save_info(&info)?;
                continue;
            };
            silent_turns = 0;
            if matches!(call.name.as_str(), "add_task" | "tell_owner" | "ask_owner" | "finish" | "plan" | "block_task" | "interview") {
                owner_request = None; // the model has acted on what the owner said
            }

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
                    let mut pend = json!({"name": call.name, "args": call.args});
                    if call.name == "run" {
                        let a = crate::risk::assess(call.args["command"].as_str().unwrap_or(""), &info.workspace);
                        pend["summary"] = json!({"title": call.args["why"].as_str().unwrap_or(&a.what), "what": a.what,
                            "risk": a.risk, "reasons": a.reasons, "outside": a.outside});
                    }
                    info.pending = Some(pend);
                    info.waiting_for = Some(s.clone());
                    info.status = Status::Waiting;
                    (s, true)
                }
            };
            info.tok_in += reply.tokens_in;
            info.tok_out += reply.tokens_out;
            j.log_step(&json!({"step": info.steps, "provider": reply.provider, "model": reply.model,
                "tool": call.name, "args": call.args, "result": short(&result, 2000),
                "tin": reply.tokens_in, "tout": reply.tokens_out, "secs": (reply.secs * 10.0).round() / 10.0}));
            let productive = !result.starts_with("ERROR")
                && matches!(call.name.as_str(), "plan" | "write_file" | "run" | "mark_done" | "add_task" | "block_task" | "tell_owner" | "image_prompt" | "ask_owner" | "finish" | "interview" | "inspect_scene" | "look" | "learn");
            if call.name == "run" {
                if result.starts_with("ERROR") {
                    let line = result.lines().rev().find(|l| l.contains("Error") || l.contains("error")).unwrap_or("").trim().to_string();
                    if !line.is_empty() { fixed_error = Some(line); }
                } else if let Some(err) = fixed_error.take() {
                    if nudge.is_none() {
                        nudge = Some(format!("That fixed the earlier error ({}). Call `learn` with a one-line rule so no future job repeats it, then carry on.", short(&err, 200)));
                    }
                }
            }
            let repeat = recent.iter().rev().take(4).any(|e| e.call == call);
            idle_turns = if productive && !repeat { 0 } else { idle_turns + 1 };
            info.idle_turns = idle_turns;
            if !paused && j.tasks().is_empty() && info.steps >= 5 && call.name != "plan" {
                nudge = Some("You still have no checklist. Call `plan` now, or `finish` if the goal needs no work.".into());
            }
            if !paused && idle_turns == 10 {
                nudge = Some("10 turns without progress. Make a real change now (write a file, run a program, mark_done) or block_task the current task.".into());
            }
            let passed_now = call.name == "mark_done" && result.contains("passed");
            info.since_pass = if passed_now { 0 } else { info.since_pass + 1 };
            if !paused && info.since_pass == STALL_ASK * 2 / 3 {
                nudge = Some(format!("{} steps since a step last passed its check. The same approach keeps failing: change the \
                    approach (simpler shapes, a loki_bpy kit, fewer parts), or block_task this step with what you tried.", info.since_pass));
            }
            if !paused && info.since_pass >= STALL_ASK && idle_turns < 16 {
                let task = current_task(&j.tasks()).map(|t| format!(" \"{}\"", t.title)).unwrap_or_default();
                let last_fail = recent.iter().rev().find(|e| e.result.contains("check failed") || e.result.contains("score") || e.result.starts_with("ERROR"))
                    .map(|e| short(&e.result, 220)).unwrap_or_default();
                let q = format!("I've worked {} steps on{task} without passing its check. Latest: {last_fail}\nShould I keep trying a different way, accept it as it is, or stop?", info.since_pass);
                info.pending = Some(json!({"name": "ask_owner", "args": {"question": q, "options": ["Try a different way", "Accept it as it is", "Stop this job"]}}));
                info.waiting_for = Some(q.clone());
                info.status = Status::Waiting;
                j.save_info(&info)?;
                j.say("loki", &q, vec![]);
                j.progress(&format!("paused: {} steps without a passed check", info.since_pass));
                return Ok(info);
            }
            if !paused && idle_turns >= 16 {
                // Out of ideas: ask the owner instead of burning the free budget.
                let mut last: Vec<String> = recent.iter().rev().take(6).map(|e| e.call.name.replace('_', " ")).collect();
                last.dedup();
                let task = current_task(&j.tasks()).map(|t| format!(" on \"{}\"", t.title)).unwrap_or_default();
                let q = format!("I'm stuck{task}: 16 turns without real progress (mostly: {}). How should I continue?", last.join(", "));
                info.pending = Some(json!({"name": "ask_owner", "args": {"question": q}}));
                info.waiting_for = Some(q.clone());
                info.status = Status::Waiting;
                j.save_info(&info)?;
                j.say("loki", &q, vec![]);
                j.progress("paused: no progress for 16 turns");
                return Ok(info);
            }
            j.save_info(&info)?;
            if paused {
                j.progress(&format!("waiting for owner: {}", short(&result, 200)));
                return Ok(info);
            }
            if info.status == Status::Done {
                break; // `finish` was accepted
            }
            recent.push(Exchange { call, result });
        }
        j.save_info(&info)?;
        Ok(info)
    }

    /// Run LOKI's inspector on a .blend in this machine's Blender; the JSON report.
    pub async fn inspect(&self, ws: &std::path::Path, blend: &str) -> Result<Value, String> {
        let file = tools::confine(ws, blend)?;
        if !file.is_file() {
            return Err(format!("{blend} does not exist"));
        }
        let Some(blender) = &self.blender else { return Err("Blender is not installed on this machine (or LOKI_BLENDER is not set)".into()) };
        let dir = ws.join(".loki");
        let _ = std::fs::create_dir_all(&dir);
        let script = dir.join("inspect_scene.py");
        let out = dir.join("inspect.json");
        let _ = std::fs::remove_file(&out);
        std::fs::write(&script, INSPECT_SCRIPT).map_err(|e| e.to_string())?;
        let mut c = tokio::process::Command::new(blender);
        c.arg("--background").arg(&file).arg("--python-exit-code").arg("1").arg("--python").arg(&script).arg("--").arg(&out)
            .current_dir(ws).kill_on_drop(true).stdin(std::process::Stdio::null());
        #[cfg(windows)]
        {
            c.creation_flags(0x0800_0000);
        }
        let run = tokio::time::timeout(std::time::Duration::from_secs(240), c.output()).await;
        match run {
            Err(_) => return Err("the inspector timed out".into()),
            Ok(Err(e)) => return Err(format!("could not start Blender: {e}")),
            Ok(Ok(o)) if !o.status.success() => {
                let err = String::from_utf8_lossy(&o.stderr);
                return Err(format!("the inspector failed: {}", short(err.trim(), 600)));
            }
            _ => {}
        }
        let text = std::fs::read_to_string(&out).map_err(|_| "the inspector wrote no report".to_string())?;
        serde_json::from_str(&text).map_err(|e| e.to_string())
    }

    async fn check_blend(&self, ws: &std::path::Path, blend: &str) -> Result<String, String> {
        let r = self.inspect(ws, blend).await?;
        let errors: Vec<String> = r["problems"].as_array().map(|a| a.iter().filter(|p| p["level"] == "error").filter_map(|p| p["text"].as_str().map(String::from)).collect()).unwrap_or_default();
        if errors.is_empty() {
            Ok(describe_inspection(&r))
        } else {
            Err(format!("the inspector found errors in {blend}: {}", errors.join("; ")))
        }
    }

    /// A vision model scores an image against the brief: (score, its notes).
    pub async fn look(&self, ws: &std::path::Path, path: &str, brief: &str) -> Result<(f64, String), String> {
        let file = tools::confine(ws, path)?;
        if !file.is_file() {
            return Err(format!("{path} does not exist"));
        }
        // loki_bpy's finish() also writes <name>_views.png (front / right / back / above): judge all four angles,
        // so a lid floating at the back or a missing side can't hide behind one hero shot
        let sheet = file.with_file_name(format!("{}_views.png", file.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default()));
        let use_sheet = sheet.is_file() && !path.contains("_views");
        let bytes = std::fs::read(if use_sheet { &sheet } else { &file }).map_err(|_| format!("{path} could not be read"))?;
        let (img, mime) = shrink(&bytes).unwrap_or((bytes, if path.to_ascii_lowercase().ends_with(".png") { "image/png" } else { "image/jpeg" }));
        let what = if use_sheet { "a sheet of four views of one 3D render (top-left: front, top-right: right side, bottom-left: from behind, bottom-right: from above)" } else { "a 3D render" };
        let prompt = format!("You are a strict art director reviewing {what}.\nBRIEF: {brief}\n\
            Look at the image. List concrete visible problems (floating or disconnected parts, wrong proportions, anything the brief asks for that is missing or out of frame, \
            blocky placeholder shapes, bad lighting or exposure, clipping). Then score 1-10 how well it meets the brief (7 = good enough to show, 9 = portfolio).\n\
            Reply only JSON: {{\"score\": n, \"problems\": [\"...\"], \"good\": [\"...\"]}}");
        match self.llm.vision(&self.pool, &prompt, &img, mime).await {
            Ok(r) => {
                let v = crate::llm::extract_json(&r.text).unwrap_or(json!({}));
                let score = v["score"].as_f64().unwrap_or(0.0);
                let probs: Vec<String> = v["problems"].as_array().map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect()).unwrap_or_default();
                let good: Vec<String> = v["good"].as_array().map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect()).unwrap_or_default();
                let text = format!("problems: {}\ngood: {}\n(by {} {})", if probs.is_empty() { "none".into() } else { probs.join("; ") }, good.join("; "), r.provider, r.model);
                Ok((score, text))
            }
            Err(e) => Err(format!("no vision model answered: {e}")),
        }
    }

    async fn check_look(&self, ws: &std::path::Path, path: &str, brief: &str) -> Result<String, String> {
        match self.look(ws, path, brief).await {
            Ok((score, text)) if score >= self.look_pass => Ok(format!("vision score {score}/10. {text}")),
            Ok((score, text)) => Err(format!("vision score {score}/10 (needs {}). Fix these and render again: {text}", self.look_pass)),
            // Don't hold a job hostage to a busy free tier: pass, but say it was not seen.
            Err(e) if e.starts_with("no vision model") => Ok(format!("NOT visually checked ({e}); file exists")),
            Err(e) => Err(e),
        }
    }

    /// The closing chat message: the summary plus the images this job made.
    fn wrap_up(&self, j: &Journal, info: &RunInfo, tasks: &[Task], summary: Option<String>, mut files: Vec<String>) {
        if files.is_empty() {
            files = recent_images(&info.workspace, 8);
        }
        let blocked: Vec<String> = tasks.iter().filter(|t| t.state == TaskState::Blocked).map(|t| format!("#{} {} ({})", t.id, t.title, t.evidence)).collect();
        let mut text = summary.unwrap_or_else(|| format!("Done: {} of {} tasks passed.", tasks.len() - blocked.len(), tasks.len()));
        if !blocked.is_empty() {
            text.push_str(&format!("\nCould not finish: {}", blocked.join("; ")));
        }
        // the facts about what was made (cad_render writes renders/<name>_info.json)
        let mut facts = vec![];
        if let Ok(rd) = std::fs::read_dir(info.workspace.join("renders")) {
            for e in rd.flatten() {
                let n = e.file_name().to_string_lossy().to_string();
                let Some(stem) = n.strip_suffix("_info.json") else { continue };
                let Some(v) = std::fs::read_to_string(e.path()).ok().and_then(|t| serde_json::from_str::<Value>(&t).ok()) else { continue };
                let sz: Vec<String> = v["size_m"].as_array().map(|a| a.iter().map(|x| format!("{:.2}", x.as_f64().unwrap_or(0.0))).collect()).unwrap_or_default();
                facts.push(format!("**{stem}**: {} m · {} triangles · {} parts · {}{}", sz.join(" × "), v["triangles"].as_u64().unwrap_or(0),
                    v["parts"].as_object().map(|o| o.len()).unwrap_or(0),
                    if v["watertight"].as_bool().unwrap_or(false) { "watertight" } else { "has open edges" },
                    v["render_s"].as_f64().map(|t| format!(" · rendered in {t:.0}s")).unwrap_or_default()));
            }
        }
        if !facts.is_empty() {
            text.push_str(&format!("\n\n{}", facts.join("\n")));
        }
        j.say("loki", &text, files);
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
                if info.interview == "always" && !info.interviewed && !info.interview_asked && list.len() >= 2 {
                    info.interview_asked = true; // remind once; if the model plans again, the goal said enough
                    return Outcome::Err("Interview the owner first: call `interview` with 1-3 option questions about the choices this goal leaves open. If the goal already settles everything, send the same plan again.".into());
                }
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
                let folder_only: Vec<String> = tasks.iter().filter(|t| {
                    let c = t.check.trim().to_ascii_lowercase();
                    ["cmd:dir", "cmd:mkdir", "cmd:ls", "cmd:test -d", "cmd:if exist"].iter().any(|p| c.starts_with(p))
                }).map(|t| t.title.clone()).collect();
                if !folder_only.is_empty() {
                    return Outcome::Err(format!("these tasks only check folders: {}. Folders are made by write_file and your scripts; \
                        plan tasks whose check is the real output (file:<path>). Send the plan again.", folder_only.join("; ")));
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
                let check = t.check.clone();
                let title = t.title.clone();
                let verdict = if let Some(p) = check.strip_prefix("blend:") {
                    self.check_blend(&ws, p.trim()).await
                } else if let Some(p) = check.strip_prefix("look:") {
                    self.check_look(&ws, p.trim(), &format!("{}\nThis step: {title}", info.goal)).await
                } else {
                    tools::verify(&ws, &self.cfg.policy, &check).await
                };
                let Some(t) = tasks.iter_mut().find(|t| t.id == id) else { return Outcome::Err(format!("no task #{id}")) };
                match verdict {
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
                // Free models give up on fixable work: a step with a machine check needs 3 real attempts first.
                let machine = ["blend:", "look:", "file:", "cmd:"].iter().any(|p| t.check.starts_with(p));
                if machine && t.attempts < 3 {
                    t.attempts += 1;
                    let _ = j.save_tasks(&tasks);
                    return Outcome::Err(format!("not yet: you have tried #{id} only {} time(s). If you know the cause ({}), fix it now \
                        (write_file, run, then mark_done). Set it aside only after 3 real attempts, or ask_owner.",
                        tasks.iter().find(|t| t.id == id).map(|t| t.attempts - 1).unwrap_or(0), short(a["reason"].as_str().unwrap_or(""), 160)));
                }
                t.state = TaskState::Blocked;
                t.evidence = a["reason"].as_str().unwrap_or("").into();
                let _ = j.save_tasks(&tasks);
                j.progress(&format!("blocked #{id}: {}", a["reason"].as_str().unwrap_or("")));
                Outcome::Ok(format!("task #{id} blocked; moving on"))
            }
            "inspect_scene" => {
                let Some(p) = a["path"].as_str() else { return Outcome::Err("missing 'path'".into()) };
                match self.inspect(&ws, p).await {
                    Ok(r) => Outcome::Ok(describe_inspection(&r)),
                    Err(e) => Outcome::Err(e),
                }
            }
            "look" => {
                let Some(p) = a["path"].as_str() else { return Outcome::Err("missing 'path'".into()) };
                let brief = a["brief"].as_str().map(String::from).unwrap_or_else(|| info.goal.clone());
                match self.look(&ws, p, &brief).await {
                    Ok((score, text)) => Outcome::Ok(format!("score {score}/10\n{text}")),
                    Err(e) => Outcome::Err(e),
                }
            }
            "learn" => {
                let l = a["lesson"].as_str().unwrap_or("");
                if self.knowledge.learn(l) {
                    j.progress(&format!("learned: {}", short(l, 160)));
                    Outcome::Ok("saved to the lessons notebook".into())
                } else {
                    Outcome::Ok("already known (or too short)".into())
                }
            }
            "tell_owner" => {
                let text = a["text"].as_str().unwrap_or("").trim();
                if text.is_empty() {
                    return Outcome::Err("tell_owner needs 'text'".into());
                }
                let files = existing_files(&ws, &a["files"]);
                j.say("loki", text, files);
                Outcome::Ok("sent to the owner".into())
            }
            "interview" => {
                let qs = a["questions"].as_array().cloned().unwrap_or_default();
                if qs.is_empty() {
                    return Outcome::Err("interview needs 1-3 questions".into());
                }
                if info.interviewed {
                    return Outcome::Err("the owner was already interviewed; use their choices and plan".into());
                }
                let n = qs.len().min(3);
                Outcome::NeedsOwner(format!("{} question{} before starting", n, if n == 1 { "" } else { "s" }))
            }
            "image_prompt" => {
                let prompt = a["prompt"].as_str().unwrap_or("").trim();
                if prompt.is_empty() {
                    return Outcome::Err("image_prompt needs 'prompt'".into());
                }
                if approved {
                    // the owner's edited prompt (the approval note) wins over the proposed one
                    return Outcome::Ok(format!("APPROVED PROMPT (use exactly): {prompt}"));
                }
                Outcome::NeedsOwner(format!("Image prompt for {}: {prompt}", a["purpose"].as_str().unwrap_or("an image")))
            }
            "finish" => {
                let tasks = j.tasks();
                if let Some(t) = current_task(&tasks) {
                    return Outcome::Err(format!("task #{} '{}' is still todo: do it, block_task it, or ask the owner", t.id, t.title));
                }
                let summary = a["summary"].as_str().unwrap_or("Done.").to_string();
                let files = existing_files(&ws, &a["files"]);
                self.wrap_up(j, info, &tasks, Some(summary), files);
                info.status = Status::Done;
                Outcome::Ok("finished".into())
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
            "run" => {
                let again = a["command"].as_str().is_some_and(|c| info.approved_commands.iter().any(|x| x == c));
                tools::run(&ws, &self.cfg.policy, a, approved || again).await
            }
            other => Outcome::Err(format!("unknown tool '{other}'. Available: plan, list_dir, read_file, write_file, run, mark_done, block_task, add_task, note, ask_owner, tell_owner, image_prompt, interview, inspect_scene, look, learn, finish")),
        }
    }
}

/// A short text version of an inspector report for the model and the chat.
pub fn describe_inspection(r: &Value) -> String {
    let c = &r["counts"];
    let mut s = format!("{} meshes, {} triangles, {} lights, {} camera(s), engine {}.",
        c["meshes"], c["triangles"], c["lights"], c["cameras"], r["engine"].as_str().unwrap_or("?"));
    let probs: Vec<String> = r["problems"].as_array().map(|a| a.iter().map(|p| format!("[{}] {}", p["level"].as_str().unwrap_or(""), p["text"].as_str().unwrap_or(""))).collect()).unwrap_or_default();
    if probs.is_empty() {
        s.push_str(" No problems found.");
    } else {
        s.push_str(&format!(" Problems: {}", probs.join("; ")));
    }
    s
}

/// Make an image small enough for a vision API: at most 768 px, JPEG.
fn shrink(bytes: &[u8]) -> Option<(Vec<u8>, &'static str)> {
    let img = image::load_from_memory(bytes).ok()?;
    let img = if img.width().max(img.height()) > 1024 { img.resize(1024, 1024, image::imageops::FilterType::Triangle) } else { img };
    let mut out = std::io::Cursor::new(Vec::new());
    img.to_rgb8().write_to(&mut out, image::ImageFormat::Jpeg).ok()?;
    Some((out.into_inner(), "image/jpeg"))
}

/// Workspace-relative files from a tool's `files` argument that really exist.
fn existing_files(ws: &std::path::Path, v: &Value) -> Vec<String> {
    v.as_array()
        .map(|a| a.iter().filter_map(|x| x.as_str()).filter(|p| tools::confine(ws, p).map(|f| f.is_file()).unwrap_or(false)).map(|p| p.trim_start_matches("./").replace('\\', "/")).collect())
        .unwrap_or_default()
}

/// Newest images under the workspace (for the closing message).
fn recent_images(ws: &std::path::Path, n: usize) -> Vec<String> {
    let mut found: Vec<(std::time::SystemTime, String)> = Vec::new();
    let mut stack = vec![ws.to_path_buf()];
    while let Some(d) = stack.pop() {
        for e in std::fs::read_dir(&d).into_iter().flatten().flatten() {
            let p = e.path();
            if p.is_dir() {
                stack.push(p);
            } else if p.extension().and_then(|x| x.to_str()).is_some_and(|x| matches!(x.to_ascii_lowercase().as_str(), "png" | "jpg" | "jpeg" | "webp")) {
                if let (Ok(m), Ok(rel)) = (e.metadata().and_then(|m| m.modified()), p.strip_prefix(ws)) {
                    found.push((m, rel.to_string_lossy().replace('\\', "/")));
                }
            }
        }
    }
    found.sort_by(|a, b| b.0.cmp(&a.0));
    found.into_iter().take(n).map(|x| x.1).collect()
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
