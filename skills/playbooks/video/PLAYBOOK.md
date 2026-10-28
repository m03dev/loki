---
name: video
title: Video clip
triggers: video, clip, animate, animation, animated, motion, shot, footage, trailer, teaser, reel, reels, tiktok, shorts, cinematic, camera move, dolly, pan, tracking shot, text to video, image to video, wan, make it move, loop, gif, b-roll, cutscene, storyboard, sequence of shots
specialists: Video Director, Concept Artist, Editor, Reviewer
---
# Video clip

## Purpose
Short video made by LOKI: one or more single-shot clips from Wan on the PC (text-to-video or image-to-video from an
approved still), optionally cut together with music or voice. Each shot is one continuous action with one camera
move. Done means: the shot list and every prompt were OK'd, each clip exists in videos/ at the asked shape, it was
watched frame by frame for artefacts, and an edit (if more than one shot) plays with sound in sync.

## Stages
```json
[
 {
  "id": "shotlist",
  "specialist": "Video Director",
  "objective": "Break the request into shots: one shot = one subject action + one camera move, 2-5 s each, with the order and the total length.",
  "output": "videos/<slug>/shotlist.md: per shot - number, length (s), shot size, camera move, action, light, start still (path or 'none')",
  "tools": ["library", "memory", "write_file"],
  "check": "no shot holds two actions or a cut; total length within 10% of the ask; each shot names its shot size (wide/medium/close) and one move (static, push-in, pull-out, pan, tilt, orbit, tracking, crane)",
  "gate": "",
  "writes": true,
  "depends_on": []
 },
 {
  "id": "keyframes",
  "specialist": "Concept Artist",
  "objective": "Make or pick a start still for each shot that needs one (image-to-video holds the look far better than text alone).",
  "output": "videos/<slug>/start-<n>.png per shot, at the clip's aspect",
  "tools": ["library", "make_image"],
  "check": "each still is at the clip aspect (16:9 or 9:16), the subject in its starting pose, the composition leaves room for the camera move; prompts OK'd by the owner",
  "gate": "owner",
  "writes": true,
  "depends_on": ["shotlist"]
 },
 {
  "id": "prompts",
  "specialist": "Video Director",
  "objective": "Write each shot as a Wan prompt: what the camera sees first, the action, the camera move, then light, lens look and style; plus the negative.",
  "output": "videos/<slug>/shot-<n>.prompt.txt (PROMPT, NEGATIVE, SECONDS, SIZE, START)",
  "tools": ["write_file"],
  "check": "60-120 words each; exactly one action verb chain and one camera verb; no on-screen text; no cut words (then, cut to, next scene); motion speed named (slow, steady, quick)",
  "gate": "",
  "writes": true,
  "depends_on": ["keyframes"]
 },
 {
  "id": "generate",
  "specialist": "Video Director",
  "objective": "Submit the prompts for the owner's OK, then render every shot on the PC, one at a time.",
  "output": "videos/<slug>/shot-<n>.mp4 per shot, with model, seed, frames, fps",
  "tools": ["make_video", "run_on_machine", "machine_job"],
  "check": "each file exists and plays; length matches SECONDS within 0.5 s; resolution and aspect as asked; nothing ran on the Mac's GPU",
  "gate": "owner",
  "writes": true,
  "depends_on": ["prompts"]
 },
 {
  "id": "review",
  "specialist": "Reviewer",
  "objective": "Watch each clip and step through it: identity drift, morphing hands and faces, flicker, frozen frames, wrong camera move, physics.",
  "output": "videos/<slug>/review.md: per shot KEEP or REDO with the timestamp and the defect",
  "tools": ["bash", "read_file"],
  "check": "frames sampled at least every 0.5 s (ffmpeg to a contact sheet) and looked at; each REDO names one change for the retry (max 3 per shot)",
  "gate": "",
  "writes": true,
  "depends_on": ["generate"]
 },
 {
  "id": "edit",
  "specialist": "Editor",
  "objective": "Cut the kept shots in order, add music or voice when asked, normalise loudness, and export the delivery file.",
  "output": "videos/<slug>/<slug>-final.mp4 (H.264, yuv420p, AAC) and the edit list",
  "tools": ["bash", "make_music", "voice", "library"],
  "check": "plays start to end; cuts land on action or beat; audio peaks below -1 dBTP and loudness near -14 LUFS for web; aspect and fps consistent across shots",
  "gate": "owner",
  "writes": true,
  "depends_on": ["review"]
 }
]
```

## Questions
```json
[
 {
  "header": "Length",
  "question": "How long should it be?",
  "multi": false,
  "options": [
    {"label": "5 seconds", "description": "One shot"},
    {"label": "10-15 seconds", "description": "Two or three shots cut together"},
    {"label": "30 seconds", "description": "A short trailer, 6-8 shots"}
  ],
  "skip_if": "(?i)\\b\\d+\\s*(s|sec|secs|seconds|minutes?)\\b"
 },
 {
  "header": "Shape",
  "question": "Which shape?",
  "multi": false,
  "options": [
    {"label": "16:9", "description": "Wide - YouTube, trailers"},
    {"label": "9:16", "description": "Tall - TikTok, Reels, Shorts"},
    {"label": "1:1", "description": "Square - feeds"}
  ],
  "skip_if": "(?i)\\b(\\d{1,2}:\\d{1,2}|vertical|tiktok|reels|shorts|widescreen|square)\\b"
 },
 {
  "header": "Start from",
  "question": "What should the clip start from?",
  "multi": false,
  "options": [
    {"label": "A still first", "description": "Make or pick a picture, then animate it - steadier look"},
    {"label": "Text only", "description": "Straight from the description - faster, less control"},
    {"label": "A 3D model", "description": "Turntable or render of a model in the library"}
  ],
  "skip_if": "(?i)(images/|\\.png|\\.jpe?g|this (picture|image)|from text|models/|\\.glb|turntable)"
 },
 {
  "header": "Sound",
  "question": "Should it have sound?",
  "multi": false,
  "options": [
    {"label": "Music", "description": "A track made to fit"},
    {"label": "Voice-over", "description": "A narrator line"},
    {"label": "Silent", "description": "No sound"}
  ],
  "skip_if": "(?i)\\b(music|soundtrack|voice.?over|narrat\\w+|silent|no sound)\\b"
 }
]
```

