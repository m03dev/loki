//! What the driver knows beyond the model: playbooks (how to do a kind of job well) and the lessons
//! notebook (rules learned from real errors, so the same mistake isn't made twice).

use std::path::{Path, PathBuf};

#[derive(Debug, Clone)]
pub struct Playbook {
    pub name: String,
    pub description: String,
    pub body: String,
}

#[derive(Debug, Clone, Default)]
pub struct Knowledge {
    pub playbooks: Vec<Playbook>,
    pub lessons_path: Option<PathBuf>,
}

/// Lessons every machine starts with: facts that crashed real jobs (2026-10-29/30 stress test).
pub const SEED_LESSONS: &[&str] = &[
    "Blender 5.2: the render engine is 'BLENDER_EEVEE' (BLENDER_EEVEE_NEXT does not exist).",
    "Blender 5.2: scene.eevee.use_gtao no longer exists - do not set it.",
    "Blender 5.2: circles are bpy.ops.mesh.primitive_circle_add(vertices=32, radius=r, fill_type='NGON').",
    "Blender scripts: build output paths from the script's folder (os.path.abspath(__file__)); '//' paths follow the .blend and land in the wrong folder.",
    "Blender scripts: place parts from the body's measured bounds so they touch; a lid placed by a guessed z floated 2.9 m above its chest.",
    "Camera framing: aim at the scene's bounds centre and keep every part the brief names inside the frame (torch flames were rendered out of view).",
    "Windows: python -c snippets need double quotes outside and single quotes inside.",
];

impl Knowledge {
    /// Load every playbooks/**/SKILL.md under `dir`, and the lessons file (seeded on first use).
    pub fn load(playbooks_dir: Option<&Path>, lessons_path: Option<&Path>) -> Self {
        let mut playbooks = Vec::new();
        if let Some(dir) = playbooks_dir {
            let mut stack = vec![dir.to_path_buf()];
            while let Some(d) = stack.pop() {
                for e in std::fs::read_dir(&d).into_iter().flatten().flatten() {
                    let p = e.path();
                    if p.is_dir() {
                        stack.push(p);
                    } else if p.file_name().is_some_and(|n| n == "SKILL.md") {
                        if let Ok(text) = std::fs::read_to_string(&p) {
                            playbooks.push(parse_playbook(&text));
                        }
                    }
                }
            }
        }
        playbooks.sort_by(|a, b| a.name.cmp(&b.name));
        if let Some(l) = lessons_path {
            if !l.exists() {
                let seed: String = SEED_LESSONS.iter().map(|s| format!("- {s}\n")).collect();
                let _ = std::fs::create_dir_all(l.parent().unwrap_or(Path::new(".")));
                let _ = std::fs::write(l, format!("# LOKI lessons - learned from real errors\n\n{seed}"));
            }
        }
        Self { playbooks, lessons_path: lessons_path.map(Path::to_path_buf) }
    }

    /// The playbooks that fit a goal best (at most `n`), by words shared with their name and description.
    pub fn pick(&self, goal: &str, n: usize) -> Vec<&Playbook> {
        let words = tokens(goal);
        let mut scored: Vec<(usize, &Playbook)> = self
            .playbooks
            .iter()
            .map(|p| {
                let mut s = tokens(&format!("{} {}", p.name.replace('-', " "), p.description)).iter().filter(|w| words.contains(w)).count();
                // the scripting playbook is the base for any Blender work
                let cad = words.iter().any(|w| matches!(w.as_str(), "cad" | "build123d" | "freecad"));
                if p.name == "cad-modeling" && cad {
                    s += 5;
                }
                if p.name == "blender-scripting" && !cad && words.iter().any(|w| matches!(w.as_str(), "blender" | "model" | "render" | "scene" | "prop" | "3d" | "low" | "poly" | "turntable")) {
                    s += 3;
                }
                (s, p)
            })
            .filter(|(s, _)| *s >= 2)
            .collect();
        scored.sort_by(|a, b| b.0.cmp(&a.0));
        scored.into_iter().take(n).map(|x| x.1).collect()
    }

