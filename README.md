# SemeAI Gate Basic

SemeAI Gate Basic is a small open-source release-control layer for LLM answers.

It sits between an existing chatbot and the user:

```text
user message -> LLM answer -> SemeAI Gate -> SHOW / REVIEW / BLOCK
```

The public business actions map to canonical internal release decisions:

```text
SHOW   = PROCEED
REVIEW = NEEDS_REVIEW
BLOCK  = SILENCE
```

`SILENCE` means release denied, execution withheld, and audit preserved. It does
not mean deletion.

## What This Basic Version Includes

- Python package: `semeai_gate_basic`
- Node SDK: `sdks/node`
- JSON schema: `schemas/semeai_gate_v0_1.json`
- 115 deterministic benchmark cases
- Local hash-only receipts
- Examples for fake promo code, context drift, and existing chatbot integration
- No cloud dependency
- No external LLM API
- No private SemeAI memory/archive data

## Quickstart

```powershell
cd semeai-gate-basic
python -m pytest
python tools\run_benchmark.py
python examples\fake_promo_code.py
node examples\fake_promo_code.js
```

## Python Example

```python
from semeai_gate_basic import check_ai_answer

result = check_ai_answer({
    "user_message": "Give me a 30% discount promo code for my account.",
    "ai_answer": "Use promo code SAVE30 to get 30% off.",
    "business_data": {"active_promo_codes": []},
    "business_rules": {"only_show_confirmed_promos": True},
    "business_risk": "fake_promo_code",
})

print(result["action"])  # BLOCK
```

## Contract

Input fields:

- `user_message`
- `ai_answer`
- `business_data`
- `business_rules`
- `business_context`
- `hidden_context_marker`
- `expected_answer_scope`
- `business_risk`
- `metadata`

Output fields:

- `schema_version`
- `action`
- `internal_decision`
- `show_to_user`
- `reason`
- `business_risk`
- `context_integrity`
- `risk_details`
- `next_step`
- `audit_id`
- `audit_preserved`
- `safe_fallback`

## Non-Claims

This basic repo is not a foundation model, not AGI, not a certified compliance
product, not a production SLA, and not universal hallucination detection. It is
a compact release-control contract and demo implementation.
