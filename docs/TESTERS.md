# Testing LOKI - a page for friends

Thank you for trying LOKI. This page tells you what it is, how to install it in three steps, what to
try, and how to tell us what went wrong. You need no terminal, no Python and no account.

## What LOKI is

LOKI is a free, open-source (AGPL-3.0) AI helper for your own computer, for Windows and macOS. You
talk to it in your own words: it answers questions, writes and explains things, works with your
documents and spreadsheets, makes pictures, runs tasks in the background and can automate things.
It can think **on your computer** (free and private, works offline) or with a **free online account**,
or both. It always asks before it does anything risky on your computer.

It is early software: some things will break. That is exactly what we want to hear about.

## Install it (3 steps)

Get the files from the **Releases** page: https://github.com/m03dev/loki/releases/latest
(or the zip someone sent you).

### Windows 10 / 11

1. Download **Loki-Setup-<version>.exe** and open it. Windows may say **"Windows protected your PC"**
   (LOKI is not code-signed yet): click **More info**, then **Run anyway**.
2. Click through the installer. It needs no admin password and installs only for you. LOKI's own
   Python is inside: nothing else is downloaded.
3. LOKI opens. The welcome tour asks how LOKI should think (see below).

No installer wanted? Download **Loki-<version>-windows-portable.zip**, unzip it anywhere and
double-click **Loki.exe**.

### macOS 11 or newer

1. Download **Loki-<version>.dmg** (Apple Silicon; there is an `-intel` one for older Macs), open it
   and drag **LOKI** onto **Applications**.
2. The first time only: in Applications, **right-click LOKI > Open**, then **Open** again. (macOS asks
   because LOKI is not notarized by Apple yet. If it says the app "is damaged", open Terminal once and
   run `xattr -dr com.apple.quarantine /Applications/Loki.app`, then open it again.)
3. LOKI opens. The welcome tour asks how LOKI should think.

### The welcome tour

- **Run AI on this computer (free, private)** - LOKI looks at your computer, picks a model that fits
  (a quick one first, usually Bonsai 2: a 1-3 GB download), installs Ollama for you quietly, and
  downloads it **in the background**. A small card at the bottom right shows the progress; you can
  keep going.
- **Connect an account** - one click with OpenRouter (sign in in your browser, approve LOKI), or paste
  a free key: **NVIDIA NIM** (DeepSeek V4.1 Flash - LOKI's favourite, free at build.nvidia.com),
  Groq or Google Gemini. Keys stay on your computer.
- **Both** - chat online right away while the local model downloads.

Every step can be skipped. You can change all of it later in **Settings**.

## What to try (15 minutes)

1. Ask something real: "Plan my meals for the week, I'm vegetarian", "Explain this bill" (paste it),
   "Write a polite email to my landlord about the heating".
2. Drop a PDF or a spreadsheet into the chat and ask about it.
3. Open the grid icon (**What can LOKI do?**) and run two examples.
4. If you chose a local model: when the card says it is done, ask the same question again - now it
   answers without the internet.
5. Close LOKI and open it again: how long until the window appears? Until it answers?
6. Try **Settings** (the gear): change the language or the text size.

## Tell us what happened

The easiest way: **Settings > General > Send feedback**. Write what happened, then:

- **Open a GitHub issue** - LOKI saves a small file (`LOKI-feedback-<date>.zip`, on your Desktop),
  shows it, and opens a new issue page with your note filled in. Drag the file into the issue and
  press **Submit** (a free GitHub account is needed).
- **Write an email** - the same file, with an email draft to attach it to.

What is in the file: LOKI's own log files (with every key, token, e-mail address and your home folder
name removed), the LOKI version, your OS and how much memory the computer has. **Never** in it: your
keys, your chats, LOKI's memory, your files, the settings file. You can open the zip and look before
you send it.

If LOKI does not open at all, send us these files by hand (they contain no keys):
- Windows: `%LOCALAPPDATA%\Loki\app\launcher.log` and `loki_app.log`
- macOS: `~/Library/Application Support/Loki/app/launcher.log` and `loki_app.log`

Useful things to mention: Windows or Mac (and which chip), what you clicked, what you expected, what
happened instead, and a screenshot.

## Remove it

- Windows: Settings > Apps > LOKI > Uninstall (or just delete the portable folder).
- macOS: drag LOKI from Applications to the Trash.

Your chats, settings and models stay in `%LOCALAPPDATA%\Loki` (Windows) or
`~/Library/Application Support/Loki` (macOS) - delete that folder to remove everything.
Ollama (if LOKI installed it) is its own app: uninstall it the same way.

---

## For the owner: making the friends kit

    python tools/make_release.py --friends

builds from the **last commit** only (`git archive HEAD`: tracked files, nothing from `harness_data`,
no `.env`), runs the secret scan (it refuses to package anything key-like and lists what it found),
and writes into `dist/`:

- `Loki-<v>-<os>-portable.zip` for the computer you run it on - with LOKI's Python inside when
  `dist/runtime` exists (`python tools/bundle_runtime.py`, or add `--bundle-runtime`; needs `uv` on
  your computer and the internet once). On a Mac with Xcode tools it zips a real `LOKI.app`.
- `release/Loki-<v>.zip` + `manifest.json` - the update zip installed copies download (not for people).
- `FRIENDS.txt` - what to send, sizes, sha256, and a warning if you have uncommitted changes.

The Windows installer and the macOS `.dmg` are built by GitHub Actions: push a tag (`git tag v0.17.0`,
`git push origin v0.17.0` - through the owner, not an agent) or run **Actions > Installers > Run
workflow**. A tag also publishes the GitHub Release (docs/INSTALL.md "Publishing a release").
