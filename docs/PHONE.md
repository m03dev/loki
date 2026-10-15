# LOKI on the phone

The owner asked for "an iOS and Android version, and a phone-local model - these super small
ones". What is built: **one app for iPhone and Android** (`mobile/`, Expo / React Native)
that chats with **LOKI on your Mac or PC when it can reach it**, and with **a small model on
the phone when it cannot**. The computer side is `engine/phone_link.py`.

## Pairing (once per phone)

1. In LOKI on the Mac or PC: Settings > Machines > **Phone**. Tick *Let the LOKI phone app
   talk to this Mac/PC* (writes `LOKI_PHONE_LINK=1` to `harness_data/.env`; port 8769, change
   it with `LOKI_PHONE_PORT`). Allow Python through the firewall if the system asks.
2. Press **Pair a phone**, give it a name. LOKI shows a QR code (and the same code as text).
3. On the phone: LOKI > **Connect** > *Scan pairing code* (or paste the text). The phone must
   be on the same Wi-Fi as the computer, or both on Tailscale.
4. The phone shows the computer as reachable. Pair the other computer the same way: the
   phone keeps a list and uses the one that answered last first.

Revoke a phone at any time in the same card (*Revoke*); *Forget* on the phone revokes it too.

## Routing: who answers

On every message (`mobile/src/router.ts`):

1. **Auto** (default): try the paired machines, the one that answered last first, all its
   addresses at once, **2.5 s** each (`GET /phone/status`, signed). A reachable machine is
   remembered for 30 s so the next message does not probe again.
2. Reachable: `POST /phone/chat`; the answer is marked **Mac** or **PC**.
3. Not reachable, busy with a chat on the computer, or LOKI's model failed there: the
   phone answers, marked **On phone (Qwen3 0.6B)** (or whichever model), with a line
   saying why. A refusal (revoked, rate limited) is shown instead, not hidden.
4. On the phone, **Needle** (when downloaded and *Quick actions* is on) first checks if the
   message is a quick action - save a note, list notes, switch who answers - and does it,
   marked **On phone (Needle)**. Otherwise the chat model answers, with the last 8 messages
   as context.

The switch at the top of Chat forces **Computer** (never the phone) or **Phone** (never
the network). The phone's chat runs in LOKI's **Ask** mode (no tools); *Let it read my
project* in Connect asks for **Plan** mode (read-only tools). Never Build.

## Safety (threat model)

The phone link listens on your network over plain HTTP, so:

| Risk | What stops it |
| --- | --- |
| Someone else on the Wi-Fi sends LOKI messages | Every request is signed (HMAC-SHA256 over method, path, timestamp, body hash) with a key only the paired phone has. Unknown, revoked or expired phones get 401. |
| A captured request is sent again | Timestamps older than 2 minutes and repeated signatures are refused. |
| Guessing keys | 32 random bytes per phone; 10 refused requests from one address lock it out for 5 minutes. |
| A phone floods LOKI | 60 requests and 6 chat messages per minute per phone. Messages up to 4,000 characters, bodies up to 32 KB. |
| The phone (or a stolen phone) makes LOKI do something risky | The phone gets Ask (no tools) or Plan (read-only) only, never Build. While a phone message runs, the approval function is replaced by one that always says **no**: a phone message can never approve anything, not even through Laya/Jev's automatic risk gate. When the computer is busy the phone gets 409 (modes are never mixed). Revoke the phone in Settings. |
| The QR leaks secrets | It carries only: machine name, Mac/PC, its private addresses, the port, the phone's id and that phone's key. No API key, peer secret or bridge token (tested). An unscanned QR expires after 15 minutes. |
| The key file on the computer | `harness_data/phone/phones.json` (never committed) holds a key derived from the QR token (HMAC-SHA256), not the token itself; revoking wipes it. Anyone who can read `harness_data` can already read your API keys, so it is protected like them. On the phone the key is in the Keychain / Keystore (expo-secure-store). |
| Reaching it from the internet | Only private, loopback and Tailscale (100.64/10) clients are served; the QR only accepts private addresses. |
| Reading the chat on the Wi-Fi | **Not prevented**: plain HTTP. Use Tailscale (WireGuard-encrypted) on untrusted networks. |

The phone link is separate from the Mac <-> PC peer link (port 8768): a phone cannot start
jobs, update a machine or send training data.

## Models on the phone

The **Models** tab shows each model's size, RAM and licence, downloads with a progress bar,
deletes, and suggests one from the phone's memory (expo-device): under 3.5 GB LFM2 350M,
3.5-7.5 GB Qwen3 0.6B, more Qwen3 1.7B. Two engines behind one `LocalBrain` interface
(`mobile/src/brains/`): **Cactus** (default; runs Needle) and **llama.cpp** (llama.rn, GGUF).

