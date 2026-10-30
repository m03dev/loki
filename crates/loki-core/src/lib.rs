//! LOKI driver core.
//!
//! - [`pool`]: free-model pool with budgets, cooldowns and failover
//! - [`llm`]: OpenAI-compatible client with tool-call repair for free/local models
//! - [`journal`]: crash-safe run files (checklist, progress, steps, summary)
//! - [`tools`]: small confined toolbox and the independent task checker
//! - [`agent`]: the long-running loop that ties them together

pub mod agent;
pub mod journal;
pub mod llm;
pub mod pool;
pub mod risk;
pub mod tools;
