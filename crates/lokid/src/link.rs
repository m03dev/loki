//! The Mac <-> PC link: the machines find each other across different networks and help each other.
//!
//! - Each machine serves a signed peer API on 127.0.0.1:<LOKI_LINK_PORT, 7718> and exposes it with a Cloudflare quick
//!   tunnel (free, no account): `cloudflared tunnel --url http://127.0.0.1:7718` hands back an https address.
//! - The address is posted to a private ntfy.sh topic derived from LOKI_PEER_SECRET (same format as the previous
//!   LOKI's tunnel_link.py), signed with the secret; the other machine reads the newest correctly signed post.
//! - Every peer request is signed: HMAC-SHA256(secret, "METHOD|path?query|unix-time|sha256(body)"), within 5 minutes.
//!   Nothing reaches the peer API without the secret; the local window API (7717) is never exposed.

use hmac::{Hmac, Mac};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::sync::Mutex;

type HmacSha256 = Hmac<Sha256>;

pub const H_NAME: &str = "x-loki-peer";
pub const H_TIME: &str = "x-loki-time";
pub const H_SIG: &str = "x-loki-sig";
const REPOST: Duration = Duration::from_secs(20 * 60);

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct PeerInfo {
    pub name: String,
    pub url: String,
    pub posted: u64,
    pub online: bool,
    #[serde(default)]
    pub hello: Value,
    pub checked: u64,
}

#[derive(Default)]
pub struct LinkState {
    pub my_url: String,
    pub error: String,
    pub peers: HashMap<String, PeerInfo>,
}

#[derive(Clone)]
pub struct Link {
    pub name: String,
    secret: String,
    pub home: PathBuf,
    pub state: Arc<Mutex<LinkState>>,
    http: reqwest::Client,
}

pub fn now() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

fn hmac_hex(secret: &str, msg: &str) -> String {
    let mut m = HmacSha256::new_from_slice(secret.as_bytes()).expect("hmac key");
    m.update(msg.as_bytes());
    hex::encode(m.finalize().into_bytes())
}

pub fn body_hash(body: &[u8]) -> String {
    hex::encode(Sha256::digest(body))
}

impl Link {
    /// None when this machine has no LOKI_PEER_SECRET (the link is off).
    pub fn from_env(home: &Path) -> Option<Self> {
        let secret = std::env::var("LOKI_PEER_SECRET").ok().map(|s| s.trim().to_string()).filter(|s| s.len() >= 16)?;
        let name = std::env::var("LOKI_PEER_NAME").ok().map(|s| s.trim().to_string()).filter(|s| !s.is_empty())
            .or_else(|| std::env::var("COMPUTERNAME").ok())
            .or_else(|| std::env::var("HOSTNAME").ok())
            .unwrap_or_else(|| if cfg!(target_os = "macos") { "mac".into() } else { "pc".into() });
        let http = reqwest::Client::builder().timeout(Duration::from_secs(60)).build().ok()?;
        Some(Self { name, secret, home: home.to_path_buf(), state: Arc::new(Mutex::new(LinkState::default())), http })
    }

    pub fn sign(&self, method: &str, path_q: &str, t: u64, body: &[u8]) -> String {
        hmac_hex(&self.secret, &format!("{}|{}|{}|{}", method.to_ascii_uppercase(), path_q, t, body_hash(body)))
    }

