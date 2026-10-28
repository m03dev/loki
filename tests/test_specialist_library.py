"""Premade specialists and real references per task (engine/specialist_library.py; owner 2026-10-28: "the prompt agent is
bad, needs improvement depending on the task, needs real ref ... we need premade, just add them to loki").

Checks, on small copies of the real library layouts (wshobson/agents, VoltAgent subagents, the YouMind galleries,
f/awesome-chatgpt-prompts, Wan2.2's system_prompt.py): the task kind is read; a FastAPI goal finds the FastAPI agent
in both layouts, a social ad the social agent; a picture card gets real reference prompts with their pictures and the
expert's brief carries them; a video card gets Wan's own rules; the card keeps the references for the UI; a team's
Builder gets the matching premade agent; a failed expert run is tried again later; the downloader fetches single
files raw and keeps a top-level LICENSE.

    python tests/test_specialist_library.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
DATA = Path(tempfile.mkdtemp(prefix="loki-plib-"))
V = DATA / "vendor"


def w(rel: str, text: str) -> None:
    p = V / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


w("wshobson-agents/plugins/python-development/agents/fastapi-pro.md",
  "---\nname: fastapi-pro\ndescription: Build high-performance async APIs with FastAPI and Pydantic.\nmodel: opus\n---\n"
  "You are a FastAPI expert.\n\n## Capabilities\n- Dependency injection\n")
w("wshobson-agents/plugins/python-development/skills/fastapi-templates/SKILL.md",
  "---\nname: fastapi-templates\ndescription: Production FastAPI project templates.\n---\n# FastAPI templates\n")
w("wshobson-agents/plugins/social-publishing/agents/social-publisher.md",
  "---\nname: social-publisher\ndescription: Plan and write social media posts and short video ads for TikTok and "
  "Instagram.\n---\nYou publish social content.\n")
w("voltagent-subagents/categories/02-language-specialists/rust-engineer.md",
  "---\nname: rust-engineer\ndescription: \"Use this agent for Rust systems programming and memory safety.\"\n"
  "tools: Read, Write\n---\nYou are a senior Rust engineer.\n")
w("voltagent-subagents/categories/02-language-specialists/README.md", "# not an agent\n")
img = "https://cms-assets.example/media/1_golem.jpg"
w("nano-banana-prompts/README.md", """# gallery

### No. 1: Game Asset - Painterly moss creature concept

#### 📖 Description

A painterly creature concept.

#### 📝 Prompt

```
A hulking moss-covered stone creature with glowing amber eyes, painterly fantasy concept art, three-quarter view,
soft rim light from the left, muted greens with {argument name="accent" default="amber"} accents, plain grey background
```

#### 🖼️ Generated Images

<img src="%s" width="700" alt="x">

#### 📌 Details

