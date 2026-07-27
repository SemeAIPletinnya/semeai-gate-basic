# Repository Workspace GitHub App

The public Repository Evidence Benchmark remains anonymous at
`https://semeai.tech/benchmark/`. The authenticated trace-preservation surface
lives separately at `https://semeai.tech/benchmark/workspace/`.

This integration is a GitHub App. User authorization authenticates an immutable
GitHub numeric user ID. Installation authorization separately controls which
repositories the app may inspect. A matching login or email never grants access
and never links this account to an existing Gate SaaS account.

## Operator checklist

1. Create a GitHub App named `SemeAI Repository Workspace`.
2. Set the homepage URL to `https://semeai.tech/benchmark/`.
3. Enable user authorization and set its callback URL to
   `https://api.semeai.tech/v0/oauth/github/callback`.
4. Set the post-installation setup URL to
   `https://api.semeai.tech/v0/github/install/callback` and enable redirect on
   update so changed repository selections are synchronized.
5. Request no account/user permissions. Email access is not required.
6. Request only these repository permissions:
   - Metadata: read-only (GitHub supplies this permission to installed apps).
   - Contents: read-only.
7. Do not request administration, contents write, issues write, pull requests
   write, workflows write, repository deletion, or organization administration.
8. Disable webhooks for this first phase. No webhook secret or event subscription
   is required.
9. Choose `Only on this account` or `Any account` according to the intended pilot.
   Repository access is still limited by each installation's explicit selection.
10. Generate a private key, place it outside the repository with OS-level access
    limited to the API service account, and point the environment variable below
    to that file.

For local development, create a separate development GitHub App (recommended)
with these URLs:

- Homepage: `http://127.0.0.1:8000/benchmark/`
- User callback: `http://127.0.0.1:8787/v0/oauth/github/callback`
- Setup callback: `http://127.0.0.1:8787/v0/github/install/callback`

The API accepts HTTP callback URLs only for `localhost` and `127.0.0.1`. Production
callbacks must use HTTPS and must match the configured endpoint path exactly.

## Required environment

```text
SEMEAI_GITHUB_CLIENT_ID=
SEMEAI_GITHUB_CLIENT_SECRET=
SEMEAI_GITHUB_APP_ID=
SEMEAI_GITHUB_APP_SLUG=
SEMEAI_GITHUB_PRIVATE_KEY_PATH=
SEMEAI_GITHUB_CALLBACK_URL=https://api.semeai.tech/v0/oauth/github/callback
SEMEAI_GITHUB_SETUP_URL=https://api.semeai.tech/v0/github/install/callback
SEMEAI_SESSION_COOKIE_SECRET=
SEMEAI_GATE_PUBLIC_SITE_URL=https://semeai.tech
SEMEAI_GATE_CORS_ORIGINS=https://semeai.tech
SEMEAI_BENCHMARK_WORKSPACE_DIR=
SEMEAI_BENCHMARK_CORE_PATH=
SEMEAI_BENCHMARK_CORE_SHA256=
SEMEAI_NODE_BINARY=node
```

`SEMEAI_SESSION_COOKIE_SECRET` must contain at least 32 high-entropy characters.
`SEMEAI_BENCHMARK_CORE_PATH` must identify the deployed public
`benchmark/assets/benchmark.js`. The optional SHA-256 pin makes the API fail
closed if those analyzer bytes differ from the operator-approved version. Node.js
must be available to the API process so authenticated runs invoke that canonical
module instead of a second scoring implementation.

## HTTP surface

- `GET /v0/oauth/github/start` starts GitHub user authorization.
- `GET /v0/oauth/github/callback` validates one-time state, exchanges the code
  server-side, and rotates into an opaque cookie session.
- `POST /v0/oauth/github/logout` revokes the current session.
- `GET /v0/me` returns the authenticated GitHub identity and workspace summary.
- `GET /v0/github/install/start` starts the separate GitHub App installation.
- `GET /v0/github/install/callback` validates installation state and ownership.
- `GET /v0/github/installations` lists installations owned by the session user.
- `GET /v0/github/repositories` lists retained connected-repository records without changing state.
- `POST /v0/github/repositories/refresh` synchronizes explicit App selections and requires the exact frontend `Origin`.
- `POST /v0/github/installations/{id}/disconnect` disconnects access but preserves
  retained history.
- `POST /v0/benchmark/runs` captures bounded evidence and retains a canonical run.
- `GET /v0/benchmark/runs` lists user-scoped progression summaries.
- `GET /v0/benchmark/runs/{run_id}` returns one user-owned retained receipt.
- `GET /v0/benchmark/configuration` reports GitHub and canonical-analyzer readiness
  without exposing operator paths or secrets.
- `POST /v0/benchmark/account/delete` requires the literal confirmation
  `DELETE BENCHMARK ACCOUNT` and removes local identity, sessions, repository
  records, and retained benchmark history.

State-changing requests require the exact configured public-site `Origin`.
Frontend calls use `credentials: "include"`. The host-only session cookie is
`HttpOnly`, `Secure`, `SameSite=Lax`, scoped to `/v0`, explicitly expires, rotates
after login, and is revoked on logout or account deletion.

## Retention boundary

The service stores normalized bounded evidence, source commit/timestamp, category
scores, indicators, Presentation Gate decision, visual seed and phase, analyzer
and policy versions, the presentation receipt, and its integrity hash. It does
not store repository source text or OAuth/installation access tokens. A short-lived
user token exists only during identity lookup. Installation tokens are generated
server-side for synchronization or capture and discarded after the request.

The presentation receipt hash is an integrity hash, not a signature. A repository
presentation receipt is not SaC/PoR release authority.

## Key rotation

Generate a new GitHub App private key, deploy it alongside the old key, update
`SEMEAI_GITHUB_PRIVATE_KEY_PATH`, restart the API, verify installation listing and
a bounded benchmark run, then revoke the old key in GitHub. Rotate the client
secret and session-cookie secret through the deployment secret store. Rotating the
session-cookie secret intentionally invalidates all existing workspace sessions.
