---
name: music
title: Music and sound
triggers: music, song, track, soundtrack, score, theme music, background music, bgm, loop, jingle, beat, instrumental, lyrics, vocals, sing, singing, melody, chiptune, orchestral, lofi, lo-fi, synthwave, ambient, battle theme, menu music, boss music, ace-step, compose, composer, sound effect, sfx, voice line, voice-over, narration, audio
specialists: Composer, Lyricist, Editor, Reviewer
---
# Music and sound

## Purpose
Original music (and, when asked, voice lines or sound effects) made by LOKI: ACE-Step on the PC's ComfyUI for music,
VoiceStudio for voices, the Tool Shelf for effects. Done means: a short music brief, tags and lyrics the owner OK'd,
2-3 takes generated, the best one picked by listening against the brief, trimmed or looped cleanly, loudness
normalised for its use, and saved in audio/ with its tags, seed, bpm and key.

## Stages
```json
[
 {
  "id": "brief",
  "specialist": "Composer",
  "objective": "Define the cue: where it plays, mood arc, genre, tempo, key, length, vocals or instrumental, and loop or one-shot.",
  "output": "audio/<slug>/brief.md: use (menu, battle, trailer, ambience), mood, one primary genre + one modifier, bpm, key, seconds, vocals yes/no, loop yes/no, reference tracks from the library",
  "tools": ["library", "memory", "read_file"],
  "check": "bpm fits the genre range (ballad 60-80, lo-fi 70-90, pop 100-120, house 120-128, techno 128-140, drum and bass 170-180); length matches the use (loop 30-90 s, trailer cue to the edit length)",
  "gate": "",
  "writes": true,
  "depends_on": []
 },
 {
  "id": "write",
  "specialist": "Lyricist",
  "objective": "Write the tags and, for vocal tracks, the structured lyrics.",
  "output": "audio/<slug>/prompt.txt: TAGS (5-12 comma-separated: genre, mood, 2-3 instruments, vocal type, production, bpm), LYRICS with [intro] [verse] [chorus] [bridge] [outro] markers, BPM, KEY, SECONDS",
  "tools": ["write_file"],
  "check": "tags are keywords, not prose; no contradictions (lo-fi and hi-fi, calm and aggressive); lyric lines about 4-8 syllables; every [chorus] has text or is relabelled [inst]; instrumental tracks use section markers only, no lyric text",
  "gate": "",
  "writes": true,
  "depends_on": ["brief"]
 },
 {
  "id": "generate",
  "specialist": "Composer",
  "objective": "Submit tags and lyrics for the owner's OK, then generate 2-3 takes on the PC with different seeds.",
  "output": "audio/<slug>-<seed>.mp3 (2-3 files) with tags, bpm, key, seed, seconds",
  "tools": ["make_music", "run_on_machine", "machine_job"],
  "check": "files exist and play; length within 2 s of the ask; run on the PC's ComfyUI; the approved prompt used unchanged",
  "gate": "owner",
  "writes": true,
  "depends_on": ["write"]
 },
 {
  "id": "listen",
  "specialist": "Reviewer",
  "objective": "Listen to each take against the brief and pick one: genre, mood, tempo felt, vocal intelligibility, artefacts.",
  "output": "audio/<slug>/review.md: per take KEEP/REDO with timestamps of problems (warble, mumbled words, abrupt end, clipping)",
  "tools": ["bash", "read_file"],
  "check": "measured bpm and loudness with ffmpeg/ebur128 recorded; a REDO changes one thing (tags, bpm, seed, lyrics) and stops after 3 rounds",
  "gate": "",
  "writes": true,
  "depends_on": ["generate"]
 },
 {
  "id": "finish",
  "specialist": "Editor",
  "objective": "Trim, fade or make the loop seamless, normalise loudness for the use, and export the delivery files.",
  "output": "audio/<slug>-final.ogg/.mp3/.wav (+ <slug>-loop.ogg for game loops)",
  "tools": ["bash", "toolshelf"],
  "check": "loop point on a bar line with no click (crossfade a few ms); loudness around -14 LUFS for web/trailers, about -16 to -18 LUFS for in-game music beds; true peak below -1 dBTP; game loops exported as OGG",
  "gate": "",
  "writes": true,
  "depends_on": ["listen"]
 },
 {
  "id": "deliver",
  "specialist": "Composer",
  "objective": "Hand over the final files with their metadata and where they fit (video edit, game scene).",
  "output": "the hand-off block with paths, bpm, key, loudness reading and loop points",
  "tools": ["library"],
  "check": "final files show in the library with their tags; the report states measured loudness and length",
  "gate": "owner",
  "writes": false,
  "depends_on": ["finish"]
 }
]
```

## Questions
```json
[
 {
  "header": "Use",
  "question": "Where will the music play?",
  "multi": false,
  "options": [
    {"label": "Game loop", "description": "Menu or level music that loops seamlessly"},
    {"label": "Trailer / video", "description": "Cut to a video's length"},
    {"label": "Song", "description": "A full song with vocals"},
    {"label": "Sound effect", "description": "A short effect or voice line"}
  ],
  "skip_if": "(?i)\\b(loop|menu|level|battle|boss|trailer|video|song with|vocals|sfx|sound effect|voice line)\\b"
 },
 {
  "header": "Genre",
  "question": "Which style?",
  "multi": false,
  "options": [
    {"label": "Orchestral", "description": "Strings, brass, percussion - epic or gentle"},
    {"label": "Electronic", "description": "Synthwave, house, ambient"},
    {"label": "Chiptune", "description": "8/16-bit retro game sound"},
    {"label": "Lo-fi / acoustic", "description": "Warm, relaxed, live instruments"}
  ],
  "skip_if": "(?i)\\b(orchestral|cinematic|synth\\w*|electronic|house|techno|ambient|chiptune|8.?bit|16.?bit|lo.?fi|acoustic|rock|metal|jazz|folk|hip.?hop|pop)\\b"
 },
 {
  "header": "Vocals",
  "question": "Vocals or instrumental?",
  "multi": false,
  "options": [
    {"label": "Instrumental", "description": "No singing"},
    {"label": "With vocals", "description": "Lyrics sung - I give or approve them"}
  ],
  "skip_if": "(?i)\\b(instrumental|no vocals|vocals|lyrics|sung|singing|choir)\\b"
 }
]
```

