# Installing LOKI (for everyone)

This page is for people who want to **use** LOKI. Developers who work on LOKI itself use a git
checkout and `setup.sh` / `setup.bat` instead (see README.md).

## What you need

- **Windows 10 or 11** (64-bit) or **macOS 11 or newer** (Apple Silicon or Intel).
- About **2 GB** of free disk for LOKI itself, plus 5-10 GB if you want a model on your computer.
- **Internet the first time** (LOKI downloads its own Python, a few minutes, once). After that it can
  work fully offline with a local model.
- No Python, no Homebrew, no admin rights, no account. A free account is only needed if you choose a
  free online model.

## Windows

1. Download **Loki-Setup-<version>.exe** and open it.
   - Windows may say "Windows protected your PC" while the installer is not code-signed yet:
     press **More info > Run anyway**.
2. Click through the installer. It installs for **you only** (no admin password) into
   `%LOCALAPPDATA%\Programs\Loki`, then downloads LOKI's Python and packages (a few minutes).
3. LOKI opens. The welcome tour helps you pick a language and connect a free model.

Open it later from the **Start menu > LOKI** (or the desktop icon).

**Uninstall:** Settings > Apps > LOKI > Uninstall. Your chats, settings and keys stay in
`%LOCALAPPDATA%\Loki`; delete that folder to remove everything.

## macOS

1. Download **Loki-<version>.dmg**, open it and drag **LOKI** to **Applications**.
2. Open LOKI from Applications.
   - If macOS says it "cannot be opened because the developer cannot be verified" (an unsigned
     build), **right-click LOKI > Open > Open** once.
3. The first start sets LOKI up (a notification says so; a few minutes, needs the internet),
   then the window opens with the welcome tour.

**Uninstall:** drag LOKI from Applications to the Trash. Your data stays in
`~/Library/Application Support/Loki`; delete that folder to remove everything.

## The first run

The welcome tour (you can open it again in Settings > General):

1. **Language** - English, Español, Français, Deutsch, العربية, हिन्दी, 中文, 日本語.
2. **A free model** - on this computer (LOKI installs Ollama and a model that fits, one click) or
   online (OpenRouter sign-in, or a free Groq / Gemini key).
3. **What you want help with.**
4. **Try an example** - each runs in a new chat and changes nothing on your computer.

Help is always one click away: the **?** at the top right, or **F1**.

## Updates

LOKI checks for new versions by itself and applies them safely:

- A new version is downloaded, its checksum and signature are checked, and it is **tried in the
  background first** (its own self-test, every window file present). A version that fails is never
  used - LOKI stays on the one that works and says why in Settings > Machines & updates.
- After switching, the new version is kept only once its window opens. If it does not within 5
  minutes, LOKI goes back to the previous version by itself.
- Your data (chats, settings, keys, models) is never touched by an update.

Turn automatic updates off in Settings > General.

## If something goes wrong

- **The first setup failed** - a message says why (usually no internet). Open LOKI again; it
  continues where it stopped. The details are in `%LOCALAPPDATA%\Loki\app\bootstrap.log`
  (Windows) or `~/Library/Application Support/Loki/app/bootstrap.log` (macOS).
- **LOKI does not answer** - connect a model: Settings > Connections, or the welcome tour.
- Press **Check everything** (the shield icon, bottom left): it tests every part and says what to do.

---

## For maintainers: how the installers work

> **Before giving an installer to anyone:** LOKI is private and contains GPL-3.0 / AGPL-3.0 ports
> (docs/THIRD_PARTY.md). Handing out an installer is distributing LOKI: remove or rewrite those parts
> first, or publish LOKI under that licence. That is the owner's decision (ZIVA_TASKS.md, Needs Mohamed).

```
tools/make_release.py --feed <url>    -> dist/release/seed/ (the LOKI tree + RELEASE.json)
                                         dist/release/Loki-<v>.zip + manifest.json (+ .sig)
packaging/windows/loki.iss            -> dist/Loki-Setup-<v>.exe   (Inno Setup 6: iscc)
tools/macos/make_dmg.sh               -> dist/Loki-<v>.dmg          (hdiutil, macOS only)
.github/workflows/installers.yml      builds all three on demand (workflow_dispatch or a v* tag)
```

What is installed:

