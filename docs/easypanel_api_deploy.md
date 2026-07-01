# EasyPanel API Deploy v0.1

> Legacy note. Use this only if you already own and control the EasyPanel
> instance for the target host. If `api.semeai.tech` opens an EasyPanel login
> you did not create, fix DNS first instead of deploying through that panel.

This guide deploys the SemeAI Gate Basic API behind:

```text
https://api.semeai.tech
```

This is not the preferred path for the current public demo. The preferred path
is Fly.io, documented in [Fly.io API deploy](fly_api_deploy.md).

## App Settings

Create a new EasyPanel app/service:

```text
Name: semeai-gate-api
Source: GitHub repository
Repository: SemeAIPletinnya/semeai-gate-basic
Branch: master
Build: Dockerfile
Port: 8787
Domain: api.semeai.tech
HTTPS: enabled
```

## Environment Variables

Set these in EasyPanel. Do not commit real values to the repository.

```text
SEMEAI_GATE_API_KEYS=<long-random-pilot-key>
SEMEAI_GATE_API_KEY_PLANS={"<long-random-pilot-key>":"pilot"}
SEMEAI_GATE_HOST=0.0.0.0
SEMEAI_GATE_PORT=8787
SEMEAI_GATE_RECEIPT_DIR=/app/outputs/api_receipts
```

`SEMEAI_GATE_API_KEYS` is required for public bind. Without it, the API refuses
to start.

## Persistent Storage

Mount a persistent volume to:

```text
/app/outputs/api_receipts
```

Receipts are scoped by authenticated API-key fingerprint. Raw API keys are not
stored in receipts.

## Verification

Health:

```bash
curl -s https://api.semeai.tech/health
```

Expected:

```json
{
  "status": "ok",
  "service": "semeai-gate-basic"
}
```

Fake promo gate check:

```bash
curl -s https://api.semeai.tech/v0/check \
  -H "content-type: application/json" \
  -H "authorization: Bearer <long-random-pilot-key>" \
  --data @examples/api_fake_promo_request.json
```

Expected:

```json
{
  "action": "BLOCK",
  "internal_decision": "SILENCE",
  "show_to_user": false,
  "audit_preserved": true
}
```

Receipt list:

```bash
curl -s https://api.semeai.tech/v0/receipts \
  -H "authorization: Bearer <long-random-pilot-key>"
```

## Boundaries

- Public actions remain `SHOW`, `REVIEW`, `BLOCK`.
- Internal decisions remain `PROCEED`, `NEEDS_REVIEW`, `SILENCE`.
- `SILENCE` means release denied, execution withheld, audit preserved.
- API authentication is not release authority.
- Subscription metadata is not release authority.
- No external LLM API is called.
- No billing provider is called.
