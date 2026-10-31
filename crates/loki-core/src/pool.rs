//! Free-model pool.
//!
//! Every provider is an OpenAI-compatible endpoint with its own free-tier
//! budget. The pool picks the best provider that still has budget for a role,
//! puts a provider on cooldown when it rate-limits or fails, and rolls over to
//! the next one. A run never dies because one free provider hit its cap.

use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

/// What a model is used for. A provider lists one model id per role it serves.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Role {
    /// Plans and drives long runs. Needs reliable tool calling.
    Brain,
    /// Looks at images (renders, concept art) to judge results.
    Vision,
    /// Cheap, quick work: summaries, compaction, naming.
    Fast,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Provider {
    pub name: String,
    pub base_url: String,
    /// Name of the environment variable holding the key. Empty = no key needed.
    #[serde(default)]
    pub key_env: String,
    /// Role -> model id on this provider.
    pub models: HashMap<Role, String>,
    /// Requests per minute allowed on the free tier (0 = unknown, treat as 10).
    #[serde(default)]
    pub rpm: u32,
    /// Requests per day allowed on the free tier (0 = unlimited / local).
    #[serde(default)]
    pub rpd: u32,
    /// Lower number = tried first.
    #[serde(default)]
    pub priority: i32,
    /// Local providers never leave the machine and have no daily cap.
    #[serde(default)]
    pub local: bool,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
struct Usage {
    day: String,
    today: u32,
    recent: Vec<DateTime<Utc>>,
    cooldown_until: Option<DateTime<Utc>>,
    consecutive_failures: u32,
    successes: u64,
    failures: u64,
    /// The work itself: checks this provider's steps passed / failed (a model that answers but builds junk loses here).
    #[serde(default)]
    checks_passed: u64,
    #[serde(default)]
    checks_failed: u64,
}

#[derive(Debug, Serialize, Deserialize, Default)]
struct PoolState {
    usage: HashMap<String, Usage>,
    /// "provider|model" -> measured generation speed
    #[serde(default)]
    speeds: HashMap<String, Speed>,
}

/// Tokens per second measured on real answers (exponential average), and the wait before the first byte.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Speed {
    pub tps: f64,
    pub latency_ms: f64,
    pub samples: u32,
}

#[derive(Debug, Clone)]
pub struct Pick {
    pub provider: Provider,
    pub model: String,
    pub api_key: Option<String>,
}

pub struct ModelPool {
    providers: Vec<Provider>,
    state: PoolState,
    state_path: Option<PathBuf>,
}

#[derive(Debug, Deserialize)]
struct ProvidersFile {
    provider: Vec<Provider>,
}

impl ModelPool {
    pub fn new(providers: Vec<Provider>) -> Self {
        Self { providers, state: PoolState::default(), state_path: None }
    }

    /// Load `providers.toml` and remember usage in `state_path` across restarts.
    pub fn load(providers_toml: &Path, state_path: &Path) -> anyhow::Result<Self> {
        let text = std::fs::read_to_string(providers_toml)?;
        let file: ProvidersFile = toml::from_str(&text)?;
        let state = std::fs::read_to_string(state_path)
            .ok()
            .and_then(|s| serde_json::from_str(&s).ok())
            .unwrap_or_default();
        Ok(Self { providers: file.provider, state, state_path: Some(state_path.to_path_buf()) })
    }

    /// Providers given directly, with usage remembered in `state_path`.
    pub fn with_state(providers: Vec<Provider>, state_path: &Path) -> Self {
        let state = std::fs::read_to_string(state_path).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default();
        Self { providers, state, state_path: Some(state_path.to_path_buf()) }
    }

    pub fn providers_mut(&mut self) -> &mut Vec<Provider> {
        &mut self.providers
    }

    pub fn providers(&self) -> &[Provider] {
        &self.providers
    }

    /// Point local providers at the models this machine really has (Ollama names vary per machine).
    /// `available` = model names the local server lists; `pinned` = the owner's chosen local model.
    pub fn fit_local(&mut self, provider: &str, available: &[String], pinned: Option<&str>) -> Vec<String> {
        let mut changes = Vec::new();
        let Some(p) = self.providers.iter_mut().find(|p| p.name == provider) else { return changes };
        let pick = pinned
            .filter(|m| !m.trim().is_empty())
            .map(|m| m.trim().to_string())
            .or_else(|| available.iter().find(|m| m.contains("qwen")).cloned())
            .or_else(|| available.first().cloned());
        let Some(pick) = pick else { return changes };
        for (role, model) in p.models.iter_mut() {
            let missing = !available.iter().any(|a| a == model || a.trim_end_matches(":latest") == model);
            if missing || pinned.is_some_and(|m| !m.trim().is_empty()) {
                if *model != pick {
                    changes.push(format!("{provider} {role:?}: {model} -> {pick}"));
                    *model = pick.clone();
                }
            }
        }
        changes
    }

    fn usage(&mut self, name: &str, now: DateTime<Utc>) -> &mut Usage {
        let day = now.format("%Y-%m-%d").to_string();
        let u = self.state.usage.entry(name.to_string()).or_default();
        if u.day != day {
            u.day = day;
            u.today = 0;
        }
        u.recent.retain(|t| *t > now - Duration::seconds(60));
        u
    }

