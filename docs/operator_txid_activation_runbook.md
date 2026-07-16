# Operator runbook · TXID review & pilot activation

**Audience:** SemeAI operator (you)  
**Goal:** After a pilot pays **USDT TRC20** and submits a TXID, verify the transfer and activate workspace **billing metadata only**.  
**Invariant:** Activation does **not** change SHOW / REVIEW / BLOCK. Payment is never release authority.

---

## 0. Prerequisites

| Item | Value / source |
| --- | --- |
| API base | `https://api.semeai.tech` |
| Admin key | Fly secret `SEMEAI_GATE_ADMIN_KEY` (never in git / never in browser) |
| Payment address | `TJmrrUrpsRpG3u9H4FE9oVyCRPYQYEpG27` (TRC20 USDT) |
| Default amount | **25.00 USDT** (`SEMEAI_GATE_MANUAL_USDT_AMOUNT`) |
| Pilot email inbox | `support@semeai.tech` |
| Founder / operator | `anton_semenenko@semeai.tech` |
| Explorer | [Tronscan](https://tronscan.org/) · filter USDT TRC20 to payment address |

Admin auth header (either form works if server accepts both):

```http
Authorization: Bearer <SEMEAI_GATE_ADMIN_KEY>
```

or

```http
X-Admin-Key: <SEMEAI_GATE_ADMIN_KEY>
```

Load key into shell (local only):

```powershell
$env:SEMEAI_ADMIN_KEY = "<paste from password manager / fly secrets>"
$API = "https://api.semeai.tech"
```

---

## 1. How the customer path works (for context)

```text
Register → verify email → API key
  → Dashboard → Billing → Create payment intent  (invoice_id)
  → Send 25 USDT TRC20 to payment address
  → Submit TXID in dashboard
  → Email support@semeai.tech with workspace_id + invoice_id + txid
  → YOU review + activate
```

Customer status sequence:

```text
pending_payment → pending_review → paid / active  (after you activate)
```

Submitting TXID alone does **not** activate access.

---

## 2. Intake: email arrives

Expected body fields:

| Field | Example |
| --- | --- |
| `workspace_id` | `ws_…` |
| `invoice_id` | `inv_…` |
| `txid` | 64-char hex |
| optional | company, email used at register |

**SLA suggestion:** respond within **1 business day** (ack + ETA or activation).

Reply template (ack):

```text
Subject: Re: Pilot payment · <invoice_id>

Received — reviewing TRC20 transfer for workspace <workspace_id>.
Will confirm activation once the USDT amount and destination match.

— SemeAI ops · support@semeai.tech
```

---

## 3. List pending billing reviews

```powershell
curl -s "$API/v0/admin/billing-reviews" `
  -H "Authorization: Bearer $env:SEMEAI_ADMIN_KEY"
```

Or list workspaces:

```powershell
curl -s "$API/v0/admin/workspaces" `
  -H "Authorization: Bearer $env:SEMEAI_ADMIN_KEY"
```

Record for the ticket:

- [ ] `workspace_id`  
- [ ] `invoice_id`  
- [ ] `txid`  
- [ ] `amount_usdt` (expect 25.00 unless agreed otherwise)  
- [ ] company / email from workspace summary  

---

## 4. On-chain verification (manual)

Open Tronscan (or Trongrid UI) for the **txid**.

Check **all** of:

| Check | Pass if |
| --- | --- |
| Network | TRC20 / Tron mainnet (not testnet) |
| Asset | USDT |
| To address | exact match `TJmrrUrpsRpG3u9H4FE9oVyCRPYQYEpG27` |
| Amount | ≥ agreed pilot (default **25 USDT**) |
| Status | confirmed / success |
| Memo | optional; do not require |
| Replay | same txid not already used for another paid invoice |

If amount is short or wrong token:

- [ ] Do **not** activate  
- [ ] Reply with what is missing  
- [ ] Leave status `pending_review`

---

## 5. Activate workspace (admin API)

Only after on-chain checks pass:

```powershell
$ws = "<workspace_id>"
$inv = "<invoice_id>"
$note = "TRC20 USDT verified; txid <txid>; amount 25; <date>"

curl -s -X POST "$API/v0/admin/workspaces/$ws/activate" `
  -H "Authorization: Bearer $env:SEMEAI_ADMIN_KEY" `
  -H "Content-Type: application/json" `
  -d "{`"invoice_id`":`"$inv`",`"plan`":`"pilot`",`"activation_note`":`"$note`"}"
```

Expect in response (shape may vary slightly):

- workspace / subscription `status` → `active`  
- billing `payment_status` → `paid`  
- `payment_metadata_is_gate_authority` remains false / release authority unchanged  

- [ ] Activation response `ok`  
- [ ] Note stored with txid reference  

---

## 6. Confirm from customer side (optional sanity)

Ask customer to **Load workspace** in dashboard, or if they share a key (prefer not — you can use admin list):

```powershell
# customer key — only if they re-paste for support; prefer admin list
curl -s "$API/v0/billing/status" -H "Authorization: Bearer <customer_api_key>"
```

Expect: paid / active pilot metadata.

---

## 7. Customer confirmation email

```text
Subject: Pilot activated · <workspace_id>

Hi <Name>,

Payment reviewed and pilot workspace is active.

• Workspace: <workspace_id>
• Invoice: <invoice_id>
• Plan: pilot
• Amount: 25 USDT (TRC20)

Next steps
1. Dashboard: https://semeai.tech/dashboard.html
2. Wire POST /v0/check after your LLM:
   https://github.com/SemeAIPletinnya/semeai-gate-basic/blob/master/docs/integration_checklist.md
3. Start with one risk class (fake promo recommended).

Reminder: billing status never changes SHOW / REVIEW / BLOCK decisions.
Payment is not release authority.

Questions → support@semeai.tech

— SemeAI
```

---

## 8. Rejection / hold email

```text
Subject: Pilot payment needs attention · <invoice_id>

Hi <Name>,

We could not activate yet:

• Reason: <wrong address | wrong amount | unconfirmed | wrong asset | missing txid>
• Expected: 25 USDT TRC20 → TJmrrUrpsRpG3u9H4FE9oVyCRPYQYEpG27

Please reply with a corrected TXID or transfer, plus workspace_id + invoice_id.

— SemeAI ops · support@semeai.tech
```

---

## 9. Security rules (non-negotiable)

| Rule | Why |
| --- | --- |
| Never put `SEMEAI_GATE_ADMIN_KEY` in frontend, GitHub, or chat | Full activate power |
| Never paste customer API keys into public tickets | Account takeover |
| Never treat “email says paid” as proof without explorer check | Fraud |
| Never change gate rules because someone paid | Product invariant |
| Log activation_note with date + txid | Audit |

---

## 10. Fly secrets (reference)

```powershell
# list (names only depending on fly version)
fly secrets list -a semeai-gate-api

# set/rotate admin key when needed
fly secrets set SEMEAI_GATE_ADMIN_KEY="..." -a semeai-gate-api
```

Related env (already on app):

- `SEMEAI_GATE_USDT_TRC20_ADDRESS`  
- `SEMEAI_GATE_MANUAL_USDT_AMOUNT`  
- `SEMEAI_GATE_OPERATOR_EMAIL`  
- `SEMEAI_GATE_FEEDBACK_EMAIL`  

---

## 11. Failure modes

| Symptom | Action |
| --- | --- |
| `admin key is not configured` | Set `SEMEAI_GATE_ADMIN_KEY` on Fly |
| `401/403` on admin routes | Wrong key; rotate if leaked |
| `workspace not found` | Typo in id; list `/v0/admin/workspaces` |
| `invoice does not belong` | Wrong invoice for that workspace |
| Customer paid but no email | Check `/v0/admin/billing-reviews` periodically |
| Double activation | Safe-ish idempotent paid state; still avoid double-crediting manually |

---

## 12. Operator checklist (print this)

```text
[ ] Email or billing-reviews queue has workspace_id + invoice_id + txid
[ ] Tronscan: to address match
[ ] Tronscan: USDT amount ≥ pilot
[ ] Tronscan: confirmed
[ ] TXID not reused for another paid invoice
[ ] POST .../activate with note
[ ] Confirmation email sent
[ ] Log row: date | workspace | invoice | txid | amount | operator
```

---

## Related docs

- [crypto_billing_v0_1.md](crypto_billing_v0_1.md)  
- [pilot_packet.md](pilot_packet.md)  
- [architecture_adr_v0_1.md](architecture_adr_v0_1.md) (ADR-008 manual billing)  
- Admin code: `semeai_gate_basic/admin.py` · `activate_workspace_after_manual_review`  
