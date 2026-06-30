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
api.semeai.tech         future hosted /v0/check endpoint
```

For now, keep the API local or deploy it only as a controlled pilot.

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

## Invariants

- Generation is not release authority.
- Business actions remain `SHOW`, `REVIEW`, `BLOCK`.
- Internal decisions remain `PROCEED`, `NEEDS_REVIEW`, `SILENCE`.
- `SHOW = PROCEED`, `REVIEW = NEEDS_REVIEW`, `BLOCK = SILENCE`.
- `SILENCE` means release denied, execution withheld, and audit preserved.
- Subscription metadata is not gate authority.
- API key authentication is not release authority.
