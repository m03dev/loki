//! Live sessions: one interpreter per job and kind (plain Python, Python inside Blender, ...) that stays open, so the
//! model works step by step - send a few lines, look, adjust - instead of re-running one big script for every change.
//! The server side is tools/session/session_server.py (written into every job's scripts/).

use serde_json::Value;
use std::collections::HashMap;
use std::path::Path;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader, Lines};
use tokio::process::{Child, ChildStdin, ChildStdout};
use tokio::sync::Mutex;

pub const SERVER: &str = include_str!("../../../tools/session/session_server.py");
const DONE: &str = "\u{1e}LOKI_DONE ";

struct Live {
    _child: Child,
    stdin: ChildStdin,
    out: Lines<BufReader<ChildStdout>>,
}

#[derive(Clone, Default)]
pub struct Sessions {
    live: Arc<Mutex<HashMap<String, Arc<Mutex<Live>>>>>,
}

/// The program line that starts a session of `kind` (None: not available on this machine).
fn program(kind: &str, blender: Option<&str>) -> Option<(String, Vec<String>)> {
    let server = "scripts/session_server.py".to_string();
    match kind {
        "blender" => blender.map(|b| (b.to_string(), vec!["--background".into(), "--factory-startup".into(), "--python".into(), server])),
        "python" => {
            let py = std::env::var("LOKI_PYTHON").ok().filter(|p| Path::new(p).is_file())
                .unwrap_or_else(|| if cfg!(windows) { "python".into() } else { "python3".into() });
            Some((py, vec!["-u".into(), server]))
        }
        _ => None,
    }
}

impl Sessions {
    /// Run `code` in the job's `kind` session (started on first use). Returns (ok, output).
    pub async fn run(&self, job: &str, ws: &Path, kind: &str, code: &str, blender: Option<&str>, timeout: Duration) -> Result<(bool, String), String> {
        let key = format!("{job}|{kind}");
        let live = { self.live.lock().await.get(&key).cloned() };
        let live = match live {
            Some(l) => l,
            None => {
                let (prog, args) = program(kind, blender).ok_or_else(|| format!("no '{kind}' session on this machine (kinds: python, blender)"))?;
                let scripts = ws.join("scripts");
                let _ = std::fs::create_dir_all(&scripts);
                let _ = std::fs::write(scripts.join("session_server.py"), SERVER);
                let mut cmd = tokio::process::Command::new(&prog);
                cmd.args(&args).current_dir(ws).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null()).kill_on_drop(true);
                #[cfg(windows)]
                {
                    cmd.creation_flags(0x0800_0000);
                }
                let mut child = cmd.spawn().map_err(|e| format!("cannot start the {kind} session ({prog}): {e}"))?;
                if let Some(pid) = child.id() { remember_pid(pid); }
                let stdin = child.stdin.take().ok_or("no stdin")?;
                let out = BufReader::new(child.stdout.take().ok_or("no stdout")?).lines();
                let l = Arc::new(Mutex::new(Live { _child: child, stdin, out }));
                // wait for "session ready"
                let ready = tokio::time::timeout(Duration::from_secs(120), read_done(&mut l.lock().await.out)).await;
                match ready {
                    Ok(Ok(_)) => {}
                    Ok(Err(e)) => return Err(format!("the {kind} session did not start: {e}")),
                    Err(_) => return Err(format!("the {kind} session did not start within 120 s")),
                }
                self.live.lock().await.insert(key.clone(), l.clone());
                l
            }
        };
        let mut g = live.lock().await;
        let line = serde_json::json!({"code": code}).to_string() + "\n";
        if g.stdin.write_all(line.as_bytes()).await.is_err() || g.stdin.flush().await.is_err() {
            drop(g);
            self.live.lock().await.remove(&key);
            return Err(format!("the {kind} session had stopped; run again to start a fresh one (variables are gone)"));
        }
        match tokio::time::timeout(timeout, read_done(&mut g.out)).await {
            Ok(Ok(v)) => Ok((v["ok"].as_bool().unwrap_or(false), v["out"].as_str().unwrap_or("").to_string())),
            Ok(Err(e)) => {
                drop(g);
                self.live.lock().await.remove(&key);
                Err(format!("the {kind} session ended: {e}"))
            }
            Err(_) => {
                drop(g);
                self.live.lock().await.remove(&key); // dropped -> killed
                Err(format!("no answer within {} s: the session was stopped (variables are gone)", timeout.as_secs()))
            }
        }
    }

    /// Close every session of a job (finished, failed or stopped).
    pub async fn close(&self, job: &str) {
        self.live.lock().await.retain(|k, _| !k.starts_with(&format!("{job}|")));
    }
}