    /// Best provider for `role` that has a key, budget and is not cooling down.
    /// `skip` lets a caller exclude providers it already tried for this request.
    pub fn pick(&mut self, role: Role, skip: &[String]) -> Option<Pick> {
        self.pick_at(role, skip, Utc::now(), None)
    }

    /// Like `pick`, but `prefer` (a provider name) is tried first when it can serve.
    pub fn pick_pref(&mut self, role: Role, skip: &[String], prefer: Option<&str>) -> Option<Pick> {
        self.pick_at(role, skip, Utc::now(), prefer)
    }

    pub fn pick_at(&mut self, role: Role, skip: &[String], now: DateTime<Utc>, prefer: Option<&str>) -> Option<Pick> {
        let mut candidates: Vec<Provider> = self
            .providers
            .iter()
            .filter(|p| p.models.contains_key(&role) && !skip.contains(&p.name))
            .cloned()
            .collect();
        // Proven-reliable providers first within the same priority.
        candidates.sort_by_key(|p| {
            let rel = self
                .state
                .usage
                .get(&p.name)
                .map(|u| u.consecutive_failures)
                .unwrap_or(0);
            let first = prefer.is_some_and(|n| n == p.name);
            // evidence: up to 8 priority points for a provider whose steps keep passing their checks
            let (ok, bad) = self.state.usage.get(&p.name).map(|u| (u.checks_passed, u.checks_failed)).unwrap_or((0, 0));
            let quality = (ok as f64 + 1.0) / ((ok + bad) as f64 + 2.0);
            (!first, p.priority - (quality * 8.0).round() as i32, rel)
        });
        for p in candidates {
            let key = if p.key_env.is_empty() {
                None
            } else {
                match std::env::var(&p.key_env) {
                    Ok(k) if !k.trim().is_empty() => Some(k),
                    _ => continue, // not set up on this machine
                }
            };
            let rpm = if p.rpm == 0 { 10 } else { p.rpm };
            let u = self.usage(&p.name, now);
            if matches!(u.cooldown_until, Some(t) if t > now) {
                continue;
            }
            if p.rpd > 0 && u.today >= p.rpd {
                continue;
            }
            if u.recent.len() as u32 >= rpm {
                continue;
            }
            u.today += 1;
            u.recent.push(now);
            let model = p.models[&role].clone();
            return Some(Pick { provider: p, model, api_key: key });
        }
        None
    }

    /// Record a real answer's speed: `tokens` generated in `secs` (whole request).
    pub fn report_speed(&mut self, provider: &str, model: &str, tokens: u64, secs: f64) {
        if tokens < 8 || secs <= 0.0 {
            return;
        }
        let tps = tokens as f64 / secs;
        let sp = self.state.speeds.entry(format!("{provider}|{model}")).or_default();
        let a = if sp.samples == 0 { 1.0 } else { 0.3 };
        sp.tps = sp.tps * (1.0 - a) + tps * a;
        sp.latency_ms = sp.latency_ms * (1.0 - a) + secs * 1000.0 * a;
        sp.samples += 1;
    }

    pub fn speeds(&self) -> HashMap<String, Speed> {
        self.state.speeds.clone()
    }

    pub fn report_ok(&mut self, name: &str) {
        let u = self.usage(name, Utc::now());
        u.consecutive_failures = 0;
        u.successes += 1;
        self.save();
    }

    /// A checklist step this provider worked on passed (or failed) the driver's check.
    pub fn report_check(&mut self, name: &str, passed: bool) {
        let u = self.usage(name, Utc::now());
        if passed { u.checks_passed += 1 } else { u.checks_failed += 1 }
        self.save();
    }

    /// Per provider: (checks passed, checks failed).
    pub fn check_scores(&self) -> HashMap<String, (u64, u64)> {
        self.state.usage.iter().map(|(k, u)| (k.clone(), (u.checks_passed, u.checks_failed))).collect()
    }

    /// `rate_limited` = HTTP 429 / quota; other failures back off more gently.
    pub fn report_fail(&mut self, name: &str, rate_limited: bool) {
        self.report_fail_at(name, rate_limited, Utc::now())
    }

    pub fn report_fail_at(&mut self, name: &str, rate_limited: bool, now: DateTime<Utc>) {
        let u = self.usage(name, now);
        u.failures += 1;
        u.consecutive_failures += 1;
        let n = u.consecutive_failures.min(6);
        let secs = if rate_limited { 30 * 2i64.pow(n) } else { 5 * 2i64.pow(n) };
        u.cooldown_until = Some(now + Duration::seconds(secs.min(3600)));
        self.save();
    }

    /// Earliest moment any provider for `role` becomes usable again.
    pub fn next_ready(&self, role: Role) -> Option<DateTime<Utc>> {
        self.providers
            .iter()
            .filter(|p| p.models.contains_key(&role))
            .filter_map(|p| self.state.usage.get(&p.name).and_then(|u| u.cooldown_until))
            .min()
    }

    fn save(&self) {
        if let Some(path) = &self.state_path {
            if let Ok(s) = serde_json::to_string_pretty(&self.state) {
                let _ = crate::journal::atomic_write(path, s.as_bytes());
            }
        }
    }
}