| Model | Download | Phone RAM | Good for | Licence | Source |
| --- | --- | --- | --- | --- | --- |
| Needle 2 (Cactus) | 14 MB, ~28 MB RAM in use | any | Tool calls only (quick actions); no chat. 45M params. Needle 3: 8-29 MB, 29-121M params | Apache-2.0 | [Cactus-Compute/needle2](https://huggingface.co/Cactus-Compute/needle2), [cactuscompute.com/needle](https://cactuscompute.com/needle) |
| Gemma 3 270M it | 253 MB (Q4_K_M) | 2 GB+ | Tiny, fast, short answers; weak at facts | Gemma Terms of Use | [google/gemma-3-270m-it](https://huggingface.co/google/gemma-3-270m-it), [GGUF](https://huggingface.co/unsloth/gemma-3-270m-it-GGUF) |
| LFM2 350M | 229 MB (Q4_K_M) | 2 GB+ | Quick chat and summaries on older phones | LFM Open License v1.0 | [LiquidAI/LFM2-350M](https://huggingface.co/LiquidAI/LFM2-350M), [GGUF](https://huggingface.co/LiquidAI/LFM2-350M-GGUF) |
| SmolLM2 360M Instruct | 386 MB (Q8_0) | 2 GB+ | Simple English chat (llama.cpp only) | Apache-2.0 | [HuggingFaceTB/SmolLM2-360M-Instruct](https://huggingface.co/HuggingFaceTB/SmolLM2-360M-Instruct), [GGUF](https://huggingface.co/HuggingFaceTB/SmolLM2-360M-Instruct-GGUF) |
| **Qwen3 0.6B** (default) | 397 MB (Q4_K_M) | 3-4 GB+ | Everyday chat, short reasoning, many languages | Apache-2.0 | [Qwen/Qwen3-0.6B](https://huggingface.co/Qwen/Qwen3-0.6B), [GGUF](https://huggingface.co/unsloth/Qwen3-0.6B-GGUF) |
| Qwen3 1.7B | 1.11 GB (Q4_K_M) | 6-8 GB | Best answers on a recent phone; slower | Apache-2.0 | [Qwen/Qwen3-1.7B](https://huggingface.co/Qwen/Qwen3-1.7B), [GGUF](https://huggingface.co/unsloth/Qwen3-1.7B-GGUF) |

Download sizes are the GGUF files on Hugging Face (checked 2026-10-15). Cactus downloads its
own quantised files; their sizes may differ slightly.

Runtimes:
- **Cactus** - on-device inference engine for phones (Swift, Kotlin, Flutter, React Native,
  Python, Rust bindings); React Native package `cactus-react-native` (+
  `react-native-nitro-modules`), class `CactusLM`. [github.com/cactus-compute/cactus](https://github.com/cactus-compute/cactus),
  [docs (React Native)](https://docs.cactuscompute.com/v1.14/react-native/),
  [quickstart](https://docs.cactuscompute.com/v1.14/docs/quickstart/),
  models: [huggingface.co/Cactus-Compute](https://huggingface.co/Cactus-Compute).
  Note: the newest Cactus docs (v2) describe a React Native bridge copied into the app
  instead of the npm package; the app uses the npm package (v1 API) - see "not done".
- **llama.rn** - llama.cpp for React Native, GGUF files.
  [npm llama.rn](https://www.npmjs.com/package/llama.rn), [github.com/mybigday/llama.rn](https://github.com/mybigday/llama.rn).

## Build and run

See [mobile/README.md](../mobile/README.md): `npm install`, `npx expo prebuild`,
`npx expo run:ios|android --device`, or EAS builds. Expo Go cannot run it (native modules).

## Tested

- `tests/test_phone_link.py` (in `tools/ship.py`): pairing issue/verify/revoke, wrong token,
  changed body/path, old and replayed requests, expiry (unscanned QR, 60 days idle), rate
  limits (chat, refused signatures), public clients refused, Build refused, a phone chat
  cannot approve (and mode/approval are restored), busy -> 409, the QR payload, the
  `/phones` Settings routes, the bridge wiring, real HTTP on 127.0.0.1, and the phone app's
  TypeScript `protocol.ts` run in Node agreeing with Python byte for byte.
- `npm run typecheck:offline` (tsc with declaration stubs).

## Not done yet

- **Not built or run on a real phone.** The npm registry was not reachable where this was
  written: no `npm install`, no `expo prebuild`, no device run. The TypeScript was checked
  against hand-written declarations of the packages' documented APIs, not the real types.
- Cactus details to confirm on first install: the model-list fields, the slugs other than
  `qwen3-0.6b`, whether a `needle` slug exists in the npm package, and how to delete a
  downloaded model (no documented call; the app removes the folders Cactus is known to use
  and says so if it finds none). If the npm package is retired in favour of the v2 bridge,
  only `src/brains/cactus.ts` changes.
- No encryption on the LAN (use Tailscale); no push notifications; no voice; no images.
- The phone cannot see or answer approval prompts (by design, approvals stay on the computer).
- A phone message is added to the active conversation on the computer, like a typed one.
- No app icon/splash artwork yet; no store listing.
