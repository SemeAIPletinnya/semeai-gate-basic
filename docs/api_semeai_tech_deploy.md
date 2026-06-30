# api.semeai.tech Deployment Note v0.1

`api.semeai.tech` is intended for the hosted SemeAI Gate Basic API runtime.
It cannot be hosted on GitHub Pages because it is a Python HTTP service, not a
static page.

## Required Hosting Shape

Use a backend host that can run a Python process or Docker container, for
example:

- VPS with Docker and a reverse proxy;
- Render / Fly.io / Railway-style container hosting;
- another internal pilot host with HTTPS termination.

Do not expose the API without authentication.

## Required Environment

```text
SEMEAI_GATE_API_KEYS=<comma-separated pilot keys>
SEMEAI_GATE_API_KEY_PLANS={"<key>":"pilot"}
SEMEAI_GATE_HOST=0.0.0.0
SEMEAI_GATE_PORT=8787
SEMEAI_GATE_RECEIPT_DIR=/app/outputs/api_receipts
```

If `SEMEAI_GATE_HOST` is public, the server refuses to start unless
`SEMEAI_GATE_API_KEYS` is configured.

## Docker Run Shape

```bash
docker run --rm -p 8787:8787 \
  -e SEMEAI_GATE_API_KEYS="$SEMEAI_GATE_API_KEYS" \
  -e SEMEAI_GATE_API_KEY_PLANS="$SEMEAI_GATE_API_KEY_PLANS" \
  -e SEMEAI_GATE_RECEIPT_DIR=/app/outputs/api_receipts \
  semeai-gate-basic:0.1
```

## DNS

Point `api.semeai.tech` to the backend host:

- use a provider-specific CNAME when the platform gives one;
- use an A record only when the host provides a stable public IP;
- do not point `api.semeai.tech` to GitHub Pages.

## Verification

Health:

```bash
curl -s https://api.semeai.tech/health
```

Gate check:

```bash
curl -s https://api.semeai.tech/v0/check \
  -H "content-type: application/json" \
  -H "authorization: Bearer <pilot-key>" \
  --data @examples/api_fake_promo_request.json
```

Expected business action for the fake promo example:

```json
{
  "action": "BLOCK",
  "internal_decision": "SILENCE",
  "show_to_user": false,
  "audit_preserved": true
}
```

Receipt listing:

```bash
curl -s https://api.semeai.tech/v0/receipts \
  -H "authorization: Bearer <pilot-key>"
```

Receipt listings are scoped to the authenticated API-key fingerprint.

## Boundary

- No external LLM API is called.
- No billing provider is called.
- No raw API key is stored in receipts.
- Receipt metadata is audit evidence, not release authority.
- Public actions remain `SHOW`, `REVIEW`, `BLOCK`.
- Internal decisions remain `PROCEED`, `NEEDS_REVIEW`, `SILENCE`.