    pub fn lessons(&self) -> Vec<String> {
        let Some(p) = &self.lessons_path else { return vec![] };
        std::fs::read_to_string(p)
            .unwrap_or_default()
            .lines()
            .filter_map(|l| l.strip_prefix("- ").map(|x| x.trim().to_string()))
            .filter(|l| !l.is_empty())
            .collect()
    }

    /// Lessons most related to the goal first, at most `n`.
    pub fn lessons_for(&self, goal: &str, n: usize) -> Vec<String> {
        let words = tokens(goal);
        let mut all: Vec<(usize, usize, String)> = self
            .lessons()
            .into_iter()
            .enumerate()
            .map(|(i, l)| (tokens(&l).iter().filter(|w| words.contains(w)).count(), i, l))
            .collect();
        all.sort_by(|a, b| b.0.cmp(&a.0).then(b.1.cmp(&a.1)));
        all.into_iter().take(n).map(|x| x.2).collect()
    }

    /// Add a lesson unless the notebook already says it. Returns false for a duplicate.
    pub fn learn(&self, lesson: &str) -> bool {
        let Some(p) = &self.lessons_path else { return false };
        let lesson = lesson.trim().replace('\n', " ");
        if lesson.len() < 12 {
            return false;
        }
        let norm = |s: &str| s.to_ascii_lowercase().chars().filter(|c| c.is_alphanumeric()).collect::<String>();
        let n = norm(&lesson);
        if self.lessons().iter().any(|l| norm(l) == n) {
            return false;
        }
        let mut lines = self.lessons();
        lines.push(lesson);
        let keep = &lines[lines.len().saturating_sub(200)..]; // the notebook stays small
        let body: String = keep.iter().map(|l| format!("- {l}\n")).collect();
        crate::journal::atomic_write(p, format!("# LOKI lessons - learned from real errors\n\n{body}").as_bytes()).is_ok()
    }
}

fn parse_playbook(text: &str) -> Playbook {
    let mut name = String::new();
    let mut description = String::new();
    let mut body = text;
    if let Some(rest) = text.strip_prefix("---") {
        if let Some(end) = rest.find("\n---") {
            for line in rest[..end].lines() {
                if let Some(v) = line.strip_prefix("name:") { name = v.trim().to_string(); }
                if let Some(v) = line.strip_prefix("description:") { description = v.trim().to_string(); }
            }
            body = &rest[end + 4..];
        }
    }
    Playbook { name, description, body: body.trim().to_string() }
}

fn tokens(s: &str) -> Vec<String> {
    const STOP: &[&str] = &["the", "and", "for", "with", "from", "that", "this", "into", "then", "make", "a", "an", "of", "to", "in", "on", "it", "is"];
    let mut v: Vec<String> = s
        .to_ascii_lowercase()
        .split(|c: char| !c.is_alphanumeric())
        .filter(|w| w.len() >= 2 && !STOP.contains(w))
        .map(|w| w.trim_end_matches('s').to_string())
        .collect();
    v.sort();
    v.dedup();
    v
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn picks_playbooks_and_keeps_lessons_unique() {
        let root = std::env::temp_dir().join(format!("lokiknow-{}", std::process::id()));
        let pb = root.join("playbooks/blender-scripting");
        std::fs::create_dir_all(&pb).unwrap();
        std::fs::write(pb.join("SKILL.md"), "---\nname: blender-scripting\ndescription: Build and render a prop with a Blender script\n---\nbody").unwrap();
        let vd = root.join("playbooks/video-director");
        std::fs::create_dir_all(&vd).unwrap();
        std::fs::write(vd.join("SKILL.md"), "---\nname: video-director\ndescription: Write a shot description for text-to-video\n---\nbody").unwrap();
        let k = Knowledge::load(Some(&root.join("playbooks")), Some(&root.join("lessons.md")));
        assert_eq!(k.pick("Model a low-poly treasure chest in Blender", 2)[0].name, "blender-scripting");
        assert!(k.pick("Write ad captions", 2).is_empty());
        assert_eq!(k.lessons().len(), SEED_LESSONS.len());
        assert!(k.learn("Blender 5.2: Bevel modifier width is in metres."));
        assert!(!k.learn("blender 5.2 - bevel modifier width is in metres"), "duplicate");
        assert!(k.lessons_for("blender bevel", 1)[0].contains("Bevel"));
        let _ = std::fs::remove_dir_all(root);
    }
}
