//! Every knob of the driver in one place, adjustable from Settings (saved in <home>/settings.json under "tuning")
//! and read fresh each turn, so a change applies to running jobs without a restart.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct Tuning {
    pub look_pass: f64,
    pub stall_steps: u32,
    pub idle_nudge: u32,
    pub idle_ask: u32,
    pub task_attempts: u32,
    pub context_window: usize,
    pub rest_cap_s: u64,
    pub command_timeout_s: u64,
    pub session_timeout_s: u64,
    /// Preferred provider per role ("" = pick by evidence).
    pub brain: String,
    pub fast: String,
    pub vision: String,
}

impl Default for Tuning {
    fn default() -> Self {
        Self { look_pass: 7.0, stall_steps: 30, idle_nudge: 10, idle_ask: 16, task_attempts: 12, context_window: 8,
               rest_cap_s: 300, command_timeout_s: 600, session_timeout_s: 300, brain: String::new(), fast: String::new(), vision: String::new() }
    }
}

impl Tuning {
    pub fn load() -> Self {
        let Ok(home) = std::env::var("LOKI_HOME") else { return Self::default() };
        std::fs::read_to_string(std::path::Path::new(&home).join("settings.json")).ok()
            .and_then(|t| serde_json::from_str::<Value>(&t).ok())
            .and_then(|v| serde_json::from_value::<Tuning>(v["tuning"].clone()).ok())
            .unwrap_or_default()
    }

    /// What the window shows: label, help, min, max per number knob (model roles are pickers of their own).
    pub fn describe() -> Value {
        json!([
            {"key": "look_pass", "label": "Vision pass mark", "help": "A look: check passes at this score out of 10", "min": 1, "max": 10, "step": 0.5},
            {"key": "stall_steps", "label": "Ask after steps without a pass", "help": "Steps without passing any check before the job stops and asks you", "min": 5, "max": 200, "step": 1},
            {"key": "idle_nudge", "label": "Nudge after idle turns", "help": "Turns that change nothing before the model is told to make a real change", "min": 2, "max": 100, "step": 1},
            {"key": "idle_ask", "label": "Ask after idle turns", "help": "Turns that change nothing before the job asks you", "min": 3, "max": 200, "step": 1},
            {"key": "task_attempts", "label": "Attempts per step", "help": "Failed attempts at one step before it is set aside", "min": 1, "max": 50, "step": 1},
            {"key": "context_window", "label": "Steps kept word for word", "help": "Recent steps the model sees in full; older ones are summarised", "min": 2, "max": 30, "step": 1},
            {"key": "rest_cap_s", "label": "Longest rest (s)", "help": "Longest wait when every free model is busy", "min": 10, "max": 3600, "step": 10},
            {"key": "command_timeout_s", "label": "Command time limit (s)", "help": "A command that runs longer is stopped", "min": 10, "max": 7200, "step": 10},
            {"key": "session_timeout_s", "label": "Session step time limit (s)", "help": "One live-session step that runs longer is stopped", "min": 10, "max": 3600, "step": 10}
        ])
    }
}
