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
GET  /v0/account
GET  /v0/receipts
GET  /v0/receipts/{receipt_id}
```

The public API still requires an API key. Do not deploy a public API without
`SEMEAI_GATE_API_KEYS`.

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
flyctl secrets set SEMEAI_GATE_CORS_ORIGIN="https://gate.semeai.tech"
```

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

The default Fly config writes receipts inside the app filesystem:

```text
/app/outputs/api_receipts
```

This is enough for a first smoke deploy. For a longer pilot, add a Fly volume and
mount it to that path before relying on receipts as durable hosted audit data.

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
  destination = "/app/outputs/api_receipts"
```

## Boundary

- No external LLM API is called.
- No customer data should be stored in source control.
- Raw prompt/answer text is not stored in receipts by default.
- Public actions remain `SHOW`, `REVIEW`, `BLOCK`.
- Internal decisions remain `PROCEED`, `NEEDS_REVIEW`, `SILENCE`.
- `SILENCE` means release denied, execution withheld, and audit preserved.