- the **seed** (a LOKI tree: only git-tracked files, no tests / phone app / CI / harness_data),
- **packaging/installer/bootstrap.ps1 / bootstrap.sh** - first run: downloads **uv** (pinned
  version, checksum checked) into `<data>/runtime`, lets uv fetch a standalone **Python 3.12**, makes
  `<data>/.venv`; then runs the launcher,
- **packaging/installer/loki_launch.py** (stdlib only) - copies the seed into
  `<data>/versions/<version>`, installs the packages of the current version when they change, and
  runs `<data>/versions/<current>/app/loki_app.py` with `LOKI_RELEASE_ROOT` set. When the app exits
  with **76** (a new version was installed, or a rollback happened) it starts the current version
  again. A newer launcher shipped in a good release is kept in `<data>/launcher/`.

How a packaged LOKI updates (`engine/release_update.py`; `engine/updater.py` switches to it when
`LOKI_RELEASE_ROOT` is set, so Update everything, the update banner and Settings > Machines & updates
work the same):

1. read the **feed** (`LOKI_RELEASE_FEED`, else the `feed` in the running version's RELEASE.json):
   `manifest.json` + `manifest.json.sig`. The signature is checked in pure Python against
   `keys/loki_public.pem` (RSA-2048 / SHA-256, as `tools/loki_sign.py sign` makes it). **An unsigned
   or wrongly signed feed is refused** (`LOKI_RELEASE_REQUIRE_SIG=0` only for tests). https only.
2. download the zip, check its **sha256**, unpack it safely (no absolute paths, `..` or links) into
   `<v>.staging`;
3. **pre-flight**: install changed requirements, run the new tree's `app/loki_app.py --self-test`
   with LOKI's Python in a throwaway data folder, and check every file index.html loads
   (`updater.ui_missing`). Failure -> skipped with the reason, never applied;
4. switch `current` (the old one stays as `last_good`), mark it **pending**, exit 76;
5. the window's `/ui/ready` marks it good; the rescue screen or 5 minutes of silence ->
   `rollback()` to `last_good`, skip with the reason, exit 76. The newest 3 versions are kept.

The older PyInstaller build (`packaging/loki.spec`, `tools/windows/build_exe.ps1`, CI's Windows
build) is a frozen, self-contained Loki.exe. It does **not** update itself (FROZEN skips
`auto_update` in app/loki_app.py): people with that build download a new zip. The installers above
are the recommended way for other people.

### Publishing a release

1. Run the **Installers** workflow (Actions > Installers > Run workflow) with the feed URL, or build
   locally with the commands above.
2. Upload `Loki-<v>.zip`, `manifest.json` and `manifest.json.sig` to the feed location, all three
   side by side. While the LOKI repo is private, the feed must be somewhere public - for example a
   separate public `loki-releases` repo's GitHub Releases (`.../releases/latest/download/manifest.json`)
   or any static host. Upload `manifest.json` **last**: installed copies see the new version only
   when the manifest points at a zip that is already there.
3. Hand out `Loki-Setup-<v>.exe` and `Loki-<v>.dmg`.

### Signing

- **Release feed (required for updates):** `LOKI_SIGNING_KEY=/path/private.pem python tools/make_release.py ...`
  signs `manifest.json`. In CI, store the PEM as the `LOKI_SIGNING_KEY_PEM` secret. The private key
  never goes into the repo; its public half is `keys/loki_public.pem`
  (`python tools/loki_sign.py fingerprint`).
- **Windows code signing (recommended):** an OV/EV code-signing certificate (or Azure Trusted
  Signing). Sign the installer: `signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 /f cert.pfx /p <pw> dist\Loki-Setup-<v>.exe`
  (or Inno Setup's `SignTool=` directive). Unsigned installers work but show SmartScreen's warning.
- **macOS (recommended):** an Apple Developer ID. `LOKI_MAC_SIGN_ID="Developer ID Application: ..."`
  and `LOKI_NOTARY_PROFILE=<xcrun notarytool store-credentials profile>` make `make_dmg.sh` sign with
  the hardened runtime, notarize and staple. Unsigned builds work after right-click > Open.

### Third-party pieces downloaded at first run

- **uv** (Astral, MIT/Apache-2.0) - only to install Python; `LOKI_UV_VERSION` pins it (default 0.8.0).
- **Python 3.12** (python-build-standalone, PSF licence) via uv.
- LOKI's Python packages from PyPI (`engine/requirements.txt`, `app/requirements.txt`).