- **Author:** [Ana](https://x.com/ana)
- **Source:** [Twitter Post](https://x.com/ana/status/1)

### No. 2: 中文提示

#### 📝 Prompt

```
一张水墨风格的山水画，远山近水，云雾缭绕，留白构图，宣纸质感，淡墨渲染，意境深远，传统中国画风格，细腻笔触
```
""" % img)
w("chatgpt-prompts/prompts.csv", 'act,prompt,for_devs,type,contributor\n'
  '"Technical Blog Writer","I want you to act as a technical blog writer. Write clear blog posts with examples.",'
  'FALSE,TEXT,x\n"Isometric Diorama","A tiny isometric 3D diorama of a city block, soft studio light.",FALSE,IMAGE,y\n')
w("wan-prompts/wan/utils/system_prompt.py",
  'T2V_A14B_EN_SYS_PROMPT = \\\n    """You are a film director. Add camera and light details. Output English."""\n'
  'I2V_A14B_EN_SYS_PROMPT = "Describe the motion of the given image."\nimport os\nos.system("echo never run")\n')
for lib in ("wshobson-agents", "voltagent-subagents", "nano-banana-prompts", "chatgpt-prompts", "wan-prompts"):
    w(lib + "/.loki_sync.json", "{}")
os.environ["LOKI_DATA"] = str(DATA)
os.environ["LOKI_OWNER_REVIEW"] = "on"

import specialist_library as P  # noqa: E402
import prompt_expert  # noqa: E402
import team  # noqa: E402

PASS: list = []
FAIL: list = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else "  <- %s" % (str(detail)[:300],)))


check("the task kind is read", [P.kind(x) for x in (
    "concept art of a golem", "T-pose turnaround of a fox", "a 5s video of a dragon", "retopologize the golem mesh",
    "fix the python script", "a TikTok ad for launch", "write a blog post")] ==
      ["image", "turnaround", "video", "3d", "code", "marketing", "writing"])
names = {d["name"] for d in P.catalog()}
check("agents and skills of both layouts are in the catalog (READMEs are not)",
      {"fastapi-pro", "fastapi-templates", "rust-engineer", "social-publisher"} <= names and "README" not in names
      and "concept-artist" in names, sorted(names)[:20])
f = P.for_task("write a FastAPI endpoint for uploads")
check("a FastAPI goal finds the FastAPI agent and skill", f["agents"] and f["agents"][0]["name"] == "fastapi-pro"
      and f["skills"][0]["name"] == "fastapi-templates", f)
check("a Rust goal finds VoltAgent's Rust engineer", P.best_specialists("port the sculpt module to Rust", 1, "agent")[0]
      ["name"] == "rust-engineer")
check("a social ad finds the social agent", P.for_task("make a TikTok ad for the app")["agents"][0]["name"] ==
      "social-publisher")
check("an agent's text has no frontmatter or tool list", "tools:" not in P.specialist_text(P.find("rust-engineer"))
      and P.specialist_text(P.find("rust-engineer")).startswith("You are a senior Rust engineer"))

refs = P.image_refs("concept art of a moss golem", 3, "image")
check("a picture task gets the real reference prompt with its picture, author and source",
      refs and refs[0]["images"] == [img] and refs[0]["author"] == "Ana" and "amber accents" in refs[0]["prompt"]
      and "{argument" not in refs[0]["prompt"], refs[:1])
check("prompts the image models cannot read well (Chinese-only) are left out",
      all("水墨" not in r["prompt"] for r in P._build_images()))
check("a text task gets a role prompt", (P.role_prompt("write a technical blog post about rendering") or {})
      .get("act") == "Technical Blog Writer")
check("Wan's own video rules are read without running the file", P.video_rules().startswith("You are a film director")
      and P.video_rules(True).startswith("Describe the motion"))

card = {"id": "c1", "kind": "prompt", "tool": "make_image", "stage": "concept", "who": "Concept Artist",
        "args": {"prompt": "a moss golem guardian, painterly"}}
b = prompt_expert.brief(card)
check("the expert's brief carries the real reference prompt", "Real prompts that made great pictures" in b
      and "glowing amber eyes" in b, b[-500:])
vs = prompt_expert.system_for({"tool": "make_video", "stage": "video", "args": {"prompt": "a dragon flying"}})
check("a video card is written with Wan's own rules", "You are a film director" in vs and '"prompt"' in vs, vs[-300:])
out = prompt_expert.improve(card, lambda s, u: ('{"prompt": "A hulking moss golem of stacked river stones, three-'
                                                'quarter view, soft rim light", "why": "added shapes"}', "fake"))
check("the rewrite keeps the references (title + picture) for the card", out["refs"] and out["refs"][0]["image"] == img
      and out["by"] == "fake", out)
check("the strongest free writer is tried first", prompt_expert.EXPERT_MODELS[0] == "nvidia-pro"
      and prompt_expert.EXPERT_MODELS[-1] == "local")

tb = team._with_playbook("builder", "Implement the plan.", "write a FastAPI endpoint for uploading renders")
check("a team's Builder gets the matching premade agent", "premade agent 'fastapi-pro'" in tb and
      tb.startswith("Implement the plan."), tb[:300])
check("an art role keeps its own skill (no premade coder)", "premade agent" not in
      team._with_playbook("art_concept", "Draw it.", "concept art of a golem"))

# a failed Prompt Expert run is tried again after a while (it used to stay on the agent's words for good)
import owner_review  # noqa: E402
calls = []
owner_review.EXPERT_ASK["ask"] = lambda s, u: (calls.append(1), ('{"prompt": "A hulking moss golem of stacked river '
                                                                  'stones, soft rim light", "why": "x"}', "fake"))[1]
try:
    item = owner_review.queue("prompt", "make_image", {"prompt": "a lantern"}, str(DATA), who="Concept Artist")
except Exception as exc:  # noqa: BLE001
    item = None
    print("  (submit unavailable: %s)" % exc)
check("a test card could be queued", bool(item))
if item:
    it = owner_review.get(item["id"])
    it["expert"] = {"status": "failed", "error": "timeout", "t": time.time() - owner_review.EXPERT_STALE_S - 5}
    owner_review._save(it)  # pylint: disable=protected-access
    owner_review.kick_expert(thread=False)
    check("a failed expert run is tried again later", (owner_review.get(item["id"])["expert"] or {}).get("status")
          == "done" and calls, owner_review.get(item["id"]).get("expert"))

import ecc_sync  # noqa: E402
fetched = []


class _R:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_open(req, timeout=0):
    url = req.full_url
    fetched.append(url)
    if "/main/" in url and "missing" not in url:
        return _R(b"ok")
    raise OSError("404")


ecc_sync.urllib.request.urlopen = fake_open
tgt = DATA / "rawtest"
n = ecc_sync._fetch_raw("a/b", ("prompts.csv", "missing-LICENSE"), tgt)  # pylint: disable=protected-access
check("single files come straight from raw.githubusercontent.com (no 200 MB zip)", n == 1 and
      (tgt / "prompts.csv").read_bytes() == b"ok" and fetched[0].startswith("https://raw.githubusercontent.com/a/b/main/"))
check("the new libraries are registered for download",
      {"wshobson-agents", "voltagent-subagents", "nano-banana-prompts", "chatgpt-prompts", "wan-prompts"} <=
      set(ecc_sync.SOURCES))

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
