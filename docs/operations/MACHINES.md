# Your machines, talking: the Mac and the PC

Loki on one computer can talk to Loki on another on your home network. The usual pair:

- **The PC** (RTX 3070 Ti): listens. It runs heavy jobs, trains Loki's own model, and can
  serve models to the Mac.
- **The Mac**: links to the PC. It sends jobs, sends its verified work to train on, and
  uses the PC's trained model once it has proven itself.

## What they do together

| | How | When |
| --- | --- | --- |
| See each other | the Mac reads the PC's hello: OS, GPU load, models, jobs, training state | Settings > Machines |
| Jobs on the PC | the Mac sends a prompt; the PC runs it with its built-in Loki agent in an isolated worktree | you click Send |
| Train on both machines' work | the Mac sends every verified success to the PC (the trainer) | every 10 min, or "Send verified work now" |
| Use the PC's GPU for models | the Mac routes local-model calls to the PC's Ollama (`LOKI_WORKERS`) | when the Mac lacks the model |
| Use the trained model | when the PC promotes a model that beat its baseline, the Mac uses it too | automatic |

## Link them (once)

> **On different networks?** (the Mac on 192.168.1.x and the PC on 192.168.0.x cannot
> reach each other.) The link only dials private addresses, so use Tailscale, or a public
> relay behind a loopback forwarder - see [OFF_NETWORK.md](OFF_NETWORK.md).

**1. On the PC** (Windows), in the Loki checkout `C:\Users\macul\Documents\loki`:

```bat
git pull
setup.bat
```

Open Loki, then **Settings > Machines > "Let my other machines link to this one"**.
Copy the **link code** it shows. (No app open? `harness_data\.venv\Scripts\python.exe
tools\peer_link.py pair --name pc` prints the same code; then restart Loki.)

If Windows asks whether Python may use the network, allow **Private networks** only.

To let the Mac use the PC's GPU for models as well:

```bat
setx OLLAMA_HOST 0.0.0.0
```

Then quit and reopen Ollama.

**2. On the Mac**, in the Loki checkout `~/Documents/loki`:

```sh
git pull
```

Reopen Loki.app, then **Settings > Machines > Link another machine**. Paste the code and
click **Link**. The PC appears as *connected*, with its GPU.

To also route models to the PC's GPU, add this line to `~/Documents/loki/harness_data/.env`
(use the PC's address from the link code):

```
LOKI_WORKERS=pc=http://192.168.x.x:11434
```

**3. On the PC, start the training loop** (once):

```bat
tools\setup_training.bat
harness_data\.venv\Scripts\python.exe tools\self_improve.py schedule
```

## Safety

- Nothing listens unless you turn it on, on that machine. It is off by default.
- Every request is signed with a secret both machines share. The secret is never sent,
  and old or replayed requests are refused.
- Only private network addresses are served: your LAN, Tailscale, localhost.
- A linked machine can only ask for a **prompt** to be worked on. It cannot pick the
  program, the folder or a shell command. The receiving machine's own policy still
  decides, and risky tools need a person, so they are refused in the background.
- Verified work is cleaned again on arrival: secrets are masked and the sender's private
  memory is never included.
- The link code contains the shared secret. Treat it like a password. To revoke it,
  turn listening off, delete `LOKI_PEER_SECRET` from the PC's `.env` and link again.

## Settings (`harness_data/.env`)

| Variable | Machine | Meaning |
| --- | --- | --- |
| `LOKI_PEER_LISTEN=1` | PC | run the peer server |
| `LOKI_PEER_SECRET` | both | the shared secret (32+ characters; the link code carries it) |
| `LOKI_PEER_NAME` | both | this machine's name (default: hostname) |
| `LOKI_PEER_PORT` | PC | default 8768 |
| `LOKI_PEERS=pc=http://...:8768` | Mac | the machines to talk to |
| `LOKI_TRAINER_PEER=pc` | Mac | send verified work there to train on |
| `LOKI_WORKERS=pc=http://...:11434` | Mac | use the PC's Ollama for models |
| `LOKI_PEER_SYNC_S` | Mac | seconds between syncs (default 600) |

## Not verified yet

This was tested with two Loki engines on one machine, over real HTTP, including a real
background job (tests/test_peers.py, plus a smoke run). It has **not** yet run between
your actual Mac and PC: firewall prompts, the router, and Windows networking are
untested until you link them.
