//! The driver's toolbox. Small on purpose: a handful of sharp tools the model
//! can't misuse, each confined to the run's workspace. App-specific tools
//! (Blender, ComfyUI, 3D generators) plug in through MCP on top of these.

use serde_json::{json, Value};
use std::path::{Component, Path, PathBuf};
use std::time::Duration;

pub enum Outcome {
    /// Normal result text shown back to the model.
    Ok(String),
    /// The tool failed; the model sees the error and can try again.
    Err(String),
    /// Needs the owner: the run pauses with this explanation.
    NeedsOwner(String),
}

#[derive(Debug, Clone)]
pub struct Policy {
    /// Commands whose first word is here run without asking.
    pub auto_commands: Vec<String>,
    pub command_timeout: Duration,
}

impl Default for Policy {
    fn default() -> Self {
        let auto = [
            "ls", "cat", "head", "tail", "wc", "echo", "mkdir", "touch", "cp", "mv", "find", "grep",
            "git", "python", "python3", "node", "cargo", "blender", "ffmpeg", "magick", "convert",
        ];
        Self {
            auto_commands: auto.iter().map(|s| s.to_string()).collect(),
            command_timeout: Duration::from_secs(600),
        }
    }
}

/// JSON schemas sent to the model.
pub fn schemas() -> Value {
    fn f(name: &str, desc: &str, props: Value, req: &[&str]) -> Value {
        json!({"type":"function","function":{"name":name,"description":desc,
            "parameters":{"type":"object","properties":props,"required":req}}})
    }
    json!([
        f("plan", "Write the task checklist for the goal. Each task needs a concrete check: 'file:<path>' (must exist, non-empty) or 'cmd:<command>' (must exit 0) or a short description.",
          json!({"tasks":{"type":"array","items":{"type":"object","properties":{"title":{"type":"string"},"check":{"type":"string"}},"required":["title","check"]}}}), &["tasks"]),
        f("list_dir", "List files in a workspace folder.", json!({"path":{"type":"string"}}), &[]),
        f("read_file", "Read a text file from the workspace.", json!({"path":{"type":"string"}}), &["path"]),
        f("write_file", "Create or overwrite a text file in the workspace.", json!({"path":{"type":"string"},"content":{"type":"string"}}), &["path","content"]),
        f("run", "Run a shell command in the workspace. Common tools run directly; anything else asks the owner first, so say what it does in 'why'.",
          json!({"command":{"type":"string"},"why":{"type":"string"}}), &["command","why"]),
        f("mark_done", "Mark a task passed. The driver re-runs the task's check; it only passes if the check holds.",
          json!({"task_id":{"type":"integer"},"evidence":{"type":"string"}}), &["task_id","evidence"]),
        f("block_task", "Give up on a task for now with the reason; the run moves on.", json!({"task_id":{"type":"integer"},"reason":{"type":"string"}}), &["task_id","reason"]),
        f("add_task", "Add a task you discovered is needed.", json!({"title":{"type":"string"},"check":{"type":"string"}}), &["title","check"]),
        f("note", "Write one line to the progress log (what you learned or decided).", json!({"text":{"type":"string"}}), &["text"]),
        f("ask_owner", "Pause and ask the owner a question with 2-4 options.", json!({"question":{"type":"string"},"options":{"type":"array","items":{"type":"string"}}}), &["question"])
    ])
}

/// Resolve a model-supplied path inside the workspace; refuse escapes.
pub fn confine(workspace: &Path, p: &str) -> Result<PathBuf, String> {
    let rel = Path::new(p.trim_start_matches('/'));
    let mut out = workspace.to_path_buf();
    for c in rel.components() {
        match c {
            Component::Normal(s) => out.push(s),
            Component::CurDir => {}
            _ => return Err(format!("path '{p}' leaves the workspace")),
        }
    }
    Ok(out)
}

pub fn list_dir(ws: &Path, args: &Value) -> Outcome {
    let p = args["path"].as_str().unwrap_or(".");
    let dir = match confine(ws, p) { Ok(d) => d, Err(e) => return Outcome::Err(e) };
    match std::fs::read_dir(&dir) {
        Ok(rd) => {
            let mut names: Vec<String> = rd
                .flatten()
                .map(|e| {
                    let n = e.file_name().to_string_lossy().to_string();
                    if e.path().is_dir() { format!("{n}/") } else { n }
                })
                .collect();
            names.sort();
            Outcome::Ok(if names.is_empty() { "(empty)".into() } else { names.join("\n") })
        }
        Err(e) => Outcome::Err(format!("cannot list {p}: {e}")),
    }
}

pub fn read_file(ws: &Path, args: &Value) -> Outcome {
    let Some(p) = args["path"].as_str() else { return Outcome::Err("missing 'path'".into()) };
    let f = match confine(ws, p) { Ok(f) => f, Err(e) => return Outcome::Err(e) };
    match std::fs::read_to_string(&f) {
        Ok(s) if s.len() > 20_000 => Outcome::Ok(format!("{}\n...[truncated, {} bytes total]", &s[..floor_char(&s, 20_000)], s.len())),
        Ok(s) => Outcome::Ok(s),
        Err(e) => Outcome::Err(format!("cannot read {p}: {e}")),
    }
}

fn floor_char(s: &str, mut i: usize) -> usize {
    while i > 0 && !s.is_char_boundary(i) { i -= 1; }
    i
}

