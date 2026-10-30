//! The run journal: everything a run needs to survive a crash, a restart or a
//! context reset, kept as plain files the owner can read.
//!
//! runs/<id>/
//!   run.json        status, goal, workspace, step counters
//!   tasks.json      the checklist; a task only flips to passed with evidence
//!   progress.md     one line per finished step, newest last (human log)
//!   steps.jsonl     full machine log of every model turn and tool result
//!   summary.md      rolling compacted memory of older steps

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::io::Write;
use std::path::{Path, PathBuf};

pub fn atomic_write(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir)?;
    }
    let tmp = path.with_extension("tmp");
    {
        let mut f = std::fs::File::create(&tmp)?;
        f.write_all(bytes)?;
        f.sync_all()?;
    }
    std::fs::rename(&tmp, path)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    Planning,
    Running,
    /// Waiting for the owner (an approval or an answer).
    Waiting,
    /// Every free provider is resting; resumes by itself.
    Resting,
    Done,
    Stopped,
    Failed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunInfo {
    pub id: String,
    pub goal: String,
    pub workspace: PathBuf,
    pub status: Status,
    pub created: DateTime<Utc>,
    pub updated: DateTime<Utc>,
    pub steps: u64,
    pub max_steps: u64,
    /// Wall-clock budget in hours (the owner can let a run go all night).
    pub max_hours: f64,
    #[serde(default)]
    pub waiting_for: Option<String>,
    #[serde(default)]
    pub last_error: Option<String>,
    /// Tool call waiting for the owner's yes/no.
    #[serde(default)]
    pub pending: Option<serde_json::Value>,
    /// The owner's answer or approval, consumed on resume.
    #[serde(default)]
    pub owner_reply: Option<OwnerReply>,
    /// "agent" (default) or "hard" (strongest model first).
    #[serde(default)]
    pub mode: String,
    /// Provider the owner picked for this job (tried first).
    #[serde(default)]
    pub prefer: Option<String>,
    /// Owner chat messages the driver has already read.
    #[serde(default)]
    pub owner_seen: u64,
    /// Rough size of the last prompt, in tokens (for the context meter).
    #[serde(default)]
    pub ctx_tokens: u64,
    /// Short title for the job list.
    #[serde(default)]
    pub title: String,
    /// Commands the owner approved in this job; the same command runs without asking again.
    #[serde(default)]
    pub approved_commands: Vec<String>,
    /// Turns in a row without progress, kept across pauses and approvals.
    #[serde(default)]
    pub idle_turns: u32,
    /// Steps since a checklist step last passed its check: busy-but-going-nowhere (write, run, fail the
    /// check, write again ...) counts here even though every single turn "did something".
    #[serde(default)]
    pub since_pass: u32,
    /// "always" | "big" | "off": ask the owner a few option questions before planning.
    #[serde(default)]
    pub interview: String,
    /// The interview happened (or was skipped on purpose).
    #[serde(default)]
    pub interviewed: bool,
    /// The driver already reminded the model to interview once.
    #[serde(default)]
    pub interview_asked: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatLine {
    pub t: DateTime<Utc>,
    /// "owner" or "loki"
    pub from: String,
    pub text: String,
    /// Files the message shows (workspace-relative), e.g. a render.
    #[serde(default)]
    pub files: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OwnerReply {
    pub approve: bool,
    #[serde(default)]
    pub note: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskState {
    Todo,
    Passed,
    Blocked,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Task {
    pub id: u32,
    pub title: String,
    /// How to prove it is done (a file that must exist, a command that must pass).
    pub check: String,
    pub state: TaskState,
    #[serde(default)]
    pub evidence: String,
    #[serde(default)]
    pub attempts: u32,
}

/// First line of the goal, cut to a short title.
pub fn title_of(goal: &str) -> String {
    let first = goal.lines().find(|l| !l.trim().is_empty()).unwrap_or("").trim();
    let mut t: String = first.chars().take(60).collect();
    if first.chars().count() > 60 {
        if let Some(i) = t.rfind(' ') { t.truncate(i); }
        t.push('…');
    }
    t
}

pub struct Journal {
    pub dir: PathBuf,
}

impl Journal {
    pub fn create(root: &Path, goal: &str, workspace: &Path, max_steps: u64, max_hours: f64) -> anyhow::Result<(Self, RunInfo)> {
        let id = format!("{}-{}", Utc::now().format("%Y%m%d-%H%M%S"), &uuid::Uuid::new_v4().to_string()[..6]);
        let dir = root.join(&id);
        std::fs::create_dir_all(&dir)?;
        std::fs::create_dir_all(workspace)?;
        let now = Utc::now();
        let info = RunInfo {
            id,
            goal: goal.to_string(),
            workspace: workspace.to_path_buf(),
            status: Status::Planning,
            created: now,
            updated: now,
            steps: 0,
            max_steps,
            max_hours,
            waiting_for: None,
            last_error: None,
            pending: None,
            owner_reply: None,
            mode: "agent".into(),
            prefer: None,
            owner_seen: 0,
            ctx_tokens: 0,
            title: title_of(goal),
            approved_commands: vec![],
            idle_turns: 0,
            since_pass: 0,
            interview: "off".into(),
            interviewed: false,
            interview_asked: false,
        };
        let j = Self { dir };
        j.save_info(&info)?;
        j.save_tasks(&[])?;
        j.say("owner", goal, vec![]);
        Ok((j, info))
    }

    pub fn open(dir: &Path) -> Self {
        Self { dir: dir.to_path_buf() }
    }

    pub fn info(&self) -> anyhow::Result<RunInfo> {
        Ok(serde_json::from_str(&std::fs::read_to_string(self.dir.join("run.json"))?)?)
    }

    pub fn save_info(&self, info: &RunInfo) -> anyhow::Result<()> {
        let mut i = info.clone();
        i.updated = Utc::now();
        atomic_write(&self.dir.join("run.json"), serde_json::to_string_pretty(&i)?.as_bytes())?;
        Ok(())
    }

    pub fn tasks(&self) -> Vec<Task> {
        std::fs::read_to_string(self.dir.join("tasks.json"))
            .ok()
            .and_then(|s| serde_json::from_str(&s).ok())
            .unwrap_or_default()
    }

    pub fn save_tasks(&self, tasks: &[Task]) -> anyhow::Result<()> {
        atomic_write(&self.dir.join("tasks.json"), serde_json::to_string_pretty(tasks)?.as_bytes())?;
        Ok(())
    }

    pub fn progress(&self, line: &str) {
        let path = self.dir.join("progress.md");
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
            let _ = writeln!(f, "- {} {}", Utc::now().format("%H:%M:%S"), line.replace('\n', " "));
        }
    }

    pub fn progress_tail(&self, n: usize) -> String {
        let s = std::fs::read_to_string(self.dir.join("progress.md")).unwrap_or_default();
        let lines: Vec<&str> = s.lines().collect();
        lines[lines.len().saturating_sub(n)..].join("\n")
    }

    pub fn log_step(&self, v: &serde_json::Value) {
        let mut v = v.clone();
        if v.get("t").is_none() {
            v["t"] = serde_json::json!(Utc::now());
        }
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(self.dir.join("steps.jsonl")) {
            let _ = writeln!(f, "{v}");
        }
    }

    pub fn steps(&self) -> Vec<serde_json::Value> {
        std::fs::read_to_string(self.dir.join("steps.jsonl"))
            .unwrap_or_default()
            .lines()
            .filter_map(|l| serde_json::from_str(l).ok())
            .collect()
    }

    pub fn say(&self, from: &str, text: &str, files: Vec<String>) {
        let line = ChatLine { t: Utc::now(), from: from.into(), text: text.into(), files };
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(self.dir.join("chat.jsonl")) {
            if let Ok(s) = serde_json::to_string(&line) {
                let _ = writeln!(f, "{s}");
            }
        }
    }

    pub fn chat(&self) -> Vec<ChatLine> {
        std::fs::read_to_string(self.dir.join("chat.jsonl"))
            .unwrap_or_default()
            .lines()
            .filter_map(|l| serde_json::from_str(l).ok())
            .collect()
    }

    pub fn summary(&self) -> String {
        std::fs::read_to_string(self.dir.join("summary.md")).unwrap_or_default()
    }

    pub fn save_summary(&self, s: &str) {
        let _ = atomic_write(&self.dir.join("summary.md"), s.as_bytes());
    }

    /// All runs under `root`, newest first.
    pub fn list(root: &Path) -> Vec<RunInfo> {
        let mut out: Vec<RunInfo> = std::fs::read_dir(root)
            .into_iter()
            .flatten()
            .flatten()
            .filter_map(|e| Journal::open(&e.path()).info().ok())
            .collect();
        out.sort_by(|a, b| b.created.cmp(&a.created));
        out
    }
}