/// Session processes this driver started, so a restarted driver (an update, a crash) can stop the ones it left behind
/// - on Windows a child outlives its parent, and every leftover Blender holds memory.
fn pid_file() -> Option<std::path::PathBuf> {
    std::env::var("LOKI_HOME").ok().map(|h| std::path::Path::new(&h).join("session_pids.txt"))
}

fn remember_pid(pid: u32) {
    if let Some(f) = pid_file() {
        use std::io::Write;
        if let Ok(mut h) = std::fs::OpenOptions::new().create(true).append(true).open(f) {
            let _ = writeln!(h, "{pid}");
        }
    }
}

/// Call once when the driver starts: stop session processes a previous driver left running.
pub fn reap_leftovers() {
    let Some(f) = pid_file() else { return };
    let Ok(text) = std::fs::read_to_string(&f) else { return };
    for pid in text.lines().filter_map(|l| l.trim().parse::<u32>().ok()) {
        // only if that pid is still a Blender or Python (pids get reused after a reboot)
        #[cfg(windows)]
        for image in ["blender.exe", "python.exe", "python3.exe"] {
            let _ = std::process::Command::new("taskkill").args(["/PID", &pid.to_string(), "/FI", &format!("IMAGENAME eq {image}"), "/T", "/F"])
                .stdout(Stdio::null()).stderr(Stdio::null()).status();
        }
        #[cfg(unix)]
        {
            let comm = std::process::Command::new("ps").args(["-p", &pid.to_string(), "-o", "comm="]).output()
                .map(|o| String::from_utf8_lossy(&o.stdout).to_ascii_lowercase()).unwrap_or_default();
            if comm.contains("blender") || comm.contains("python") {
                let _ = std::process::Command::new("kill").args(["-9", &pid.to_string()]).stdout(Stdio::null()).stderr(Stdio::null()).status();
            }
        }
    }
    let _ = std::fs::remove_file(f);
}

async fn read_done(out: &mut Lines<BufReader<ChildStdout>>) -> Result<Value, String> {
    loop {
        match out.next_line().await {
            Ok(Some(l)) => {
                if let Some(rest) = l.find(DONE).map(|i| &l[i + DONE.len()..]) {
                    return serde_json::from_str(rest).map_err(|e| e.to_string());
                }
            }
            Ok(None) => return Err("it exited".into()),
            Err(e) => return Err(e.to_string()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn a_python_session_keeps_its_variables_and_reports_errors() {
        let ws = std::env::temp_dir().join(format!("loki-session-{}", std::process::id()));
        std::fs::create_dir_all(&ws).unwrap();
        let s = Sessions::default();
        let t = Duration::from_secs(60);
        assert!(s.run("j", &ws, "python", "x = 20", None, t).await.unwrap().0);
        assert_eq!(s.run("j", &ws, "python", "x + 22", None, t).await.unwrap(), (true, "42\n".to_string()));
        let (ok, out) = s.run("j", &ws, "python", "1/0", None, t).await.unwrap();
        assert!(!ok && out.contains("ZeroDivisionError"));
        assert!(s.run("j", &ws, "python", "print(x)", None, t).await.unwrap().1.contains("20"), "still alive after an error");
        s.close("j").await;
        let _ = std::fs::remove_dir_all(&ws);
    }
}
