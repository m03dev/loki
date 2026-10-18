# Installing LOKI (for everyone)

This page is for people who want to **use** LOKI. Developers who work on LOKI itself use a git
checkout and `setup.sh` / `setup.bat` instead (see README.md). Friends testing LOKI: docs/TESTERS.md
is the short version, with what to try and how to send feedback.

## What you need

- **Windows 10 or 11** (64-bit) or **macOS 11 or newer** (Apple Silicon; an Intel build when CI has one).
- About **1 GB** of free disk for LOKI itself, plus 2-10 GB if you want a model on your computer.
- Nothing else: no Python, no git, no Homebrew, no admin rights, no account. **LOKI's own Python and
  every package it needs are inside the installer**, so the first start downloads nothing and works
  offline. An account is only needed if you choose an online model.

Downloads: https://github.com/m03dev/loki/releases/latest

## Windows

1. Download **Loki-Setup-<version>.exe** and open it.
   - Windows may say "Windows protected your PC" while the installer is not code-signed yet:
     press **More info > Run anyway**.
2. Click through the installer. It installs for **you only** (no admin password) into
   `%LOCALAPPDATA%\Programs\Loki`.
3. LOKI opens. The welcome tour asks how LOKI should think.

Open it later from the **Start menu > LOKI** (or the desktop icon). **Portable instead:**
`Loki-<version>-windows-portable.zip` - unzip anywhere, double-click **Loki.exe**.

**Uninstall:** Settings > Apps > LOKI > Uninstall. Your chats, settings and keys stay in
`%LOCALAPPDATA%\Loki`; delete that folder to remove everything.

## macOS

1. Download **Loki-<version>.dmg** (or `Loki-<version>-macos.zip`), open it and drag **LOKI** to
   **Applications**.
2. The first time: **right-click LOKI > Open > Open** (LOKI is ad-hoc signed, not notarized yet, so
   macOS asks once). If macOS says the app "is damaged", run once in Terminal:
   `xattr -dr com.apple.quarantine /Applications/Loki.app`.
3. The window opens with the welcome tour.

**Uninstall:** drag LOKI from Applications to the Trash. Your data stays in
`~/Library/Application Support/Loki`; delete that folder to remove everything.

## The first run

The welcome tour (open it again in Settings > General):

1. **Language** - English, Español, Français, Deutsch, العربية, हिन्दी, 中文, 日本語 (+ bigger text, high contrast).
2. **How should LOKI think?**
   - **Run AI on this computer (free, private)** - LOKI reads the computer (memory, GPU / Apple
     Silicon, free disk), picks a model that fits and downloads quickly (Bonsai 2 9B or 4B, or a small
     Qwen; a bigger one is offered later), installs **Ollama** quietly if it is missing (Windows: the
     official installer, silent, per-user; macOS: the official app, its server started in the
     background) and downloads the model **in the background**: a card at the bottom right shows the
     progress and keeps going after the tour. If it fails, the card offers: try again, install
     Ollama by hand, or use an online model.
   - **Connect an account** - OpenRouter (one-click sign-in in the browser), **NVIDIA NIM** (a free
     key from build.nvidia.com: DeepSeek V4.1 Flash, LOKI's main driver), Groq or Google Gemini (paste
     a free key; it stays on this computer).
   - **Both** - chat online at once while the local model downloads.
3. **What you want help with.**
4. **Try an example** - each runs in a new chat and changes nothing on your computer.

Every step can be skipped. Help is always one click away: the **?** at the top right, or **F1**.

## Updates

LOKI checks GitHub Releases for new versions by itself and applies them safely:

- While LOKI runs, a new version is downloaded, its checksum and signature are checked, and it is
  **tried in the background** (its own self-test, every window file present). A version that fails
  is never used - LOKI stays on the one that works and says why in Settings > Machines & updates.
- The **next start** switches to it instantly (no waiting for downloads before the window). It is
  kept only once its window opens; if it does not within 5 minutes, LOKI goes back by itself.
- Your data (chats, settings, keys, models) is never touched by an update.

Turn automatic updates off in Settings > General (or `LOKI_RELEASE_FEED=off`).

