# Fly.io API Deploy v0.1

This guide deploys the SemeAI Gate Basic API runtime to Fly.io for
`api.semeai.tech`.

`gate.semeai.tech` can stay on GitHub Pages as the static demo. The API needs a
real Python/Docker runtime, so it should run on Fly.io or another backend host.

## What Fly Runs

Fly.io builds the repository `Dockerfile` and exposes the Python API server:

```text
POST /v0/check
GET  /health
HEAD /health
GET  /v0/demo/scenarios
GET  /v0/demo/account
POST /v0/demo/check
POST /v0/register
POST /v0/verify
GET  /v0/account
GET  /v0/receipts
GET  /v0/receipts/{receipt_id}
```

The public API still requires an API key. Do not deploy a public API without
`SEMEAI_GATE_API_KEYS`.

Exception: `/v0/demo/check` is a browser-safe public demo endpoint. It does not
require an API key, does not persist receipts, and is not the production/pilot
integration endpoint.

`/v0/demo/account` is also public demo metadata only. It returns the SaaS
account-shell labels and manual activation placeholder for `gate.semeai.tech`.
It does not return API keys, customer secrets, or payment-provider tokens.

`/v0/register` and `/v0/verify` are the first browser-safe account endpoints.
They create a pending workspace record, verify an email-link token, and issue a
workspace API key once. The raw API key is not stored server-side. In v0.1 email
delivery is not configured; the verification link is returned for manual
early-access activation.

## Files

The repository includes:

```text
Dockerfile
fly.toml
.env.api.example
```

Default Fly app name in `fly.toml`:

```text
semeai-gate-api
```

If that app name is unavailable in your Fly account, create another name and
update the `app = "..."` line in `fly.toml`.

Default Fly region in `fly.toml`:

```text
arn
```

This keeps the first pilot close to Europe while avoiding deprecated regions
for new Fly Machines.

## Install Fly CLI

On Windows:

```powershell
winget install Fly.Flyctl
```

Then restart the terminal and verify:

```powershell
flyctl version
```

## Login

```powershell
flyctl auth login
```

## Create the App

From the repository root:

```powershell
cd "D:\SemeAi\from git\semeai-gate-basic"
flyctl apps create semeai-gate-api
```

If the app already exists, continue.

## Configure Secrets

Generate a long random pilot key and set it as a Fly secret. Never commit real
keys to Git.

```powershell
$pilotKey = "replace-with-long-random-pilot-key"
flyctl secrets set SEMEAI_GATE_API_KEYS="$pilotKey"
flyctl secrets set SEMEAI_GATE_API_KEY_PLANS="{`"$pilotKey`":`"pilot`"}"
```

Optional CORS for the static demo domain:

```powershell
flyctl secrets set SEMEAI_GATE_CORS_ORIGINS="https://semeai.tech,https://www.semeai.tech,https://gate.semeai.tech"
flyctl secrets set SEMEAI_GATE_PUBLIC_SITE_URL="https://semeai.tech"
```

Set this before connecting the static GitHub Pages demo to the live API. The
browser should call only `https://api.semeai.tech/v0/demo/check` and
`https://api.semeai.tech/v0/demo/account`, or the public registration endpoints
`/v0/register` and `/v0/verify`. The authenticated `/v0/check` endpoint must not
be called from public browser JavaScript with a shared secret.

## Deploy

```powershell
flyctl deploy --ha=false
```

Fly will build the Docker image and run the API on internal port `8787`.
`--ha=false` keeps the first pilot to one Machine instead of creating a
high-availability pair.

## Add api.semeai.tech

Add the custom domain in Fly:

```powershell
flyctl certs add api.semeai.tech
flyctl certs show api.semeai.tech
```

Use the DNS record(s) Fly prints. For a subdomain like `api.semeai.tech`, Fly
often supports a CNAME target such as:

```text
api -> semeai-gate-api.fly.dev
```

But use the exact DNS instructions returned by `flyctl certs show` or the Fly
dashboard.

## Verify

Health:

```powershell
curl.exe https://api.semeai.tech/health
```

Use the `https://` URL in browsers. Opening `http://api.semeai.tech/health`
can show a "not secure" label before the Fly HTTPS redirect completes.

Public demo check without an API key:

```powershell
curl.exe https://api.semeai.tech/v0/demo/check `
  -H "content-type: application/json" `
  --data '{ "scenario_id": "fake_promo_code" }'
```

Expected demo result:

```json
{
  "action": "BLOCK",
  "internal_decision": "SILENCE",
  "api": {
    "auth_mode": "public_demo",
    "api_key_exposed_to_browser": false,
    "receipt_persisted": false
  }
}
```

Public account shell metadata without an API key:

```powershell
curl.exe https://api.semeai.tech/v0/demo/account
```

Expected boundary:

```json
{
  "demo_mode": true,
  "customer_data_stored": false,
  "account": {
    "stripe_enabled": false
  },
  "activation": {
    "network": "TRC20",
    "automatic_payment_processing": false
  }
}
```

Register a workspace without embedding an API key in the browser:

```powershell
curl.exe https://api.semeai.tech/v0/register `
  -H "content-type: application/json" `
  --data '{ "email": "pilot@example.com", "company": "Pilot Workspace", "use_case": "support" }'
```

The response includes a manual verification URL for v0.1. Open that URL or pass
the token to `/v0/verify`; the API key is shown once and then only its hash is
kept on the server.

Account/auth:

```powershell
curl.exe https://api.semeai.tech/v0/account `
  -H "authorization: Bearer $pilotKey"
```

Fake promo check:

```powershell
curl.exe https://api.semeai.tech/v0/check `
  -H "content-type: application/json" `
  -H "authorization: Bearer $pilotKey" `
  --data "@examples/api_fake_promo_request.json"
```

Expected result:

```json
{
  "action": "BLOCK",
  "internal_decision": "SILENCE",
  "show_to_user": false,
  "audit_preserved": true
}
```

Receipt list:

```powershell
curl.exe https://api.semeai.tech/v0/receipts `
  -H "authorization: Bearer $pilotKey"
```

Receipt listings are scoped to the authenticated API-key fingerprint.

## Receipt Persistence

The default Fly config writes receipts and account records inside the app
filesystem:

```text
/app/outputs/api_receipts
/app/outputs/api_accounts
```

This is enough for a first smoke deploy. For a longer pilot, add a Fly volume and
mount it to `/app/outputs` before relying on receipts or account records as
durable hosted audit/account data.

Example future step:

```powershell
flyctl volumes create semeai_gate_api_receipts --region arn --size 1
```

Use the same region as `primary_region` in `fly.toml`, or match the region
shown by `flyctl status`.

Then add a `[mounts]` section to `fly.toml`:

```toml
[mounts]
  source = "semeai_gate_api_receipts"
  destination = "/app/outputs"
```

## Boundary

- No external LLM API is called.
- No customer data should be stored in source control.
- Raw prompt/answer text is not stored in receipts by default.
- Public actions remain `SHOW`, `REVIEW`, `BLOCK`.
- Internal decisions remain `PROCEED`, `NEEDS_REVIEW`, `SILENCE`.
- `SILENCE` means release denied, execution withheld, and audit preserved.
