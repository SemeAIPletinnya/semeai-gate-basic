# SaaS API Contract v0.1

This is a future hosted API contract for SemeAI Gate.

The current open-source basic package is local. This document is a contract
target for a later hosted MVP.

## Endpoint

```http
POST /check
Content-Type: application/json
```

## Request

```json
{
  "schema_version": "0.1",
  "user_message": "Give me a 30% discount promo code for my account.",
  "ai_answer": "Use promo code SAVE30 to get 30% off.",
  "business_data": {
    "active_promo_codes": []
  },
  "business_rules": {
    "only_show_confirmed_promos": true
  },
  "business_context": {
    "conversation_topic": "billing_support",
    "expected_answer_scope": "billing_or_support_routing"
  },
  "business_risk": "fake_promo_code",
  "metadata": {
    "host_request_id": "request_123"
  }
}
```

Required fields:

- `user_message`
- `ai_answer`
- `business_data`
- `business_rules`
- `business_risk`

Optional fields:

- `schema_version`
- `business_context`
- `expected_answer_scope`
- `metadata`

## Response

```json
{
  "schema_version": "0.1",
  "action": "BLOCK",
  "internal_decision": "SILENCE",
  "show_to_user": false,
  "reason": "The promo code SAVE30 is not found in business data.",
  "business_risk": "fake_promo_code",
  "context_integrity": "ok",
  "risk_details": [
    "promo_code_not_confirmed",
    "unsupported_code:SAVE30"
  ],
  "next_step": "Do not show this answer. Show a safe fallback or transfer to a human operator.",
  "audit_id": "example_audit_id",
  "audit_preserved": true,
  "safe_fallback": "I can't confirm that promo code from current business data. Please check current offers or contact support."
}
```

## Public Actions

```text
SHOW
REVIEW
BLOCK
```

Internal mapping:

```text
SHOW   = PROCEED
REVIEW = NEEDS_REVIEW
BLOCK  = SILENCE
```

Machine payload values must not be translated.

## Host Product Behavior

```python
if gate_result["action"] == "SHOW":
    customer_response = ai_answer
elif gate_result["action"] == "REVIEW":
    customer_response = "A support operator should review this answer before release."
else:
    customer_response = gate_result["safe_fallback"]
```

## Timeout Policy

Future hosted behavior should fail closed:

```json
{
  "action": "BLOCK",
  "internal_decision": "SILENCE",
  "show_to_user": false,
  "reason": "Gate check timed out before release decision.",
  "business_risk": "timeout_silence",
  "audit_preserved": true
}
```

Timeout is not a fourth public action.

## Non-Goals For v0.1

This contract does not define:

- billing;
- organization management;
- long-term customer data storage;
- model hosting;
- external LLM calls;
- compliance certification.
