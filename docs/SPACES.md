# LOKI Spaces - your own Discord, peer to peer

Owner, 2026-10-19: *"an open source discord or voip that's p2p - people make their own and host people - seamless
integration in LOKI World, where people can chat and create lobbies ... reimagine the space ... replace discord"*.

| Piece | Where |
| --- | --- |
| host + member engine, wire server, invites, crypto | `engine/spaces.py` |
| the window's routes (`/spaces/...`, bearer token) | `engine/spaces_api.py` (wired in `engine/loki_bridge.py`) |
| the window: rail, rooms, chat, lobbies, voice | `app/ui/spaces.js`, `app/ui/spaces.css` |
| tests | `tests/test_spaces.py` (two engines over real HTTP), `tests/test_spaces_ui.py` (two windows, a real WebRTC call) |

## What it is

- **A space** is a community. The machine that makes it **hosts** it: no company server, no account. Its LOKI keeps
  the rooms, the members and the (encrypted) history in `harness_data/spaces/hosted/<id>/` (never committed).
- **The Spaces tab** (title bar, Ctrl/Cmd+6) fills the whole window the way Discord does: the rail of spaces, the
  rooms with who is in voice and your own panel (mute, deafen, settings) at the bottom, the room (chat, or the voice
  stage with a tile per person), and the members. Nothing floats over LOKI home or the game (owner: "seamless, I
  don't wanna see it, it should cover the entire screen"). In a call on another tab, a small pill keeps the call;
  the tab shows the unread count.
- **Rooms**: text, voice, and **lobbies** - voice + text that anyone opens for a game or a hangout. A lobby can take
  everyone in it into **LOKI World**, and tidies itself away 90 s after the last person leaves.
- **Invites**: one code, `loki-space:...`, carrying the space id, the space KEY and where to reach the host (its LAN
  address, the public relay address, loopback). Whoever has the code can join. The host can lock the space.
- **Chat**: replies, edits (↑), deletes, reactions, typing, unread dots, @mentions, links. **End-to-end encrypted in
  the window**: the engines (yours and the host's) only ever hold ciphertext.
- **Voice**: WebRTC between the windows - a mesh, peer to peer, DTLS-SRTP. Mute, deafen, push-to-talk (hold `),
  who is speaking. The voice bar follows you everywhere in LOKI. Your own TURN server can be set (You > TURN) for
  networks that block direct calls.
- **Moderation**: owner > admins > members. Kick (can come back), ban (cannot), lock, admin/member roles.

## How it travels

```
window --(bearer)--> its own engine /spaces/...  --HTTP, signed-->  host's spaces port  (LAN :8795 or bore.pub:<port>)
window <==== WebRTC voice, peer to peer (offers/answers relayed as encrypted signals through the host) ====> window
```

- **Spaces port**: `LOKI_SPACES_PORT` (default 8795, the next free one if taken), on all interfaces, only while the
  machine hosts a space. The first time, Windows / macOS ask whether LOKI may accept connections - say yes for
  people on your network. For people elsewhere the port is also published on the public bore relay
  (`engine/relay_link.py`, the same free relay the Mac and PC use), on ports derived from this machine's own secret,
  so invites keep working after a restart. `LOKI_SPACES_RELAY=off` keeps a space LAN-only.
- **Joining**: the new member makes a member id and a 32-byte secret, sends the secret XOR an HMAC-SHA256
  keystream keyed by the space key, plus an HMAC proof that it holds the key. The host checks the proof and keeps
  the secret.
- **Every later request** carries `X-Sp-Member`, `X-Sp-Ts`, `X-Sp-Sig = HMAC(secret, method, path, ts, sha256(body))`;
  the host refuses a bad signature, a clock more than 5 minutes off, and a replay. **Every answer** is signed back
  (`HMAC(secret, "resp", request signature, sha256(body))`), so a relay in the middle cannot change it.
- **Message text** is sealed in the window with AES-256-GCM (WebCrypto); the key is HKDF-SHA256 of the space key
  (salt = space id, info `loki-spaces enc v1`); the room id is the additional data. WebRTC signals are sealed the
  same way (aad `signal`), so nobody in the middle can swap an offer.
- Wire endpoints (all `POST /sp/v1/<space>/<action>`, JSON): `join`, `sync {since}`, `send {room, ct, iv, reply?}`,
  `edit`, `delete`, `react`, `typing`, `room {op: add|edit|delete, kind, name, activity?, cap?, world?}`,
  `voice {room|null, muted, deaf, speaking}`, `signal {to, ct, iv}`, `mod {op: kick|ban|admin|member|lock}`, `leave`,
  `space {name?, color?, icon?}`. `GET /sp/v1/hello` answers `{loki: "spaces"}`.

## Threat model, plainly

- The **host machine** is a member of its own space and can read it - it is your space.
- **Anyone with an invite** can join until the host locks the space or bans them. A banned member still holds the
  key, so what they saw stays seen; rotating the key on a ban is a follow-up.
- **The relay** (bore.pub) sees who connects to whom and when, and the encrypted bytes. It cannot read messages,
  cannot act as a member and cannot change an answer.
- **STUN** (Google, Cloudflare - free public servers) tells each window its public address for the call; the audio
  never goes through them. When two networks are too strict for a direct call, a TURN server is needed (none is
  used unless you set your own).

## LOKI World (the Godot side)

`GET /spaces/world` (bearer) answers `{lobbies: [{space, space_name, space_color, room, name, kind: lobby|voice,
activity, cap, people: [{name, color}]}]}` - every open lobby and voice room in every space this machine is in. The Godot client (`game/loki-world`) should poll
it (like `/world/presence`) and draw each lobby as a place on the island - a campfire with a name plate and the
people in it - and walking into it should post `{"lokiSpaces": "join", space, room}` to the parent window
(`LokiSpaces.join(space, room)` there). Tracked in ZIVA_TASKS.md.

## Next

Screen share and video (renegotiation), file and image attachments (encrypted blobs), key rotation on ban, an
SFU mode for big rooms (the mesh is for up to ~8), LOKI itself as a member (@loki answers in a room, from the
owner's window, so it stays end to end), a phone client (mobile/), and the Godot places above.