## If something goes wrong

- **LOKI does not open** - a message says why. Details: `%LOCALAPPDATA%\Loki\app\launcher.log`
  (Windows) or `~/Library/Application Support/Loki/app/launcher.log` (macOS).
- **LOKI does not answer** - connect a model: Settings > Connections, or the welcome tour.
- Press **Check everything** (the shield icon, bottom left): it tests every part and says what to do.
- **Send feedback**: Settings > General > Send feedback (a zip of logs without keys or chats).

---

## For maintainers: how the installers work

```
tools/make_release.py [--asset-base URL]  -> dist/release/seed/ (the LOKI tree + RELEASE.json)
                                             dist/release/Loki-<v>.zip + manifest.json (+ .sig)
tools/bundle_runtime.py                   -> dist/runtime/  python-build-standalone 3.12 + LOKI's packages,
                                             byte-compiled (run on the target OS; needs uv on the build machine)
packaging/launcher (cargo build --release) -> Loki.exe / Loki   the native double-click launcher (Rust std only)
packaging/windows/loki.iss  (iscc)        -> dist/Loki-Setup-<v>.exe
tools/make_release.py --from-seed ...     -> dist/Loki-<v>-windows-portable.zip
tools/macos/make_dmg.sh                   -> dist/Loki-<v>.dmg + dist/Loki-<v>-macos.zip
tools/make_release.py --friends           -> the zip(s) for friends from the last commit (docs/TESTERS.md)
.github/workflows/installers.yml          all of the above on a v* tag, then publishes the GitHub Release
```

Every build runs **tools/secret_scan.py** over what it packages and refuses (exit 2, with the list)
when anything looks like a key, a token, a private key, `.env`, `harness_data/` or a chat file.

What is installed (`%LOCALAPPDATA%\Programs\Loki`, `Loki.app/Contents/Resources`, or the portable folder):

- `Loki.exe` / `MacOS/Loki` - the native launcher: starts `runtime/python/pythonw.exe` (Windows, no
  console) or `runtime/python/bin/python3` on `loki_launch.py --seed seed`; without a runtime (a slim
  build) it runs the bootstrap instead. Sets `LOKI_LAUNCH_T0` and `LOKI_INSTALL_DIR`.
- `runtime/` - the bundled Python with every package; `runtime/loki-requirements.sha256` says which.
- `seed/` - the LOKI tree (git-tracked files only; no tests / phone app / CI / harness_data), with .pyc.
- **packaging/installer/loki_launch.py** (stdlib only) - copies the seed into `<data>/versions/<version>`,
  makes `<data>/.venv` from the bundled Python (`--system-site-packages`, offline, ~0.2 s; again if the
  app moved), pip-installs only requirements that an update added, and runs
  `<data>/versions/<current>/app/loki_app.py` with `LOKI_RELEASE_ROOT` set. On exit **76** (a new
  version, or a rollback) it starts the current version again. A newer launcher shipped in a good
  release is kept in `<data>/launcher/` and used next time. Failures show a dialog (no console).
- **packaging/installer/bootstrap.ps1 / bootstrap.sh** - the slim-build path: download **uv** (pinned,
  checksum checked) -> standalone Python 3.12 -> `<data>/.venv`. With a bundled runtime they hand over
  to it at once.

How a packaged LOKI updates (`engine/release_update.py`; `engine/updater.py` switches to it when
`LOKI_RELEASE_ROOT` is set, so Update everything, the update banner and Settings > Machines work the same):

1. read the **feed**: `LOKI_RELEASE_FEED`, else RELEASE.json's `feed`, else
   `https://github.com/m03dev/loki/releases/latest/download/manifest.json` (`DEFAULT_FEED`) - plus
   `manifest.json.sig`, checked in pure Python against `keys/loki_public.pem` (RSA-2048 / SHA-256).
   **An unsigned or wrongly signed feed is refused** (`LOKI_RELEASE_REQUIRE_SIG=0` only for tests).
   https only, also across redirects (GitHub redirects downloads to its file host).
