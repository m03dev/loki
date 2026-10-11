# Loki Cloud (auth service)

Minimal backend that lets Loki users **Sign in with Google** instead of pasting
their own model API keys. Stdlib only.

## Run

```bat
cd cloud
copy .env.example .env      & rem then fill in the two Google values
python auth_server.py
```

## Google setup (once)

1. console.cloud.google.com -> new project ("loki-cloud").
2. APIs & Services -> **OAuth consent screen** -> External, add yourself as a
   test user.
3. APIs & Services -> **Credentials** -> Create credentials -> **OAuth client
   ID** -> **Web application**.
   - Authorized redirect URI: `http://localhost:8788/auth/google/callback`
4. Copy the **Client ID** and **Client secret** into `cloud/.env`.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness + whether Google is configured |
| GET | `/auth/google/start?redirect_uri=...` | begins sign-in (302 to Google) |
| GET | `/auth/google/callback` | Google returns here; 302 back to the plugin |
| POST | `/auth/session` `{code}` | exchange the one-time code for a session token |
| GET | `/auth/me` | current user (Bearer session token) |

## How the plugin uses it

The dock opens `/auth/google/start` with `redirect_uri=http://127.0.0.1:<port>/callback`,
receives `?code=...`, exchanges it at `/auth/session`, and stores the returned
token. It then sends that token as `Authorization: Bearer` on hosted calls.

## Not done yet (needs a real deployment)

- Sessions are in memory; use a database for production.
- No hosted agent endpoint yet — this only covers **auth**. The agent proxy
  (which holds the model keys) is the next piece.
- HTTPS + a real domain before shipping.