## Checklist
- Brief states use, mood, one primary genre (+ one modifier), bpm, key, length, vocals, loop.
- Tags: 5-12 comma-separated keywords, genre first, then mood, 2-3 named instruments, vocal type, production, bpm.
- No contradictory tags; no "no vocals" tag together with lyric text.
- bpm set in the tags and in the bpm argument; inside the genre's usual range.
- Lyrics in lowercase square-bracket sections; lines about 4-8 syllables; a language marker at the start of a section for non-English.
- Instrumental tracks: section markers only (e.g. [intro] [inst] [build-up] [drop] [outro]).
- Tags and lyrics OK'd by the owner before generating.
- Generation ran on the PC's ComfyUI; the Mac only played the results.
- 2-3 takes with different seeds; the pick has a stated reason.
- Measured bpm and integrated loudness recorded.
- Loops cut on a bar line, seamless when played twice in a row, no click.
- Loudness: about -14 LUFS for web/trailers; quieter beds for in-game; true peak below -1 dBTP.
- Fades: 1-3 s fade-out for one-shots and trailer ends; no fade on loops.
- Game delivery as OGG (loops) plus WAV master; web delivery MP3/AAC.
- Voice lines: voice cloning only with the person's permission; captions (.srt) when the line goes in a video.
- Files saved in audio/ with tags, seed, bpm, key and length recorded.

## Quality bar
- Great: the mood is right within the first 5 seconds; the genre is unmistakable.
- Great loops: you cannot hear the seam after 3 repeats.
- Great vocals: every lyric word intelligible on the first listen; no warbling sustained notes.
- Great: the track sits under dialogue and sound effects in a game without masking them (no constant mid-range wall).
- Great: 1 keeper in 3 takes; if 0 of 3, change the tags (not only the seed).
- Acceptable music fits the genre; great music fits the moment it is made for.

## Failure modes
- Muddy, genre-less result -> one primary genre plus one modifier, name concrete instruments, remove adjectives that conflict.
- Prose prompts give weak results -> rewrite as a keyword list in the order genre, mood, instruments, vocals, production, bpm.
- Tempo feels wrong -> put the bpm in tags and in the bpm argument; pick a value inside the genre range.
- Vocals mumble or words are lost -> shorter lines (4-8 syllables), simple words, a clear [verse]/[chorus] structure; male/female voice named in tags.
- Singing appears in an instrumental -> no lyric text at all; section markers only; add "instrumental" to tags.
- Empty [chorus] produces garbage -> give it text or relabel it [inst].
- The track loses coherence after a few minutes -> keep game loops 30-90 s and longer songs to about 3 minutes; build longer pieces from sections.
- Loop clicks or jumps -> cut on a bar boundary (60/bpm x 4 seconds per 4/4 bar), crossfade a few ms, test by looping 3 times.
- Clipping or too loud next to other audio -> normalise with ffmpeg loudnorm (I=-14, TP=-1) or the in-game target; check the peak afterwards.
- ComfyUI on the PC busy or out of VRAM -> one job at a time; shorter seconds; retry after the running job finishes; never run it on the Mac.
- Cloned voice without consent -> never; use a designed voice (voice action=design) instead.

## Hand-off
Beyond the constitution's block: the approved tags and lyrics file, the takes with seeds and verdicts, the final files
with length, measured bpm, key, integrated loudness and true peak, loop start/end in seconds, and where it is meant
to go (the video edit, the game scene).

## Tools
- library kind=music|voice|audio: reuse or extend earlier tracks and voices.
- make_music tags= lyrics= seconds=10-240 bpm= key= language= seed=: ACE-Step on the PC's ComfyUI; saves an MP3 in audio/.
- voice action=speak text= voice= instruct= | design name= description= | transcribe audio= srt=true: voice lines, designed voices, captions.
- toolshelf action=list area=audio / run id=: sound effects and audio tools installed on request (asks the owner first).
- bash: ffmpeg for trimming, fades, loudnorm, ebur128 measurement, loop tests and format export.
- run_on_machine machine=pc / machine_job: generation jobs on the PC when called from the Mac.
- write_file: brief.md, prompt.txt and review.md under audio/<slug>/.

## References
- ACE-Step 1.5 prompting guide (tags, structure tags, bpm ranges, failures) - https://deapi.ai/blog/ace-step-1-5-prompting-guide-how-to-write-tags-structure-lyrics-and-generate-better-music
- ComfyUI ACE-Step tutorial (tags, lyrics markers, language codes) - https://docs.comfy.org/tutorials/audio/ace-step/ace-step-v1
- ACE-Step songwriting skill - https://skills.sh/ace-step/ace-step-1.5/acestep-songwriting
- EBU R 128 loudness - https://en.wikipedia.org/wiki/EBU_R_128
