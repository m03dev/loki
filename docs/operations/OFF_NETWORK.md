# Linking two Loki machines that are NOT on the same network

The [peer link](MACHINES.md) is built for a home LAN, but its address rule is stricter than
that: `peers.private_host()` only accepts a **private IP, a Tailscale address (100.64/10), or a
name** - it **refuses a public hostname**. So when the Mac (192.168.1.x) and the PC
(192.168.0.x) are on different networks you cannot simply paste a public address; you need one
of the options below. Nothing here changes the link's own safety: every request is still signed
with the shared secret, and the receiver's policy still decides what may run.

## Option A - Tailscale (recommended: private and encrypted)

Both machines join the same Tailscale network and get a **100.x** address, which the link
accepts directly - no forwarder, encrypted, stable.

1. Install Tailscale on each machine and **sign in with the same account**:
   - macOS: the Tailscale app (`brew install --cask tailscale`) - **needs an admin password**
     for the system extension; then sign in.
   - Windows: the installer from tailscale.com, then sign in.
2. Read each machine's address: `tailscale ip -4` -> e.g. `100.101.102.103`.
3. Link as usual (see MACHINES.md), but use the 100.x address:
   - PC: `tools\peer_link.py pair --name pc --address 100.x.x.x` (prints the link code).
   - Mac: `LOKI_PEERS=pc=http://100.x.x.x:8768` in `harness_data/.env`, then restart Loki.
   - Mac's GPU route: `LOKI_WORKERS=pc=http://100.x.x.x:11434`.

## Option B - public relay + local forwarder (no account, works today)

Reach the other machine through a small public relay, then run a loopback forwarder in front of
it so Loki still dials a *private* address (127.0.0.1). Verified end to end (a signed
`/peer/hello` travelled Mac -> bore.pub -> Mac's own peer server and came back).

1. Both machines install **bore** (github.com/ekzhang/bore) - no account needed:
   - macOS: `brew install bore-cli`
   - Windows: `winget install ekzhang.bore` (or the release .exe on PATH)
2. On the machine that must be **reachable** (the PC), publish its peer port on a free high
   port (keep the port stable by picking one and reusing it):
   ```bat
   bore local 8768 --to bore.pub --port 28768
   ```
   It prints `listening at bore.pub:28768`.
3. On the **other** machine (the Mac), forward a loopback port to it and point Loki there:
   ```sh
   python tools/peer_forward.py --listen 127.0.0.1:8768 --to bore.pub:28768
   # harness_data/.env:
   # LOKI_PEERS=pc=http://127.0.0.1:8768
   ```
   Restart Loki. The Machines panel should show *pc* connected.
4. Do it on **both** machines (each publishing, the other forwarding) so either can reach the
   other - *Update everything* needs the PC to reach the Mac too.

Keep both the `bore` client and `peer_forward.py` running in the background (a macOS
`LaunchAgent` or a Windows logon shortcut), like the engines.

### Verified notes and caveats

- `bore local ... --port N` gives a **stable** endpoint. Do **not** pass `--secret` with the
  public `bore.pub` server: it fails ("timed out waiting for initial message"). Pick an
  uncommon high port.
- The relay endpoint is on the **public internet**: anyone can connect, and the *only* gate is
  the HMAC signature (so treat `LOKI_PEER_SECRET` like a password). The hop is **not encrypted
  end to end** - prefer Option A (Tailscale) on untrusted networks.
- `bore.pub` is a third-party free relay; if it is down, use another bore server or Tailscale.

## Option C - public IPv6 (if both machines have it)

If both machines have a global IPv6 address, one can reach the other's `[<ipv6>]:8768`
directly; run `peer_forward.py --listen 127.0.0.1:8768 --to <ipv6>:8768` on the dialling side
(the link refuses a public address, so the loopback forwarder is still what Loki talks to).
This needs inbound IPv6 allowed on both routers/firewalls, so it is a fallback, not the plan.
