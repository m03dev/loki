//! OpenAI-compatible chat client with tool calling, plus a repair step for the
//! free/local models that write their tool call into plain text instead of the
//! `tool_calls` field.

use crate::pool::{ModelPool, Role};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::time::Duration;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Msg {
    pub role: String,
    #[serde(default)]
    pub content: String,
}

impl Msg {
    pub fn system(s: impl Into<String>) -> Self { Self { role: "system".into(), content: s.into() } }
    pub fn user(s: impl Into<String>) -> Self { Self { role: "user".into(), content: s.into() } }
    pub fn assistant(s: impl Into<String>) -> Self { Self { role: "assistant".into(), content: s.into() } }
}

#[derive(Debug, Clone, PartialEq)]
pub struct ToolCall {
    pub name: String,
    pub args: Value,
}

#[derive(Debug, Clone)]
pub struct Reply {
    pub text: String,
    pub call: Option<ToolCall>,
    pub provider: String,
    pub model: String,
}

#[derive(Debug)]
pub enum LlmError {
    /// Every provider for the role is out of budget or cooling down.
    AllBusy { retry_in_secs: i64 },
    Other(String),
}

impl std::fmt::Display for LlmError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            LlmError::AllBusy { retry_in_secs } => write!(f, "all free providers busy, retry in {retry_in_secs}s"),
            LlmError::Other(s) => write!(f, "{s}"),
        }
    }
}

pub struct Llm {
    http: reqwest::Client,
}

impl Default for Llm {
    fn default() -> Self { Self::new() }
}

impl Llm {
    pub fn new() -> Self {
        let http = reqwest::Client::builder()
            .timeout(Duration::from_secs(180))
            .build()
            .expect("http client");
        Self { http }
    }

    /// One model turn. Tries providers in pool order until one answers.
    pub async fn chat(
        &self,
        pool: &tokio::sync::Mutex<ModelPool>,
        role: Role,
        messages: &[Msg],
        tools: &Value,
    ) -> Result<Reply, LlmError> {
        self.chat_pref(pool, role, messages, tools, None, &[]).await
    }

    pub async fn chat_pref(
        &self,
        pool: &tokio::sync::Mutex<ModelPool>,
        role: Role,
        messages: &[Msg],
        tools: &Value,
        prefer: Option<&str>,
        exclude: &[String],
    ) -> Result<Reply, LlmError> {
        let mut tried: Vec<String> = exclude.to_vec();
        loop {
            let pick = { pool.lock().await.pick_pref(role, &tried, prefer) };
            let Some(pick) = pick else {
                let wait = pool
                    .lock()
                    .await
                    .next_ready(role)
                    .map(|t| (t - chrono::Utc::now()).num_seconds().max(1))
                    .unwrap_or(60);
                return Err(LlmError::AllBusy { retry_in_secs: wait });
            };
            let name = pick.provider.name.clone();
            tried.push(name.clone());
            let url = format!("{}/chat/completions", pick.provider.base_url.trim_end_matches('/'));
            let mut body = json!({
                "model": pick.model,
                "messages": messages,
                "temperature": 0.2,
            });
            if tools.as_array().map(|a| !a.is_empty()).unwrap_or(false) {
                body["tools"] = tools.clone();
                body["tool_choice"] = json!("auto");
            }
            let mut req = self.http.post(&url).json(&body);
            if let Some(k) = &pick.api_key {
                req = req.bearer_auth(k);
            }
            let started = std::time::Instant::now();
            match req.send().await {
                Ok(resp) => {
                    let status = resp.status();
                    if status.as_u16() == 429 || status.as_u16() == 402 {
                        pool.lock().await.report_fail(&name, true);
                        continue;
                    }
                    if !status.is_success() {
                        pool.lock().await.report_fail(&name, false);
                        continue;
                    }
                    let v: Value = match resp.json().await {
                        Ok(v) => v,
                        Err(_) => {
                            pool.lock().await.report_fail(&name, false);
                            continue;
                        }
                    };
                    let msg = &v["choices"][0]["message"];
                    let text = msg["content"].as_str().unwrap_or("").to_string();
                    let call = parse_native_call(msg).or_else(|| repair_call_with(&text, tools));
                    let mut p = pool.lock().await;
                    if let Some(n) = v["usage"]["completion_tokens"].as_u64() {
                        p.report_speed(&name, &pick.model, n, started.elapsed().as_secs_f64());
                    }
                    p.report_ok(&name);
                    drop(p);
                    return Ok(Reply { text, call, provider: name, model: pick.model });
                }
                Err(_) => {
                    pool.lock().await.report_fail(&name, false);
                    continue;
                }
            }
        }
    }
}

