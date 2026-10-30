//! What a command would do, in plain words, and how risky it is.
//!
//! Patterns ported from OpenHands' PatternSecurityAnalyzer (MIT), by way of the previous LOKI's
//! engine/command_risk.py, plus a plain-English summary so approval cards read like
//! "Copies dungeon.png into this job's renders folder" instead of a raw command line.

use regex::Regex;
use serde::Serialize;
use std::path::Path;
use std::sync::OnceLock;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Risk {
    Low,
    Medium,
    High,
}

#[derive(Debug, Clone, Serialize)]
pub struct Assessment {
    pub risk: Risk,
    /// Why it is risky ("deletes files", "installs software").
    pub reasons: Vec<String>,
    /// One plain sentence: what the command does.
    pub what: String,
    /// Paths it touches outside the job's folder (empty = stays inside).
    pub outside: Vec<String>,
}

const HIGH: &[(&str, &str)] = &[
    (r"\brm\s+(?:-[frR]{2,}|-[rR]\s+-f|-f\s+-[rR]|--recursive\s+--force|--force\s+--recursive)\b", "deletes a whole folder tree"),
    (r"\bsudo\s+rm\b", "deletes files as administrator"),
    (r"\bmkfs\.\w+", "formats a disk"),
    (r"\bdd\b.{0,100}of=/dev/", "writes raw to a disk"),
    (r"\bcurl\b[^|]{0,200}\|\s*(?:ba|z)?sh\b", "downloads a script and runs it"),
    (r"\bwget\b[^|]{0,200}\|\s*(?:ba|z)?sh\b", "downloads a script and runs it"),
    (r"(?i)\b(?:rd|rmdir)\s+/s\b", "deletes a whole folder tree"),
    (r"(?i)\bdel\s+(?:/[a-z]\s+){0,4}/s\b", "deletes files in every subfolder"),
    (r"(?i)\bformat\s+[a-z]:", "formats a drive"),
    (r"(?i)\bremove-item\b.{0,120}-recurse\b", "deletes a whole folder tree"),
    (r"(?i)\b(?:iex|invoke-expression)\b", "runs code it builds on the fly"),
    (r"\bgit\s+push\b.{0,80}(?:--force\b|\s-f\b)", "overwrites history on GitHub"),
    (r"\bgit\s+reset\s+--hard\b", "throws away uncommitted work"),
    (r"\bchmod\s+(?:-R\s+)?777\s+/", "opens system files to everyone"),
    (r"(?i)\b(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions?|prompts?|rules?)\b", "contains an instruction-override attempt"),
];
const MEDIUM: &[(&str, &str)] = &[
    (r"\bcurl\b.{0,100}https?://", "contacts the internet"),
    (r"\bwget\b.{0,100}https?://", "downloads from the internet"),
    (r"(?i)\b(?:pip|pip3|npm|pnpm|yarn|brew|winget|choco|apt|apt-get|ollama)\s+(?:install|add|i|pull)\b", "installs software"),
    (r"\bgit\s+(?:push|clean\s+-[a-z]*f)\b", "changes GitHub or deletes untracked files"),
    (r"\brm\s+", "deletes files"),
    (r"(?i)\bdel\s+", "deletes files"),
    (r"(?i)\b(?:shutdown|restart-computer|taskkill)\b", "stops programs or the computer"),
];

