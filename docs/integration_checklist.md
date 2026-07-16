# Integration checklist · SemeAI Gate pilot

Use this after the [pilot packet](pilot_packet.md). Goal: first protected check in production-shaped code, not a slide deck.

---

## 0. Choose deployment mode

| Mode | When | Path |
| --- | --- | --- |
| **A. Hosted API** | Fast pilot, data policy allows scoped payloads | `https://api.semeai.tech` |
| **B. Local package** | Offline / VPC first | `pip install -e .` · `check_ai_answer(...)` |
| **C. Self-hosted API** | Same contract inside your network | Docker / Fly clone |

Most design partners start with **A**, then optionally move to **B/C**.

---

## 1. Get credentials (hosted)

- [ ] Open https://semeai.tech/register.html  
- [ ] Submit work email + use case  
- [ ] Verify email (or paste token)  
- [ ] **Copy API key once** → store in secret manager  
- [ ] Open dashboard → **Load workspace**  
- [ ] Confirm `GET /health` shows `status: ok`

```bash
curl -s https://api.semeai.tech/health | head
```

---

## 2. Confirm public demo works (no key)

```bash
curl -s https://api.semeai.tech/v0/demo/check \
  -H "Content-Type: application/json" \
  -d "{\"scenario_id\":\"fake_promo_code\"}"
```

Expect: `"action":"BLOCK"` (or equivalent for that scenario).

- [ ] Demo check returns SHOW / REVIEW / BLOCK  
- [ ] Browser console: https://gate.semeai.tech/demo/saas_visible.html  

---

## 3. Middleware shape (required)

Insert the gate **after** LLM generation, **before** returning text to the user:

```text
user message
  → your LLM → ai_answer (candidate)
  → SemeAI Gate
  → if SHOW: return ai_answer
  → if REVIEW: hold / queue human
  → if BLOCK: return safe_fallback (or fixed template)
```

### Python (local package)

```python
from semeai_gate_basic import check_ai_answer

result = check_ai_answer({
    "user_message": user_message,
    "ai_answer": ai_answer,
    "business_data": {"active_promo_codes": active_codes},  # from your DB
    "business_rules": {"only_show_confirmed_promos": True},
    "business_risk": "fake_promo_code",
})

if result["action"] == "SHOW":
    customer_response = ai_answer
elif result["action"] == "REVIEW":
    customer_response = "A support operator should review this before release."
else:
    customer_response = result.get("safe_fallback") or "I can't confirm that from current business data."
```

### Hosted API

```bash
curl -s https://api.semeai.tech/v0/check \
  -H "Authorization: Bearer $SEMEAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d @payload.json
```

Node remote helper: `sdks/node/remote.js`  
Python examples: `examples/middleware_boundary.py`, `examples/fake_promo_code.py`

- [ ] Middleware branch implemented for SHOW / REVIEW / BLOCK  
- [ ] Safe fallback copy approved by support lead  

---

## 4. Supply real business facts (critical)

The gate does **not** invent your catalog. You must pass evidence.

| Field | Responsibility |
| --- | --- |
| `business_data` | Your system of record (promos, products, policies) |
| `business_rules` | Flags like `only_show_confirmed_promos` |
| `business_context` | Optional topic/scope for drift checks |
| `business_risk` | Risk class for this check (start with `fake_promo_code`) |

- [ ] Promo (or other) list loaded from live DB / cache, not hard-coded forever  
- [ ] Empty list means “no active promos” → fake codes should BLOCK  
- [ ] No customer secrets / PII in pilot payloads if avoidable  

---

## 5. First vertical pack (recommended)

Start with **fake_promo_code** only.

Payload skeleton:

```json
{
  "user_message": "…",
  "ai_answer": "…",
  "business_data": { "active_promo_codes": [] },
  "business_rules": { "only_show_confirmed_promos": true },
  "business_risk": "fake_promo_code"
}
```

- [ ] 10 known-bad answers → expect BLOCK  
- [ ] 5 known-good answers (code in data) → expect SHOW  
- [ ] 5 vague answers → expect REVIEW or team decision  

Expand later: `unsafe_action`, financial claims, context drift.

---

## 6. Audit & operations

- [ ] Store `audit_id` / receipt id with your conversation id  
- [ ] Dashboard → Receipts / Review queue for REVIEW+BLOCK  
- [ ] Document who owns the REVIEW queue (support / ops)  
- [ ] Confirm raw prompt/answer storage policy (gate receipts hash by default)

---

## 7. Usage limits & pilot billing

- [ ] Read usage in dashboard (daily limits by tier)  
- [ ] If converting to paid pilot: 25 USDT TRC20, create intent, submit TXID  
- [ ] Email support@semeai.tech with workspace_id + invoice_id + txid  
- [ ] Remember: **payment ≠ SHOW permission**

---

## 8. Go / no-go (end of pilot)

| Question | Pass if… |
| --- | --- |
| Did false promo SHOW drop on the test set? | Yes, material reduction |
| Is REVIEW volume operable? | Team can process in SLA |
| Is integration latency acceptable? | Gate p95 typically ≪ model latency |
| Can you refresh business_data? | Automated or daily job exists |
| Do receipts satisfy audit need? | Yes for pilot scope |

---

## 9. Support & links

| Need | Where |
| --- | --- |
| Email | support@semeai.tech |
| Health | https://api.semeai.tech/health |
| Contract | [contract.md](contract.md) |
| Architecture / debt | [architecture_adr_v0_1.md](architecture_adr_v0_1.md) |
| 5-min demo script | [demo_script_5_min.md](demo_script_5_min.md) |
| Outreach templates | [partner_outreach_templates.md](partner_outreach_templates.md) |

---

## Minimal “done” definition

You are integrated when:

1. Every candidate answer for the chosen risk class hits the gate.  
2. SHOW / REVIEW / BLOCK drive real user-visible behavior.  
3. At least one BLOCK case has a preserved `audit_id` you can look up.  

Everything else is optimization.