pub fn write_file(ws: &Path, args: &Value) -> Outcome {
    let (Some(p), Some(c)) = (args["path"].as_str(), args["content"].as_str()) else {
        return Outcome::Err("need 'path' and 'content'".into());
    };
    let f = match confine(ws, p) { Ok(f) => f, Err(e) => return Outcome::Err(e) };
    if let Some(d) = f.parent() { let _ = std::fs::create_dir_all(d); }
    match std::fs::write(&f, c) {
        Ok(_) => Outcome::Ok(format!("wrote {p} ({} bytes)", c.len())),
        Err(e) => Outcome::Err(format!("cannot write {p}: {e}")),
    }
}

pub fn command_allowed(policy: &Policy, command: &str) -> bool {
    // Chaining could smuggle an unlisted program past the first-word check.
    if ["&&", "||", ";", "|", "`", "$(", ">", "<"].iter().any(|t| command.contains(t)) {
        return false;
    }
    let first = command.split_whitespace().next().unwrap_or("");
    let prog = Path::new(first).file_name().and_then(|s| s.to_str()).unwrap_or(first);
    policy.auto_commands.iter().any(|a| a == prog)
}

pub async fn run(ws: &Path, policy: &Policy, args: &Value, approved: bool) -> Outcome {
    let Some(cmd) = args["command"].as_str() else { return Outcome::Err("missing 'command'".into()) };
    if !approved && !command_allowed(policy, cmd) {
        let why = args["why"].as_str().unwrap_or("(no reason given)");
        return Outcome::NeedsOwner(format!("Wants to run `{cmd}` in {}: {why}", ws.display()));
    }
    shell(ws, &harden(cmd), policy.command_timeout).await
}

/// Make known tools report failure honestly. Blender exits 0 even when its Python script
/// crashes, so a broken render looked like success; `--python-exit-code 1` fixes that.
pub fn harden(cmd: &str) -> String {
    let first = cmd.split_whitespace().next().unwrap_or("");
    let prog = Path::new(first).file_stem().and_then(|s| s.to_str()).unwrap_or("").to_ascii_lowercase();
    if prog == "blender" && cmd.contains("--python") && !cmd.contains("--python-exit-code") {
        return cmd.replacen("--python", "--python-exit-code 1 --python", 1);
    }
    cmd.to_string()
}

pub async fn shell(ws: &Path, cmd: &str, timeout: Duration) -> Outcome {
    let mut c = if cfg!(windows) {
        let mut c = tokio::process::Command::new("cmd");
        c.arg("/C").arg(cmd);
        c
    } else {
        let mut c = tokio::process::Command::new("sh");
        c.arg("-c").arg(cmd);
        c
    };
    c.current_dir(ws).kill_on_drop(true);
    match tokio::time::timeout(timeout, c.output()).await {
        Err(_) => Outcome::Err(format!("`{cmd}` timed out after {}s", timeout.as_secs())),
        Ok(Err(e)) => Outcome::Err(format!("cannot start `{cmd}`: {e}")),
        Ok(Ok(o)) => {
            let mut text = String::from_utf8_lossy(&o.stdout).to_string();
            let err = String::from_utf8_lossy(&o.stderr);
            if !err.trim().is_empty() { text.push_str("\n[stderr]\n"); text.push_str(&err); }
            if text.len() > 8000 { let cut = text.len() - 8000; text = format!("...{}", &text[floor_char(&text, cut)..]); }
            if o.status.success() { Outcome::Ok(format!("exit 0\n{text}")) } else { Outcome::Err(format!("exit {:?}\n{text}", o.status.code())) }
        }
    }
}

/// Re-check a task's `check` independently of what the model claims.
pub async fn verify(ws: &Path, policy: &Policy, check: &str) -> Result<String, String> {
    if let Some(p) = check.strip_prefix("file:") {
        let f = confine(ws, p.trim())?;
        return match std::fs::metadata(&f) {
            Ok(m) if m.len() > 0 => Ok(format!("{} exists ({} bytes)", p.trim(), m.len())),
            Ok(_) => Err(format!("{} is empty", p.trim())),
            Err(_) => Err(format!("{} does not exist", p.trim())),
        };
    }
    if let Some(c) = check.strip_prefix("cmd:") {
        let c = c.trim();
        if !command_allowed(policy, c) {
            return Err(format!("check command `{c}` is not on the auto list; use a file: check or ask the owner"));
        }
        return match shell(ws, c, policy.command_timeout).await {
            Outcome::Ok(t) => Ok(t),
            Outcome::Err(t) | Outcome::NeedsOwner(t) => Err(t),
        };
    }
    Ok("self-reported (no machine check)".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn confine_blocks_escapes() {
        let ws = Path::new("/w");
        assert!(confine(ws, "../etc/passwd").is_err());
        assert_eq!(confine(ws, "/a/b.txt").unwrap(), PathBuf::from("/w/a/b.txt"));
        assert_eq!(confine(ws, "./a").unwrap(), PathBuf::from("/w/a"));
    }

    #[test]
    fn blender_script_errors_fail_the_command() {
        assert_eq!(harden("blender --background --python s.py"), "blender --background --python-exit-code 1 --python s.py");
        assert_eq!(harden("blender -b --python-exit-code 1 --python s.py"), "blender -b --python-exit-code 1 --python s.py");
        assert_eq!(harden("git status"), "git status");
    }

    #[test]
    fn policy_blocks_chaining_and_unknown_programs() {
        let p = Policy::default();
        assert!(command_allowed(&p, "git status"));
        assert!(!command_allowed(&p, "git status && rm -rf /"));
        assert!(!command_allowed(&p, "rm -rf build"));
        assert!(!command_allowed(&p, "curl http://x"));
    }
}