fn compiled(list: &'static [(&'static str, &'static str)], cell: &'static OnceLock<Vec<(Regex, &'static str)>>) -> &'static [(Regex, &'static str)] {
    cell.get_or_init(|| list.iter().filter_map(|(p, d)| Regex::new(p).ok().map(|r| (r, *d))).collect())
}

/// Strip invisible characters and collapse whitespace so an evasion doesn't slip past a pattern.
fn normalize(s: &str) -> String {
    let clean: String = s
        .chars()
        .filter(|c| !matches!(*c as u32, 0x00..=0x08 | 0x0b | 0x0c | 0x0e..=0x1f | 0x7f..=0x9f | 0x200b..=0x200f | 0x202a..=0x202e | 0x2060..=0x206f | 0xfeff))
        .collect();
    clean.split_whitespace().collect::<Vec<_>>().join(" ")
}

pub fn assess(command: &str, workspace: &Path) -> Assessment {
    static H: OnceLock<Vec<(Regex, &'static str)>> = OnceLock::new();
    static M: OnceLock<Vec<(Regex, &'static str)>> = OnceLock::new();
    let text = normalize(command);
    let mut risk = Risk::Low;
    let mut reasons: Vec<String> = Vec::new();
    for (re, why) in compiled(HIGH, &H) {
        if re.is_match(&text) {
            risk = Risk::High;
            reasons.push(why.to_string());
        }
    }
    if risk != Risk::High {
        for (re, why) in compiled(MEDIUM, &M) {
            if re.is_match(&text) {
                risk = Risk::Medium;
                reasons.push(why.to_string());
            }
        }
    }
    reasons.dedup();
    let outside = outside_paths(&text, workspace);
    if !outside.is_empty() && risk == Risk::Low {
        risk = Risk::Medium;
        reasons.push("works outside this job's folder".into());
    }
    Assessment { risk, reasons, what: describe(&text), outside }
}

/// Absolute paths in the command that are not inside the workspace.
fn outside_paths(cmd: &str, ws: &Path) -> Vec<String> {
    static P: OnceLock<Regex> = OnceLock::new();
    let re = P.get_or_init(|| Regex::new(r#"(?i)(?:[a-z]:[\\/][^\s"'<>|]*|(?:^|\s)/(?:[^\s"'<>|]+))"#).unwrap());
    let ws_n = ws.to_string_lossy().replace('\\', "/").to_ascii_lowercase();
    let mut out = Vec::new();
    for m in re.find_iter(cmd) {
        let p = m.as_str().trim().trim_matches(|c| c == '"' || c == '\'');
        let n = p.replace('\\', "/").to_ascii_lowercase();
        if n.starts_with(&ws_n) || n.starts_with("/dev/null") || n.len() < 3 {
            continue;
        }
        // program paths (blender.exe, python) are what runs, not what it touches
        if m.start() == 0 || cmd[..m.start()].trim().is_empty() {
            continue;
        }
        if !out.contains(&p.to_string()) {
            out.push(p.to_string());
        }
    }
    out
}

/// A plain sentence for the most common programs; the model's own "why" is shown above it.
pub fn describe(cmd: &str) -> String {
    let words: Vec<&str> = cmd.split_whitespace().collect();
    let first = words.first().copied().unwrap_or("");
    let base = first.trim_matches('"').rsplit(['/', '\\']).next().unwrap_or(first);
    let prog = base.strip_suffix(".exe").or_else(|| base.strip_suffix(".EXE")).unwrap_or(base).to_ascii_lowercase();
    // split on both separators: a Windows path must read the same on any machine
    let last_name = |w: &str| w.trim_matches('"').rsplit(['/', '\\']).find(|x| !x.is_empty()).unwrap_or(w).to_string();
    let args: Vec<&str> = words.iter().skip(1).copied().filter(|w| !w.starts_with('-') && !w.starts_with('/')).collect();
    match prog.as_str() {
        "copy" | "cp" | "xcopy" | "robocopy" => match (args.first(), args.get(1)) {
            (Some(a), Some(b)) => format!("Copies {} to {}", last_name(a), last_name(b)),
            _ => "Copies files".into(),
        },
        "move" | "mv" | "ren" | "rename" => match (args.first(), args.get(1)) {
            (Some(a), Some(b)) => format!("Moves or renames {} to {}", last_name(a), last_name(b)),
            _ => "Moves files".into(),
        },
        "del" | "erase" | "rm" | "rmdir" | "rd" => format!("Deletes {}", args.iter().map(|a| last_name(a)).collect::<Vec<_>>().join(", ")),
        "mkdir" | "md" => "Creates a folder".into(),
        "blender" => {
            if let Some(i) = words.iter().position(|w| *w == "--python") {
                format!("Runs Blender in the background with the script {}", words.get(i + 1).map(|w| last_name(w)).unwrap_or_default())
            } else {
                "Runs Blender".into()
            }
        }
        "python" | "python3" | "py" => {
            if words.get(1) == Some(&"-c") {
                "Runs a short Python snippet".into()
            } else if words.get(1) == Some(&"-m") && words.get(2).is_some_and(|w| w.starts_with("pip")) {
                "Installs Python packages".into()
            } else {
                format!("Runs the Python script {}", args.first().map(|a| last_name(a)).unwrap_or_default())
            }
        }
        "ffmpeg" => "Makes or converts a video or image sequence with ffmpeg".into(),
        "magick" | "convert" => "Edits or converts images with ImageMagick".into(),
        "git" => format!("Uses git ({})", words.get(1).copied().unwrap_or("")),
        "pip" | "pip3" => "Installs Python packages".into(),
        "npm" | "pnpm" | "yarn" => "Installs or runs JavaScript packages".into(),
        "curl" | "wget" => "Downloads from the internet".into(),
        "ollama" => format!("Manages local AI models ({})", words.get(1).copied().unwrap_or("")),
        "dir" | "ls" | "type" | "cat" | "findstr" | "grep" | "where" => "Looks at files (read only)".into(),
        "" => "Runs nothing".into(),
        _ => format!("Runs the program {first}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn plain_words_and_levels() {
        let ws = Path::new(r"D:\loki\home\work\r1");
        let a = assess(r"copy D:\loki\home\work\renders\dungeon.png D:\loki\home\work\r1\renders\dungeon.png", ws);
        assert_eq!(a.what, "Copies dungeon.png to dungeon.png");
        assert_eq!(a.risk, Risk::Medium, "reads from outside the job folder");
        assert_eq!(a.outside, vec![r"D:\loki\home\work\renders\dungeon.png".to_string()]);
        let b = assess(r"copy renders\a.png out\a.png", ws);
        assert_eq!(b.risk, Risk::Low);
        assert_eq!(assess("rm -rf build", ws).risk, Risk::High);
        assert_eq!(assess("pip install pillow", ws).risk, Risk::Medium);
        assert!(assess("blender --background --python scripts/x.py", ws).what.contains("x.py"));
        assert_eq!(assess("r\u{200b}m -rf /", ws).risk, Risk::High, "invisible characters don't hide it");
    }
}