impl Llm {
    /// Ask a vision model about one image. `image` is JPEG/PNG bytes (send small: ~768 px JPEG).
    pub async fn vision(&self, pool: &tokio::sync::Mutex<ModelPool>, prompt: &str, image: &[u8], mime: &str) -> Result<Reply, LlmError> {
        use base64::Engine;
        let data = base64::engine::general_purpose::STANDARD.encode(image);
        let content = json!([
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": format!("data:{mime};base64,{data}")}}
        ]);
        let mut tried: Vec<String> = Vec::new();
        loop {
            let pick = { pool.lock().await.pick(Role::Vision, &tried) };
            let Some(pick) = pick else { return Err(LlmError::AllBusy { retry_in_secs: 60 }) };
            let name = pick.provider.name.clone();
            tried.push(name.clone());
            let url = format!("{}/chat/completions", pick.provider.base_url.trim_end_matches('/'));
            let body = json!({"model": pick.model, "temperature": 0.1, "max_tokens": 700,
                "messages": [{"role": "user", "content": content}]});
            let mut req = self.http.post(&url).json(&body);
            if let Some(k) = &pick.api_key {
                req = req.bearer_auth(k);
            }
            match req.send().await {
                Ok(r) if r.status().is_success() => {
                    let v: Value = r.json().await.unwrap_or(json!({}));
                    let text = v["choices"][0]["message"]["content"].as_str().unwrap_or("").to_string();
                    if text.trim().is_empty() {
                        pool.lock().await.report_fail(&name, false);
                        continue;
                    }
                    pool.lock().await.report_ok(&name);
                    return Ok(Reply { text, call: None, provider: name, model: pick.model });
                }
                Ok(r) => {
                    let limited = matches!(r.status().as_u16(), 429 | 402);
                    pool.lock().await.report_fail(&name, limited);
                }
                Err(_) => pool.lock().await.report_fail(&name, false),
            }
        }
    }
}

fn parse_native_call(msg: &Value) -> Option<ToolCall> {
    let tc = msg["tool_calls"].as_array()?.first()?;
    let name = tc["function"]["name"].as_str()?.to_string();
    let raw = &tc["function"]["arguments"];
    let args = match raw {
        Value::String(s) => parse_json_lenient(s).unwrap_or(json!({})),
        Value::Object(_) => raw.clone(),
        _ => json!({}),
    };
    Some(ToolCall { name, args })
}

/// Free models often answer with a JSON blob (sometimes fenced) instead of a
/// native tool call. Accept `{"tool": .., "args": ..}`, `{"name": .., "arguments": ..}`.
pub fn repair_call(text: &str) -> Option<ToolCall> {
    repair_call_with(text, &crate::tools::schemas())
}

/// Like `repair_call`, and when the JSON names no tool, infer it from which tool's
/// required arguments it carries (`{"args":{"tasks":[...]}}` is a `plan`).
pub fn repair_call_with(text: &str, schemas: &Value) -> Option<ToolCall> {
    for candidate in json_candidates(text) {
        if let Some(v) = parse_json_lenient(&candidate) {
            if v.get("tool").or_else(|| v.get("name")).and_then(|n| n.as_str()).is_none() {
                let args = v.get("args").or_else(|| v.get("arguments")).or_else(|| v.get("parameters")).cloned().unwrap_or_else(|| v.clone());
                if let Some(name) = infer_tool(&args, schemas) {
                    return Some(ToolCall { name, args });
                }
                continue;
            }
            let name = v.get("tool").or_else(|| v.get("name")).and_then(|n| n.as_str());
            if let Some(name) = name {
                let args = v
                    .get("args")
                    .or_else(|| v.get("arguments"))
                    .or_else(|| v.get("parameters"))
                    .cloned()
                    .unwrap_or(json!({}));
                let args = match args {
                    Value::String(s) => parse_json_lenient(&s).unwrap_or(json!({})),
                    a => a,
                };
                return Some(ToolCall { name: name.to_string(), args });
            }
        }
    }
    None
}