    /// Check an incoming peer request. Returns the caller's name.
    pub fn verify(&self, method: &str, path_q: &str, name: &str, t: &str, sig: &str, body: &[u8]) -> Result<String, &'static str> {
        let t: u64 = t.parse().map_err(|_| "bad time")?;
        if now().abs_diff(t) > 300 {
            return Err("clock skew over 5 minutes");
        }
        let want = self.sign(method, path_q, t, body);
        let ok: bool = want.len() == sig.len() && want.bytes().zip(sig.bytes()).fold(0u8, |a, (x, y)| a | (x ^ y)) == 0;
        if !ok {
            return Err("bad signature");
        }
        Ok(name.to_string())
    }

    fn topic(&self) -> String {
        format!("loki-{}", &hmac_hex(&self.secret, "loki-tunnel-rendezvous-v1")[..32])
    }

    fn ntfy(&self) -> String {
        std::env::var("LOKI_TUNNEL_NTFY").unwrap_or_else(|_| "https://ntfy.sh".into()).trim_end_matches('/').to_string()
    }

    fn post_sig(&self, name: &str, url: &str, t: u64) -> String {
        hmac_hex(&self.secret, &format!("{name}|{url}|{t}"))
    }

    /// Call a peer: signed request to its tunnel. `path_q` like "/runs?x=1".
    pub async fn call(&self, peer: &str, method: &str, path_q: &str, body: Vec<u8>, ctype: Option<&str>) -> Result<reqwest::Response, String> {
        let url = { self.state.lock().await.peers.get(peer).map(|p| p.url.clone()) }.ok_or("unknown or offline machine")?;
        let t = now();
        let sig = self.sign(method, path_q, t, &body);
        let m = reqwest::Method::from_bytes(method.as_bytes()).map_err(|e| e.to_string())?;
        let mut req = self.http.request(m, format!("{}{}", url.trim_end_matches('/'), path_q))
            .header(H_NAME, &self.name).header(H_TIME, t.to_string()).header(H_SIG, sig);
        if let Some(c) = ctype {
            req = req.header("content-type", c);
        }
        if !body.is_empty() {
            req = req.body(body);
        }
        req.send().await.map_err(|e| format!("{peer} unreachable: {e}"))
    }

    pub async fn call_json(&self, peer: &str, method: &str, path_q: &str, body: Option<&Value>) -> Result<Value, String> {
        let b = body.map(|v| v.to_string().into_bytes()).unwrap_or_default();
        let r = self.call(peer, method, path_q, b, body.map(|_| "application/json")).await?;
        if !r.status().is_success() {
            return Err(format!("{peer} answered {}", r.status()));
        }
        let text = r.text().await.map_err(|e| e.to_string())?;
        Ok(if text.is_empty() { json!(null) } else { serde_json::from_str(&text).unwrap_or(json!(text)) })
    }

    // ------------------------------------------------------------- tunnel + rendezvous

    async fn cloudflared(&self) -> Option<PathBuf> {
        let exe = if cfg!(windows) { "cloudflared.exe" } else { "cloudflared" };
        if let Ok(p) = std::env::var("LOKI_CLOUDFLARED") {
            if Path::new(&p).is_file() { return Some(PathBuf::from(p)); }
        }
        // the previous LOKI's copy, then LOKI's own, then PATH
        let data = self.home.parent().map(Path::to_path_buf).unwrap_or_else(|| self.home.clone());
        for c in [data.join("bin").join(exe), self.home.join("bin").join(exe)] {
            if c.is_file() { return Some(c); }
        }
        for dir in std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default()) {
            let c = dir.join(exe);
            if c.is_file() { return Some(c); }
        }
        let asset = if cfg!(windows) { "cloudflared-windows-amd64.exe".to_string() }
            else if cfg!(target_os = "macos") { format!("cloudflared-darwin-{}.tgz", if cfg!(target_arch = "aarch64") { "arm64" } else { "amd64" }) }
            else { format!("cloudflared-linux-{}", if cfg!(target_arch = "aarch64") { "arm64" } else { "amd64" }) };
        let url = format!("https://github.com/cloudflare/cloudflared/releases/latest/download/{asset}");
        tracing::info!("link: downloading cloudflared ({asset})");
        let bytes = self.http.get(&url).timeout(Duration::from_secs(600)).send().await.ok()?.bytes().await.ok()?;
        let dir = self.home.join("bin");
        let _ = std::fs::create_dir_all(&dir);
        let dest = dir.join(exe);
        if asset.ends_with(".tgz") {
            let tgz = dir.join("cloudflared.tgz");
            std::fs::write(&tgz, &bytes).ok()?;
            let ok = std::process::Command::new("tar").args(["-xzf"]).arg(&tgz).arg("-C").arg(&dir).status().ok()?.success();
            let _ = std::fs::remove_file(&tgz);
            if !ok { return None; }
        } else {
            std::fs::write(&dest, &bytes).ok()?;
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = std::fs::set_permissions(&dest, std::fs::Permissions::from_mode(0o755));
        }
        dest.is_file().then_some(dest)
    }

    async fn post_address(&self, url: &str) {
        let t = now();
        let msg = json!({"name": self.name, "url": url, "t": t as f64, "sig": self.post_sig(&self.name, url, t)});
        let r = self.http.post(format!("{}/{}", self.ntfy(), self.topic())).body(msg.to_string()).send().await;
        if let Err(e) = r {
            self.state.lock().await.error = format!("ntfy: {e}");
        }
    }

    /// Newest signed address per machine (not this one) from the topic.
    async fn read_addresses(&self) -> HashMap<String, (String, u64)> {
        let mut out: HashMap<String, (String, u64)> = HashMap::new();
        let url = format!("{}/{}/json?poll=1&since=13h", self.ntfy(), self.topic());
        let Ok(r) = self.http.get(&url).timeout(Duration::from_secs(20)).send().await else { return out };
        let Ok(text) = r.text().await else { return out };
        for line in text.lines() {
            let Ok(ev) = serde_json::from_str::<Value>(line) else { continue };
            let Some(msg) = ev["message"].as_str() else { continue };
            let Ok(d) = serde_json::from_str::<Value>(msg) else { continue };
            let (Some(name), Some(u), Some(t), Some(sig)) = (d["name"].as_str(), d["url"].as_str(), d["t"].as_f64(), d["sig"].as_str()) else { continue };
            let t = t as u64;
            if name == self.name || !u.starts_with("https://") || !u.ends_with(".trycloudflare.com") || now().saturating_sub(t) > 13 * 3600 {
                continue;
            }
            // the previous LOKI signed "%.0f" of a float time - the same digits as this integer
            if self.post_sig(name, u, t) != sig {
                continue;
            }
            if out.get(name).map(|x| x.1 < t).unwrap_or(true) {
                out.insert(name.to_string(), (u.to_string(), t));
            }
        }
        out
    }

    /// Run the tunnel (restarting it if it dies) and keep the address posted.
    pub async fn run_tunnel(self, port: u16) {
        loop {
            let Some(bin) = self.cloudflared().await else {
                self.state.lock().await.error = "cloudflared could not be downloaded".into();
                tokio::time::sleep(Duration::from_secs(600)).await;
                continue;
            };
            let mut cmd = tokio::process::Command::new(&bin);
            cmd.args(["tunnel", "--no-autoupdate", "--url", &format!("http://127.0.0.1:{port}")])
                .stdout(std::process::Stdio::null()).stderr(std::process::Stdio::piped()).stdin(std::process::Stdio::null()).kill_on_drop(true);
            #[cfg(windows)]
            {
                cmd.creation_flags(0x0800_0000);
            }
            let Ok(mut child) = cmd.spawn() else {
                self.state.lock().await.error = "cloudflared did not start".into();
                tokio::time::sleep(Duration::from_secs(120)).await;
                continue;
            };
            let stderr = child.stderr.take().unwrap();
            let me = self.clone();
            let reader = tokio::spawn(async move {
                use tokio::io::{AsyncBufReadExt, BufReader};
                let mut lines = BufReader::new(stderr).lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    if let Some(i) = line.find("https://") {
                        let u: String = line[i..].chars().take_while(|c| !c.is_whitespace() && *c != '|').collect();
                        if u.ends_with(".trycloudflare.com") {
                            tracing::info!("link: this machine is reachable at {u}");
                            me.state.lock().await.my_url = u.clone();
                            me.post_address(&u).await;
                        }
                    }
                }
            });
            // re-post while it lives
            let me2 = self.clone();
            let reposter = tokio::spawn(async move {
                loop {
                    tokio::time::sleep(REPOST).await;
                    let u = me2.state.lock().await.my_url.clone();
                    if !u.is_empty() { me2.post_address(&u).await; }
                }
            });
            let _ = child.wait().await;
            reader.abort();
            reposter.abort();
            self.state.lock().await.my_url.clear();
            tracing::warn!("link: tunnel stopped; starting it again");
            tokio::time::sleep(Duration::from_secs(10)).await;
        }
    }

    /// Find peers and check they answer, every minute.
    pub async fn run_discovery(self) {
        loop {
            let mut found = self.read_addresses().await;
            // fixed addresses (same network, or tests): LOKI_LINK_PEERS="pc=http://192.168.1.20:7718,mac=..."
            for pair in std::env::var("LOKI_LINK_PEERS").unwrap_or_default().split(',') {
                if let Some((n, u)) = pair.split_once('=') {
                    found.insert(n.trim().to_string(), (u.trim().to_string(), now()));
                }
            }
            for (name, (url, t)) in found {
                let hello = {
                    let mut st = self.state.lock().await;
                    let p = st.peers.entry(name.clone()).or_default();
                    p.name = name.clone();
                    if p.url != url { p.url = url.clone(); }
                    p.posted = t;
                    p.clone()
                };
                let ok = self.call_json(&name, "GET", "/hello", None).await;
                let mut st = self.state.lock().await;
                if let Some(p) = st.peers.get_mut(&name) {
                    p.checked = now();
                    p.online = ok.is_ok();
                    if let Ok(h) = ok { p.hello = h; }
                }
                drop(hello);
            }
            // look again soon while a machine is missing
            let all_on = { let st = self.state.lock().await; !st.peers.is_empty() && st.peers.values().all(|p| p.online) };
            tokio::time::sleep(Duration::from_secs(if all_on { 60 } else { 15 })).await;
        }
    }

    pub async fn status(&self) -> Value {
        let st = self.state.lock().await;
        let peers: Vec<&PeerInfo> = st.peers.values().collect();
        json!({"name": self.name, "reachable_at": st.my_url, "error": st.error, "peers": peers})
    }

    pub async fn online_peers(&self) -> Vec<String> {
        self.state.lock().await.peers.values().filter(|p| p.online).map(|p| p.name.clone()).collect()
    }

    // ------------------------------------------------------------- library mirror

    /// Keep a copy of every image the other machines made in `<home>/mirror/<machine>/<run>/<path>`, every 2 minutes.
    /// A picture deleted over there is deleted here too; nothing here is ever sent back.
    pub async fn run_mirror(self) {
        tokio::time::sleep(Duration::from_secs(20)).await;
        loop {
            for peer in self.online_peers().await {
                // its logs too, so either machine (and whoever helps) can read both
                if let Ok(v) = self.call_json(&peer, "GET", "/logs?lines=400", None).await {
                    let dir = self.home.join("mirror").join(clean(&peer)).join("logs");
                    let _ = std::fs::create_dir_all(&dir);
                    if let Some(o) = v.as_object() {
                        for (k, t) in o {
                            let _ = std::fs::write(dir.join(clean(k)), t.as_str().unwrap_or(""));
                        }
                    }
                }
                match self.mirror_one(&peer).await {
                    Ok((got, gone)) if got + gone > 0 => tracing::info!("mirror {peer}: {got} new, {gone} removed"),
                    Ok(_) => {}
                    Err(e) => tracing::warn!("mirror {peer}: {e}"),
                }
            }
            tokio::time::sleep(Duration::from_secs(120)).await;
        }
    }

    pub async fn mirror_one(&self, peer: &str) -> Result<(usize, usize), String> {
        let root = self.home.join("mirror").join(clean(peer));
        let mut want: HashMap<String, (u64, String)> = HashMap::new(); // rel -> (bytes, title)
        let mut stamp: HashMap<String, u64> = HashMap::new();            // rel -> modified time over there
        let per = 200;
        for page in 0..25 {
            let v = self.call_json(peer, "GET", &format!("/library?own=1&per={per}&page={page}"), None).await?;
            let items = v["items"].as_array().cloned().unwrap_or_default();
            for it in &items {
                let (Some(run), Some(path)) = (it["run"].as_str(), it["path"].as_str()) else { continue };
                let rel = format!("{}/{}", clean(run), path.split('/').map(clean).collect::<Vec<_>>().join("/"));
                if rel.contains("..") { continue; }
                stamp.insert(rel.clone(), it["modified"].as_u64().unwrap_or(0));
                want.insert(rel, (it["bytes"].as_u64().unwrap_or(0), it["title"].as_str().unwrap_or("").to_string()));
            }
            if items.len() < per { break; }
        }
        // what was copied last time (and when it changed over there): copy only what is new or changed since
        let index_path = root.join("index.json");
        let mut index: HashMap<String, u64> = std::fs::read_to_string(&index_path).ok().and_then(|t| serde_json::from_str(&t).ok()).unwrap_or_default();
        let mut got = 0;
        for (rel, (bytes, _)) in &want {
            let dest = root.join(rel);
            let there = stamp.get(rel).copied().unwrap_or(0);
            if dest.is_file() && (index.get(rel) == Some(&there) || std::fs::metadata(&dest).map(|m| m.len() == *bytes).unwrap_or(false) && !index.contains_key(rel)) {
                index.insert(rel.clone(), there);
                continue;
            }
            let (run, path) = rel.split_once('/').unwrap();
            let r = self.call(peer, "GET", &format!("/runs/{}/file?path={}", enc(run), enc(path)), vec![], None).await?;
            if !r.status().is_success() { continue; }
            let Ok(b) = r.bytes().await else { continue };
            if let Some(d) = dest.parent() { let _ = std::fs::create_dir_all(d); }
            let tmp = dest.with_extension("part");
            if std::fs::write(&tmp, &b).is_ok() && std::fs::rename(&tmp, &dest).is_ok() {
                got += 1;
                index.insert(rel.clone(), there);
            }
        }
        index.retain(|k, _| want.contains_key(k));
        // titles for the Library captions
        let titles: HashMap<String, String> = want.iter().map(|(rel, (_, t))| (rel.split('/').next().unwrap_or("").to_string(), t.clone())).collect();
        let _ = std::fs::create_dir_all(&root);
        let _ = std::fs::write(root.join("titles.json"), serde_json::to_string(&titles).unwrap_or_default());
        let _ = std::fs::write(&index_path, serde_json::to_string(&index).unwrap_or_default());
        // deletes: anything here the other machine no longer has
        let mut gone = 0;
        let mut stack = vec![root.clone()];
        while let Some(dir) = stack.pop() {
            let Ok(rd) = std::fs::read_dir(&dir) else { continue };
            for e in rd.flatten() {
                let p = e.path();
                if p.is_dir() { stack.push(p); continue; }
                let rel = p.strip_prefix(&root).unwrap_or(&p).to_string_lossy().replace('\\', "/");
                if rel == "titles.json" || rel == "index.json" || rel.starts_with("logs/") { continue; }
                if !want.contains_key(&rel) && std::fs::remove_file(&p).is_ok() { gone += 1; }
            }
        }
        Ok((got, gone))
    }
}

