# Pilot Packet

This is the short packet to send after a potential design partner asks,
"What exactly would we test?"

## Product

SemeAI Gate Basic is a local release-control adapter for AI answers.

It sits between an existing chatbot and the user:

```text
existing chatbot -> SemeAI Gate -> SHOW / REVIEW / BLOCK -> customer/operator
```

## Problem

Production chatbots can confidently invent unsupported business facts:

- fake promo codes;
- unsupported product or account terms;
- unsupported financial/product claims;
- risky actions;
- answers that drift away from the current support context.

If the answer reaches a user, the user may try it, fail, complain, escalate, or
lose trust.

## Pilot Goal

Prove one narrow thing:

```text
One class of unsupported AI answer can be stopped before customer release while
an audit id is preserved.
```

Recommended first class:

```text
fake promo-code prevention
```

## What You Provide

For a first pilot, the partner provides:

- 20 to 50 representative user messages;
- generated chatbot answers for those messages, if available;
- current business data, such as active promo codes;
- business rules, such as "only show confirmed promo codes";
- safe fallback copy;
- expected route for `REVIEW` cases.

No customer secrets are required for the first demo. Use redacted or synthetic
examples when needed.

## What SemeAI Gate Returns

```json
{
  "action": "BLOCK",
  "internal_decision": "SILENCE",
  "show_to_user": false,
  "reason": "The promo code SAVE30 is not found in business data.",
  "business_risk": "fake_promo_code",
  "next_step": "Do not show this answer. Show a safe fallback or transfer to a human operator.",
  "audit_id": "example_audit_id",
  "audit_preserved": true
}
```

Public action mapping:

```text
SHOW   = PROCEED
REVIEW = NEEDS_REVIEW
BLOCK  = SILENCE
```

`SILENCE` means release denied, execution withheld, and audit preserved. It
does not mean deletion.

## Pilot Success Criteria

The pilot is useful if:

- fake promo-code answers are not shown to users;
- `REVIEW` is routed separately from `BLOCK`;
- safe fallback does not repeat the unsupported claim;
- each result has an `audit_id`;
- the result is understandable to support/product teams;
- no cloud/API/network behavior is required by the basic package.

## Local Demo Commands

```powershell
python examples\fake_promo_code.py
python examples\middleware_boundary.py
node examples\middleware_boundary.js
python tools\check_contract.py
python tools\run_benchmark.py
python -m pytest
```

Expected current signal:

```text
contract_check=passed
cases=100 passed=100 failed=0 accuracy=1.0
11 passed
```

## Pilot Timeline

```text
Day 1: scope one risk class
Day 2: collect sample messages and business data
Day 3: run local integration
Day 4: batch evaluate examples
Day 5: review disagreements
Day 6: tighten business data/rules/fallback text
Day 7: readout and next-risk decision
```

## What This Is Not

This pilot is not:

- a production SLA;
- a compliance certification;
- legal proof;
- universal hallucination detection;
- a replacement for human review;
- a new model runtime;
- fine-tuning or model training.

It is a narrow local release-control pilot.