/// The one tool whose required arguments are all present (most required keys wins; ties = unknown).
fn infer_tool(args: &Value, schemas: &Value) -> Option<String> {
    let obj = args.as_object()?;
    let mut best: Option<(usize, String)> = None;
    let mut tie = false;
    for t in schemas.as_array()? {
        let f = &t["function"];
        let req: Vec<&str> = f["parameters"]["required"].as_array().map(|a| a.iter().filter_map(|x| x.as_str()).collect()).unwrap_or_default();
        let props = f["parameters"]["properties"].as_object();
        if req.is_empty() || !req.iter().all(|k| obj.contains_key(*k)) {
            continue;
        }
        if obj.keys().any(|k| props.map(|p| !p.contains_key(k)).unwrap_or(true)) {
            continue; // carries keys this tool doesn't take
        }
        let score = req.len();
        match &best {
            Some((b, _)) if *b > score => {}
            Some((b, _)) if *b == score => tie = true,
            _ => { best = Some((score, f["name"].as_str()?.to_string())); tie = false; }
        }
    }
    if tie { None } else { best.map(|b| b.1) }
}

fn json_candidates(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    // Fenced blocks first.
    let mut rest = text;
    while let Some(start) = rest.find("```") {
        let after = &rest[start + 3..];
        let body_start = after.find('\n').map(|i| i + 1).unwrap_or(0);
        if let Some(end) = after[body_start..].find("```") {
            out.push(after[body_start..body_start + end].trim().to_string());
            rest = &after[body_start + end + 3..];
        } else {
            break;
        }
    }
    // Then the outermost balanced {...} in the raw text.
    if let Some(s) = text.find('{') {
        let mut depth = 0i32;
        let mut in_str = false;
        let mut esc = false;
        for (i, ch) in text[s..].char_indices() {
            if in_str {
                if esc { esc = false; } else if ch == '\\' { esc = true; } else if ch == '"' { in_str = false; }
                continue;
            }
            match ch {
                '"' => in_str = true,
                '{' => depth += 1,
                '}' => {
                    depth -= 1;
                    if depth == 0 {
                        out.push(text[s..s + i + 1].to_string());
                        break;
                    }
                }
                _ => {}
            }
        }
    }
    out
}

/// The first JSON object in a model's text answer (fenced or bare).
pub fn extract_json(text: &str) -> Option<Value> {
    json_candidates(text).into_iter().find_map(|c| parse_json_lenient(&c))
}

/// Strict parse, then a forgiving pass (trailing commas, single quotes).
pub fn parse_json_lenient(s: &str) -> Option<Value> {
    if let Ok(v) = serde_json::from_str::<Value>(s) {
        return Some(v);
    }
    let fixed = s.replace(",}", "}").replace(",]", "]").replace(", }", "}").replace(", ]", "]");
    if let Ok(v) = serde_json::from_str::<Value>(&fixed) {
        return Some(v);
    }
    if !fixed.contains('"') {
        return serde_json::from_str::<Value>(&fixed.replace('\'', "\"")).ok();
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn repairs_fenced_tool_json() {
        let t = "Sure!\n```json\n{\"tool\": \"write_file\", \"args\": {\"path\": \"a.txt\", \"content\": \"hi\"},}\n```";
        let c = repair_call(t).unwrap();
        assert_eq!(c.name, "write_file");
        assert_eq!(c.args["path"], "a.txt");
    }

    #[test]
    fn repairs_bare_json_with_string_args() {
        let t = r#"I will call {"name":"read_file","arguments":"{\"path\":\"x.md\"}"} now"#;
        let c = repair_call(t).unwrap();
        assert_eq!(c.name, "read_file");
        assert_eq!(c.args["path"], "x.md");
    }

    #[test]
    fn infers_the_tool_from_its_arguments() {
        let t = r#"{"args":{"tasks":[{"title":"Render","check":"file:r.png"}]}}"#;
        assert_eq!(repair_call(t).unwrap().name, "plan");
        assert_eq!(repair_call(r#"{"path":"a.py","content":"x"}"#).unwrap().name, "write_file");
        assert_eq!(repair_call(r#"{"command":"blender -b","why":"render"}"#).unwrap().name, "run");
        assert!(repair_call(r#"{"foo":1}"#).is_none());
    }

    #[test]
    fn plain_text_is_not_a_call() {
        assert!(repair_call("All done, nothing to do.").is_none());
    }
}
