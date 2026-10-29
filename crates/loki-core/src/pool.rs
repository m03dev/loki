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
}

#[derive(Debug, Serialize, Deserialize, Default)]
struct PoolState {
    usage: HashMap<String, Usage>,
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

    pub fn providers(&self) -> &[Provider] {
        &self.providers
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
        self.pick_at(role, skip, Utc::now())
    }

    pub fn pick_at(&mut self, role: Role, skip: &[String], now: DateTime<Utc>) -> Option<Pick> {
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
            (p.priority, rel)
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

    pub fn report_ok(&mut self, name: &str) {
        let u = self.usage(name, Utc::now());
        u.consecutive_failures = 0;
        u.successes += 1;
        self.save();
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