/// A safe single path segment.
pub fn clean(s: &str) -> String {
    s.chars().map(|c| if c.is_alphanumeric() || matches!(c, '.' | '-' | '_' | ' ') { c } else { '_' }).collect::<String>().trim().trim_start_matches('.').to_string()
}

/// Percent-encode for a query value or path segment.
pub fn enc(s: &str) -> String {
    s.bytes().map(|b| if b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.' | b'~') { (b as char).to_string() } else { format!("%{b:02X}") }).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn signatures_and_topic_match_the_previous_loki() {
        let home = std::env::temp_dir();
        std::env::set_var("LOKI_PEER_SECRET", "0123456789abcdef0123456789abcdef");
        std::env::set_var("LOKI_PEER_NAME", "pc");
        let l = Link::from_env(&home).unwrap();
        // python: "loki-" + hmac.new(secret, b"loki-tunnel-rendezvous-v1", sha256).hexdigest()[:32]
        assert!(l.topic().starts_with("loki-") && l.topic().len() == 37);
        let t = now();
        let sig = l.sign("POST", "/runs", t, b"{}");
        assert!(l.verify("POST", "/runs", "mac", &t.to_string(), &sig, b"{}").is_ok());
        assert!(l.verify("POST", "/runs", "mac", &t.to_string(), &sig, b"{\"x\":1}").is_err(), "body changed");
        assert!(l.verify("POST", "/runs", "mac", &(t - 900).to_string(), &l.sign("POST", "/runs", t - 900, b"{}"), b"{}").is_err(), "too old");
    }
}
