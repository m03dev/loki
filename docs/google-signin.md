# Sign in with Google (hosted mode)

Users install only the addon, click **Sign in with Google**, and the agent runs
on Loki servers — no Python, no model keys in the plugin.

## Architecture

The dock always talks to a local HTTP endpoint (`127.0.0.1:8766`). Hosted mode
keeps that contract and changes what is behind it:

- **Local mode** — the dock starts `harness/loki.py` on `127.0.0.1:8766`.
- **Hosted mode** — after sign-in the dock holds a **session token** and talks
  to the Loki Cloud endpoint instead. Model keys live server-side only.

## Flow

1. User clicks **Sign in with Google** in the dock.
2. Dock opens `GET {cloud}/auth/google/start?redirect_uri=http://127.0.0.1:<port>/callback`.
3. Cloud redirects to Google's consent screen, then Google calls back the
   cloud at `/auth/google/callback`.
4. Cloud exchanges the code, mints a **one-time code**, and redirects the
   browser back to the dock's loopback `redirect_uri` with `?code=...`.
5. Dock `POST`s `{code}` to `/auth/session` and receives a **session token**.
6. Dock sends `Authorization: Bearer <token>` on hosted agent calls.

## Server side

Implemented in **`cloud/auth_server.py`** (see `cloud/README.md`). Requires a
Google OAuth **Web application** client; register the redirect URI
`{LOKI_CLOUD_BASE_URL}/auth/google/callback`.

## Status

- Auth service: **implemented AND verified end-to-end** — a real Google account
  completed consent, the cloud received the code, and issued a session token.
- Hosted agent proxy (the part that holds model keys and runs tasks): **not yet**.
- Dock "Sign in with Google" button + client: pending (next), so a button would
  be a fake until the hosted endpoint exists.

## Not for production yet

In-memory sessions, no HTTPS/domain, no quota/billing.