2. **prepare** (the engine's background check, `release_update.prepare`): download the zip, check its
   sha256, unpack it safely (no absolute paths, `..` or links), pre-flight (changed requirements, the
   new tree's own `--self-test` in a throwaway data folder, every window file) and keep it as `ready`.
   Failure -> skipped with the reason, never applied.
3. at the **next start** (`apply_ready`, no network): switch `current` (the old one stays
   `last_good`), mark it **pending**, exit 76 to the launcher. `LOKI_UPDATE_AT_START=1` = the old
   "download before the window" order.
4. the window's `/ui/ready` marks it good; the rescue screen or 5 minutes of silence ->
   `rollback()` to `last_good`, skip with the reason, exit 76. The newest 3 versions are kept.

The older PyInstaller build (`packaging/loki.spec`, `tools/windows/build_exe.ps1`) is a frozen
Loki.exe that does **not** update itself; the installers above replace it for other people.

### Publishing a release (GitHub Releases, the repo is public)

1. Make sure the release key secret exists (below), then tag: `git tag v0.17.0 && git push origin v0.17.0`
   (the owner, or `tools/ship.py` users with permission - agents never push tags on their own).
2. **Actions > Installers** runs: the release (scanned, signed), the Windows job (bundled Python,
   `Loki.exe`, iscc, the portable zip, a silent install + self-test of the installed copy), the macOS
   jobs (arm64; Intel optional), then **publish**: a draft GitHub Release with every file, made public
   and "latest" only when all are uploaded - so installed copies (which follow `releases/latest`)
   never see a half-uploaded release. The manifest names its zip by its absolute
   `releases/download/<tag>/` URL.
3. A manual run (Run workflow) builds the same files as artifacts without publishing.

### Signing: the release key (never in the repo)

Installed copies trust `keys/loki_public.pem`. Its PRIVATE half signs `manifest.json`. If nobody has
the private key for the committed public key yet (HANDOFF: "who holds the release signing key"),
make a new pair **on your own computer** and replace the public key before the first release:

```
openssl genrsa -out ~/loki-release-private.pem 2048          # keep this file offline / in a password manager
openssl rsa -in ~/loki-release-private.pem -pubout -out keys/loki_public.pem
python tools/loki_sign.py fingerprint                         # publish this fingerprint (README, release notes)
gh secret set LOKI_SIGNING_KEY_PEM --repo m03dev/loki < ~/loki-release-private.pem
```

- Commit only `keys/loki_public.pem` (and the new fingerprint in keys/README.md). The secret scan
  refuses any file with "PRIVATE KEY" in it, so a private key cannot slip into a release zip.
- CI writes the secret to a 0600 temp file for `tools/loki_sign.py sign` and deletes it right after.
- Signing locally: `LOKI_SIGNING_KEY=~/loki-release-private.pem python tools/make_release.py ...`.
- Rotating: a new public key in a release is only trusted by copies that already run that release,
  so sign the rotating release with the OLD key, and ship the new public key inside it.

### Code signing (later, recommended)

- **Windows:** an OV/EV code-signing certificate or Azure Trusted Signing; sign `Loki-Setup-*.exe`
  and `Loki.exe` (`signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 ...`).
  Unsigned works, with SmartScreen's warning.
- **macOS:** an Apple Developer ID. Secrets `LOKI_MAC_SIGN_ID` and `LOKI_NOTARY_PROFILE` make
  `make_dmg.sh` sign with the hardened runtime, notarize and staple. Without them the app is ad-hoc
  signed (`codesign -s -`; Apple Silicon needs at least that) and opened once with right-click > Open.

### Third-party pieces inside the installers

- **CPython 3.12** from python-build-standalone (PSF-2.0; build scripts MPL-2.0), bundled.
- LOKI's Python packages from PyPI (`engine/requirements.txt`, `app/requirements.txt`), bundled; each
  carries its licence in its `.dist-info`.
- **uv** (Astral, MIT/Apache-2.0) - only on build machines, and in slim builds' bootstrap.
- **Ollama** is not bundled: the tour downloads the official installer from ollama.com when asked.
Rows in docs/THIRD_PARTY.md.
