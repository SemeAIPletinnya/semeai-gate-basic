# Email provider v0.1

SemeAI Gate sends verification and operator notices through a pluggable provider.

## Priority order

1. **Resend** — `SEMEAI_GATE_RESEND_API_KEY` (or `RESEND_API_KEY`)
2. **SMTP** — `SEMEAI_GATE_SMTP_HOST` + user/password
3. **Outbox only** — durable JSON files under `SEMEAI_GATE_ACCOUNT_DIR/email_outbox`

## Recommended production setup (Resend)

1. Create a free account at https://resend.com
2. Verify domain `semeai.tech` (or start with Resend sandbox `onboarding@resend.dev` for tests)
3. Create an API key
4. Set Fly secrets:

```bash
fly secrets set \
  SEMEAI_GATE_RESEND_API_KEY=re_xxx \
  SEMEAI_GATE_EMAIL_FROM="SemeAI Gate <onboarding@resend.dev>" \
  SEMEAI_GATE_OPERATOR_EMAIL=adelayida0403@gmail.com \
  SEMEAI_GATE_FEEDBACK_EMAIL=adelayida0403@gmail.com \
  -a semeai-gate-api
```

When using a verified domain:

```bash
fly secrets set SEMEAI_GATE_EMAIL_FROM="SemeAI Gate <noreply@semeai.tech>" -a semeai-gate-api
```

## What gets emailed

| Event | To | Content |
| --- | --- | --- |
| Registration | applicant | verification link |
| Registration | operator | notice + registration id |
| Billing TXID submit | operator | workspace_id, invoice_id, txid |

## Health fields

`GET /health` → `email_verification.provider`, `automatic_email_delivery`, `operator_email`.

## Local outbox

Without a provider key, emails are written to:

```text
$SEMEAI_GATE_ACCOUNT_DIR/email_outbox/*.json
```

Operator can forward them manually until Resend/SMTP is configured.
