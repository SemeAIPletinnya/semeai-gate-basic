# SemeAI Gate API Runtime v0.1

This is the first small SaaS-shaped runtime for SemeAI Gate Basic.

It is still deterministic and local-first. It does not call an external LLM,
cloud AI API, payment API, telemetry service, or customer data store.

## Core API

```text
POST /v0/check
```

The endpoint runs the same local gate contract used by the Python package:

```text
user_message + ai_answer + business_data + business_rules
-> SemeAI Gate
-> SHOW / REVIEW / BLOCK
-> receipt metadata
```

## Public Demo Endpoint

The hosted static demo can call a demo-only endpoint without exposing an API
key in the browser:

```text
POST /v0/demo/check
GET  /v0/demo/scenarios
GET  /v0/demo/account
```

This endpoint is for the public demo shell only. It does not replace the
authenticated production/pilot endpoint.

Demo endpoint guarantees:

- no API key is required or exposed in browser JavaScript;
- receipts are not persisted for public demo calls;
- raw prompt/answer text is not stored by default;
- output still uses the canonical `SHOW` / `REVIEW` / `BLOCK` contract.

`GET /v0/demo/account` returns browser-safe product/account shell metadata for
the public demo. It does not authenticate a customer, process payments, or
return secrets. It exists so `gate.semeai.tech` can show the intended SaaS
surface without exposing a production API key in browser JavaScript.

Production and pilot integrations must use:

```text
POST /v0/check
```

with an API key.

## Account Registration Endpoint

The first browser-safe account backend is intentionally small:

```text
POST /v0/register
POST /v0/verify
```

`/v0/register` accepts an early workspace request without exposing a shared API
key in browser JavaScript:

```json
{
  "email": "builder@example.com",
  "company": "Example Support",
  "use_case": "support",
  "expected_monthly_checks": "1000"
}
```

It creates a pending server-side record and returns a verification link:

```json
{
  "status": "verification_required",
  "workspace_status": "pending_email_verification",
  "verification": {
    "method": "email_link",
    "delivery_provider": "not_configured",
    "manual_delivery": true,
    "raw_verification_token_stored": false
  }
}
```

This v0.1 account layer does not send email yet. The verification URL is
returned for manual early-access activation and local demos. Add a real email
provider later without changing the gate contract.

`/v0/verify` accepts the verification token and issues a workspace API key once:

```json
{
  "verification_token": "..."
}
```

The raw API key is shown once in the response and is never stored server-side.
The server stores only a hash and a fingerprint. Issued API keys can then call
the authenticated endpoints:

```text
POST /v0/check
GET  /v0/account
GET  /v0/receipts
```

Account records are stored under:

```text
outputs/api_accounts
```

Override with:

```text
SEMEAI_GATE_ACCOUNT_DIR=/path/to/api_accounts
SEMEAI_GATE_PUBLIC_SITE_URL=https://semeai.tech
SEMEAI_GATE_CORS_ORIGINS=https://semeai.tech,https://www.semeai.tech,https://gate.semeai.tech
```

Account authentication is not release authority. SaC/SemeAI Gate decisions
remain `SHOW`, `REVIEW`, and `BLOCK`.

## Run Locally

```powershell
$env:SEMEAI_GATE_API_KEYS="local-dev-key"
$env:SEMEAI_GATE_API_KEY_PLANS='{"local-dev-key":"developer"}'
python -m semeai_gate_basic.server --host 127.0.0.1 --port 8787
```

In a second terminal:

```powershell
powershell -ExecutionPolicy Bypass -File examples\api_curl_check.ps1
```

Equivalent curl shape:

```bash
curl -s http://127.0.0.1:8787/v0/check \
  -H "content-type: application/json" \
  -H "authorization: Bearer local-dev-key" \
  --data @examples/api_fake_promo_request.json
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

## Authentication

Set accepted API keys through:

```text
SEMEAI_GATE_API_KEYS=key1,key2
```

Optional local plan metadata:

```text
SEMEAI_GATE_API_KEY_PLANS={"key1":"developer","key2":"pilot"}
```

This is not payment processing. It is local subscription/plan metadata for an
API MVP.

If `SEMEAI_GATE_API_KEYS` is empty, the API runs in `disabled_local_dev` mode.
Do not expose that mode publicly.

When the server binds to a public host such as `0.0.0.0`, API keys are
required. The server refuses to start on a public bind without
`SEMEAI_GATE_API_KEYS`.

## Receipt Storage

By default, API receipts are written to:

```text
outputs/api_receipts
```

Override with:

```text
SEMEAI_GATE_RECEIPT_DIR=/path/to/api_receipts
```

Receipts store metadata and hashes. Raw prompt/answer text is not stored by
default.

Useful endpoints:

```text
GET /health
HEAD /health
POST /v0/register
POST /v0/verify
GET /v0/demo/scenarios
GET /v0/demo/account
POST /v0/demo/check
GET /v0/account
GET /v0/receipts?limit=25
GET /v0/receipts/<receipt_id>
POST /v0/check
```

`/v0/account` and receipt endpoints use the same API key contract.

Receipt listing and receipt reads are scoped to the authenticated API key. A
key can list and fetch only receipts written under its own API-key
fingerprint. The raw API key is never stored in the receipt.

## Docker

Build:

```powershell
docker build -t semeai-gate-basic:0.1 .
```

Run:

```powershell
docker run --rm -p 8787:8787 `
  -e SEMEAI_GATE_API_KEYS=local-dev-key `
  -e SEMEAI_GATE_API_KEY_PLANS='{"local-dev-key":"developer"}' `
  semeai-gate-basic:0.1
```

## Hosted Demo Relationship

The static site at `gate.semeai.tech` remains a SaaS-visible demo shell.

The API runtime is the next layer:

```text
gate.semeai.tech        static demo / public proof
api.semeai.tech         hosted /v0/demo/check and authenticated /v0/check endpoint
```

Always use the HTTPS API URL in browsers and examples:

```text
https://api.semeai.tech/health
```

Opening `http://api.semeai.tech/health` may show a browser "not secure" label
before the platform redirect completes.

See [api.semeai.tech deployment note](api_semeai_tech_deploy.md) before
pointing a public DNS record at the API.

## Subscription Boundary

This MVP includes subscription metadata only:

```json
{
  "subscription": {
    "status": "active",
    "tier": "developer",
    "billing_provider": "not_configured",
    "external_billing_calls": false
  }
}
```

It does not implement Stripe, card collection, invoices, or paid billing.

The public SaaS-visible demo may show a manual activation placeholder:

```json
{
  "activation": {
    "method": "manual_crypto_activation",
    "network": "TRC20",
    "asset": "USDT",
    "automatic_payment_processing": false
  }
}
```

This is not an automated checkout. It is an early-pilot operational placeholder
for manual activation only.

## Invariants

- Generation is not release authority.
- Business actions remain `SHOW`, `REVIEW`, `BLOCK`.
- Internal decisions remain `PROCEED`, `NEEDS_REVIEW`, `SILENCE`.
- `SHOW = PROCEED`, `REVIEW = NEEDS_REVIEW`, `BLOCK = SILENCE`.
- `SILENCE` means release denied, execution withheld, and audit preserved.
- Subscription metadata is not gate authority.
- API key authentication is not release authority.
