# Integration Readiness Checklist

Use this checklist before connecting SemeAI Gate Basic to an existing chatbot
or support assistant.

The goal is simple:

```text
existing chatbot -> SemeAI Gate -> SHOW / REVIEW / BLOCK -> customer or operator
```

## 1. Host Product Boundary

Confirm the host product has a clear release boundary:

- [ ] The chatbot/LLM produces an `ai_answer`.
- [ ] The answer is checked before the customer sees it.
- [ ] The host product can choose what to do with `SHOW`, `REVIEW`, or `BLOCK`.
- [ ] The host product can show a safe fallback when release is blocked.
- [ ] The host product can route `REVIEW` to a human/operator path.

Do not wire `REVIEW` and `BLOCK` into the same silent fallback path. `REVIEW`
means manual inspection before release. `BLOCK` means do not release the answer.

## 2. Minimum Request Fields

Every gate call should provide:

- [ ] `user_message`
- [ ] `ai_answer`
- [ ] `business_data`
- [ ] `business_rules`
- [ ] `business_risk`

Optional but recommended:

- [ ] `business_context`
- [ ] `expected_answer_scope`
- [ ] `metadata`

Example:

```json
{
  "user_message": "Give me a 30% discount promo code for my account.",
  "ai_answer": "Use promo code SAVE30 to get 30% off.",
  "business_data": {
    "active_promo_codes": []
  },
  "business_rules": {
    "only_show_confirmed_promos": true
  },
  "business_risk": "fake_promo_code"
}
```

## 3. Business Data Readiness

The gate is only as useful as the business data and rules supplied to it.

Prepare the local data needed for your first use case:

- [ ] active promo codes;
- [ ] supported product/account claims;
- [ ] known account product or subscription tier;
- [ ] approval-required actions;
- [ ] topics/scopes where the answer is allowed to stay;
- [ ] business rules that should block unsupported claims.

Do not treat the chatbot answer itself as business data.

## 4. Action Handling

Implement explicit host-app behavior:

```python
if gate_result["action"] == "SHOW":
    customer_response = ai_answer
elif gate_result["action"] == "REVIEW":
    customer_response = "A support operator should review this answer before release."
else:
    customer_response = gate_result["safe_fallback"]
```

Mapping remains stable:

```text
SHOW   = PROCEED
REVIEW = NEEDS_REVIEW
BLOCK  = SILENCE
```

Machine payload values must not be translated.

## 5. Context Integrity

Context integrity is not a secret keyword and not a prompt trick.

It is a deterministic consistency check between:

- current business context;
- expected answer scope;
- generated AI answer.

Prepare:

- [ ] `business_context.conversation_topic`
- [ ] `business_context.known_account_product`
- [ ] `expected_answer_scope`
- [ ] rules for unsupported financial/product claims

Example signal:

```text
AI answer does not match the current billing support context.
```

## 6. Safe Fallback and Human Review

Before shipping any integration, decide:

- [ ] What should the user see when action is `BLOCK`?
- [ ] Where should a `REVIEW` item go?
- [ ] Who owns the review queue?
- [ ] Is the fallback honest and non-promissory?
- [ ] Does the fallback avoid repeating the unsupported claim?

Safe fallback example:

```text
I can't confirm that promo code from current business data. Please check
current offers or contact support.
```

## 7. Audit Handling

Every result includes audit metadata.

Store or log at least:

- [ ] `audit_id`
- [ ] `action`
- [ ] `internal_decision`
- [ ] `business_risk`
- [ ] `reason`
- [ ] `risk_details`
- [ ] timestamp/host request id if your system has one

Receipts preserve decision evidence. They are not a compliance certification
and should not be represented as legal proof without a separate review process.

## 8. Local Validation Commands

Run:

```powershell
python tools\check_contract.py
python tools\run_benchmark.py
python -m pytest
python examples\middleware_boundary.py
node examples\middleware_boundary.js
```

Expected basic signal:

```text
contract_check=passed
cases=100 passed=100 failed=0 accuracy=1.0
11 passed
```

## 9. First Pilot Scope

Pick one narrow business risk for the first integration:

- [ ] fake promo code;
- [ ] unsupported product/account claim;
- [ ] unsupported financial claim;
- [ ] unsafe action;
- [ ] context drift.

Do not start with all chatbot risks at once.

Recommended first pilot:

```text
fake promo code prevention for support/chatbot answers
```

## 10. Production Boundaries

Do not claim:

- [ ] universal hallucination detection;
- [ ] compliance certification;
- [ ] legal guarantee;
- [ ] autonomous approval authority;
- [ ] replacement for human review;
- [ ] model-level safety proof.

Current basic package does not:

- call cloud APIs;
- call external LLM APIs;
- run a model;
- fine-tune weights;
- provide a hosted SaaS.

## Integration Definition of Done

A first integration is ready when:

- [ ] the host app checks every candidate answer before customer release;
- [ ] `SHOW`, `REVIEW`, and `BLOCK` are handled separately;
- [ ] fake promo code case blocks correctly;
- [ ] safe fallback is shown for `BLOCK`;
- [ ] `REVIEW` routes to a human/operator path;
- [ ] audit id is preserved;
- [ ] contract checker passes;
- [ ] benchmark passes locally;
- [ ] no unsupported production or compliance claims are made.
