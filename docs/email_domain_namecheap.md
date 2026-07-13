# Namecheap + Resend domain email for `noreply@semeai.tech`

Current public DNS for `semeai.tech` (observed):

- MX → PrivateEmail (`mx1/mx2.privateemail.com`) — good for **receiving** mail at your inbox
- SPF → `include:spf.privateemail.com`

That is **inbox hosting**, not yet full **Resend send-domain** verification.

## Goal

Send product mail as:

```text
SemeAI Gate <noreply@semeai.tech>
```

## Steps in Resend

1. Resend → Domains → Add `semeai.tech`
2. Add the DNS records Resend shows (typically):
   - DKIM `resend._domainkey` TXT
   - optional SPF include for Resend (merge carefully with PrivateEmail SPF)
   - optional DMARC `_dmarc`
3. Wait until Resend shows **Verified**
4. Create a fresh API key
5. Fly:

```bash
fly secrets set \
  SEMEAI_GATE_RESEND_API_KEY=re_xxx \
  SEMEAI_GATE_EMAIL_FROM=noreply@semeai.tech \
  SEMEAI_GATE_EMAIL_FROM_NAME="SemeAI Gate" \
  -a semeai-gate-api
```

## SPF merge tip

Keep one SPF TXT on apex, for example:

```text
v=spf1 include:spf.privateemail.com include:amazonses.com ~all
```

(use whatever Resend currently documents; do not publish two SPF records)

## Until verified

API still works with:

- verification URL in register JSON
- outbox + operator notices
- sandbox `onboarding@resend.dev` only to the Resend account owner email