## Checklist
- One shot = one continuous action and one camera move; no cuts inside a shot.
- Each shot 2-5 s (Wan holds coherence best at or under ~5 s; frame count 4n+1, e.g. 81 frames at 16 fps).
- Prompt order: what the camera sees first, the action, the camera move, then light, lens look, colour, style.
- Camera vocabulary is explicit: push-in/pull-out (dolly), pan left/right, tilt up/down, orbit, tracking, crane up; speed stated.
- Shot size stated: wide, medium, close-up; lens look (24 mm wide, 50 mm, 85 mm).
- Light direction and quality stated and consistent across shots of one scene.
- Image-to-video used when identity or style must hold; the start still at the clip's aspect.
- Negative covers: static frame, flicker, morphing, extra limbs, deformed hands, text, watermark, low quality.
- Every prompt and every start still OK'd by the owner before rendering.
- Rendered on the PC one job at a time; test renders at low resolution before the final size.
- Each clip watched and stepped through; defects named with timestamps.
- Retakes change one thing (seed, motion words, start still) and stop after 3.
- Edit: consistent fps and aspect, cuts on motion or the beat, no black frames at the head or tail.
- Audio: web delivery around -14 LUFS integrated, true peak below -1 dBTP; voice above music by ~10 dB.
- Delivery: H.264 MP4, yuv420p, AAC 48 kHz; plays in a browser.
- No words on screen unless asked (and then added in the edit, not generated).

## Quality bar
- Great: the subject keeps its identity across the whole clip (same face, same costume, same colours) - 0 visible morphs.
- Great: the camera move is the one asked and stays smooth (no jitter, no direction change).
- Great: motion has weight - feet plant, cloth follows - and nothing slides or melts.
- Great: 1 of every 2 renders is a keeper; if fewer than 1 in 4, the prompt or the still is wrong, not the seed.
- Great edits: shots cut on action, the first second hooks (movement or reveal), the last frame holds 0.5-1 s.
- Acceptable clips look fine at speed; great ones survive stepping frame by frame.

## Failure modes
- The clip is almost static -> name a strong, concrete action verb and a camera move with speed; for image-to-video, leave room in the still for the move.
- Two actions blur into mush -> one action per shot; split the idea into two shots and cut.
- Face or costume drifts mid-clip -> start from an approved still (image-to-video), shorten to 3-4 s, reduce motion strength.
- Hands and fingers morph -> keep hands simple and partly out of frame, avoid hand-centred actions, close-ups on faces instead.
- Camera does the wrong move -> one camera verb only, put it right after the action, remove competing words (orbit and pan together).
- Flicker or boiling textures -> fewer steps on a distilled model is fine but raise them on the full model; lower the resolution for the test, keep the final at 720p.
- PC runs out of VRAM (8 GB) -> 480p-ish test renders, fewer frames, a GGUF/quantised model, ComfyUI low-VRAM mode; one job at a time.
- Text or captions appear in the frame -> add text, subtitles, watermark to the negative; add any wanted text in the edit.
- Shots do not match in colour -> same light words and grade words in every prompt; match colour in the edit.
- Audio clipping or too quiet -> normalise loudness in the edit (ffmpeg loudnorm to -14 LUFS, -1 dBTP).
- Video does not play on the phone -> re-encode H.264 yuv420p with faststart.
- The generate step tried to run on the Mac -> route to the PC with run_on_machine; the Mac only plays results.

## Hand-off
Beyond the constitution's block: the shot list, per shot the prompt file, start still, model, seed, frames and fps,
KEEP/REDO verdict with timestamps, the final edit path with duration, resolution, fps and loudness reading, and the
music/voice files used.

## Tools
- library kind=images|videos|music|voice: reuse stills, clips, tracks and voice lines before making new.
- make_image prompt= width= height= (16:9 1280x720 / 9:16 720x1280): start stills; the owner OKs the prompt.
- make_video prompt= seconds=2-5 image=<start still>: Wan on the PC; image= for image-to-video.
- make_music tags= seconds= bpm=: a track cut to the edit length.
- voice action=speak text= voice= instruct=narrator: a voice-over WAV.
- bash: ffmpeg for contact sheets (fps=2 tile), concatenation, loudnorm, and H.264 export.
- run_on_machine machine=pc / machine_job wait=: render jobs on the PC and collect them.
- render_scene model= frames=48 prompt=: a turntable video of a 3D model instead of text-to-video.

## References
- LOKI video-director specialist - skills/art-pipeline/video-director/SKILL.md
- Wan 2.2, what's new and how to write prompts (structure, camera verbs, length, fps) - https://www.instasd.com/post/wan2-2-whats-new-and-how-to-write-killer-prompts
- Wan 2.2 prompting guide (image-to-video) - https://dhl.veed.io/learn/wan-2-2-prompting-guide
- Wan 2.2 I2V on an 8 GB card in ComfyUI (low-VRAM settings) - https://lilting.ch/en/articles/wan22-comfyui-rtx4060-i2v
- EBU R 128 loudness - https://en.wikipedia.org/wiki/EBU_R_128
- LOKI AI renderer notes (Wan VACE on the PC, frame counts in steps of 4) - docs/AI_RENDERER.md
