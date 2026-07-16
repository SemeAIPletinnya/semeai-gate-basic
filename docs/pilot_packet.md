# SemeAI Gate · Pilot Packet (1-pager)

**Send this** after a design partner asks: *“What exactly would we test?”*  
**Owner:** support@semeai.tech · founder anton_semenenko@semeai.tech  
**Version:** 2026-07-16

---

## One sentence

SemeAI Gate is a **runtime release-control layer** for existing LLM chatbots:
after generation, before the user sees the answer — **SHOW / REVIEW / BLOCK** with audit.

```text
existing chatbot → SemeAI Gate → SHOW | REVIEW | BLOCK → customer / operator / receipt
```

---

## Problem (why this exists)

Production bots invent fluent but unsupported facts:

| Risk class | Example |
| --- | --- |
| Fake promo / refund | “Use SAVE30 for 30% off” when no code exists |
| Unsupported finance / product claim | “Guaranteed 12% return” |
| Unsafe action | “Bypass approval and deploy” |
| Context drift | Billing question → investment pitch |

**Generation is not release authority.**

---

## Pilot goal (narrow on purpose)

Prove **one** class of unsupported answer can be stopped before release, with an audit id.

**Recommended first class:** fake promo-code prevention.

Success metric example:

```text
On N promo-related candidate answers:
  false accepts (SHOW when code not in business data) → near zero
  operator REVIEW queue stays usable
  every BLOCK/REVIEW leaves a receipt id
```

---

## What you provide (partner)

| Item | Notes |
| --- | --- |
| 20–50 sample user messages | real or redacted |
| Candidate AI answers | from current bot, if available |
| Business data | e.g. `active_promo_codes: [...]` |
| Business rules | e.g. only show confirmed promos |
| Safe fallback copy | what users see on BLOCK |
| REVIEW routing | who handles ambiguous cases |

**No production secrets required** for week-1 demo — synthetic data is fine.

---

## What SemeAI provides

| Asset | Link / note |
| --- | --- |
| Live API | `https://api.semeai.tech` · `POST /v0/check` |
| Free browser demo | [semeai.tech](https://semeai.tech) (5 free checks) |
| Product console | [gate.semeai.tech/demo](https://gate.semeai.tech/demo/saas_visible.html) |
| Register workspace | [semeai.tech/register](https://semeai.tech/register.html) |
| Dashboard | keys · checks · receipts · USDT pilot |
| Open source | [semeai-gate-basic](https://github.com/SemeAIPletinnya/semeai-gate-basic) |
| Contract semantics | SHOW=PROCEED · REVIEW=NEEDS_REVIEW · BLOCK=SILENCE |

### Example response

```json
{
  "action": "BLOCK",
  "internal_decision": "SILENCE",
  "show_to_user": false,
  "reason": "The promo code SAVE30 is not found in business data.",
  "business_risk": "fake_promo_code",
  "audit_id": "…",
  "audit_preserved": true,
  "safe_fallback": "I can't confirm that promo code from current business data."
}
```

---

## Pilot commercial shape

| Item | Default |
| --- | --- |
| Fee | **25 USDT** (TRC20) pilot |
| Address | `TJmrrUrpsRpG3u9H4FE9oVyCRPYQYEpG27` |
| Activation | TXID in dashboard + email support@semeai.tech |
| Invariant | **Payment is not gate authority** |

Self-hosted / open-source evaluation is free (you run the binary).

---

## Timeline (suggested 2 weeks)

| Day | Activity |
| --- | --- |
| 0 | 15-min call · pick risk class · share 10 samples |
| 1–2 | Wire `POST /v0/check` or local package (see integration checklist) |
| 3–5 | Run batch on 20–50 cases · export receipts |
| 6–8 | Tune business_data feed + fallback copy |
| 9–10 | Review false accepts / false blocks · go/no-go |

---

## What this is **not**

- Not a replacement LLM  
- Not universal hallucination detection  
- Not SOC2 certification  
- Not “pay to unlock SHOW”

---

## Next step

1. Try [live demo](https://gate.semeai.tech/demo/saas_visible.html)  
2. [Register](https://semeai.tech/register.html) for API key  
3. Follow **[Integration checklist](integration_checklist.md)** (middleware in ~10 lines)

Questions: **support@semeai.tech**
