# Integration Patterns

SemeAI Gate Basic is meant to sit between an existing AI answer generator and
the real user.

It is not a chatbot replacement. It is a release-control adapter.

```text
user message
-> existing chatbot / LLM app
-> ai answer
-> SemeAI Gate
-> SHOW / REVIEW / BLOCK
-> customer, operator, or safe fallback
```

## Pattern 1: Existing Chatbot Wrapper

Use this when a product already has a chatbot or LLM answer function.

```python
from semeai_gate_basic import check_ai_answer

user_message = "Give me a 30% discount promo code for my account."
ai_answer = existing_chatbot_answer(user_message)

gate_result = check_ai_answer({
    "user_message": user_message,
    "ai_answer": ai_answer,
    "business_data": {"active_promo_codes": []},
    "business_rules": {"only_show_confirmed_promos": True},
    "business_risk": "fake_promo_code",
})

customer_response = ai_answer if gate_result["show_to_user"] else gate_result["safe_fallback"]
```

Run the local examples:

```powershell
python examples\existing_chatbot_integration.py
python examples\middleware_boundary.py
node examples\existing_chatbot_integration.js
node examples\middleware_boundary.js
```

## Pattern 2: Middleware Boundary

Use this when the host application has a request/response boundary.

```text
incoming user request
-> product context lookup
-> LLM answer generation
-> SemeAI Gate check
-> release decision
```

The host product should:

- show the answer only when `action == "SHOW"`;
- route to review when `action == "REVIEW"`;
- block and use a safe fallback when `action == "BLOCK"`;
- keep `audit_id` and receipt metadata for later inspection.

Minimal host-app branch:

```python
if gate_result["action"] == "SHOW":
    customer_response = ai_answer
elif gate_result["action"] == "REVIEW":
    customer_response = "A support operator should review this answer before release."
else:
    customer_response = gate_result["safe_fallback"]
```

The runnable examples are:

- `examples/middleware_boundary.py`
- `examples/middleware_boundary.js`

## Pattern 3: Context Integrity Check

Use this when the host product knows the current business context.

Example:

```json
{
  "business_context": {
    "conversation_topic": "billing_support",
    "known_account_product": "basic_subscription",
    "expected_answer_scope": "billing_or_support_routing"
  }
}
```

If the AI answer drifts into another product, promo, or unsupported financial
claim, the gate can return `REVIEW` or `BLOCK`.

## Business Contract

Public actions:

```text
SHOW
REVIEW
BLOCK
```

Internal canonical decisions:

```text
PROCEED
NEEDS_REVIEW
SILENCE
```

Mapping:

```text
SHOW   = PROCEED
REVIEW = NEEDS_REVIEW
BLOCK  = SILENCE
```

Machine payload values must not be translated.

## Boundaries

This basic package does not:

- run an LLM;
- call cloud APIs;
- call external services;
- replace the host chatbot;
- prove universal hallucination detection;
- provide compliance certification.
