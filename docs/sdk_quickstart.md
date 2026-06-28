# SDK Quickstart

SemeAI Gate Basic can be used from Python directly or from Node through the
included local adapter.

The basic package is local and deterministic. It does not call an LLM, cloud
API, network service, or external telemetry.

## Python From Source

```powershell
git clone https://github.com/SemeAIPletinnya/semeai-gate-basic.git
cd semeai-gate-basic
python examples\fake_promo_code.py
```

Use the package directly:

```python
from semeai_gate_basic import check_ai_answer

result = check_ai_answer({
    "user_message": "Give me a 30% discount promo code.",
    "ai_answer": "Use promo code SAVE30 to get 30% off.",
    "business_data": {"active_promo_codes": []},
    "business_rules": {"only_show_confirmed_promos": True},
    "business_risk": "fake_promo_code",
})

if result["action"] == "SHOW":
    customer_response = "Use the AI answer."
elif result["action"] == "REVIEW":
    customer_response = "Send this answer to a human reviewer."
else:
    customer_response = result["safe_fallback"]
```

## Python Install From Git

For a basic source install:

```powershell
python -m pip install git+https://github.com/SemeAIPletinnya/semeai-gate-basic.git
```

Then:

```python
from semeai_gate_basic import check_ai_answer
```

## Node Local Adapter

The Node adapter shells out to the local Python package. This keeps the basic
repo small and avoids adding a separate runtime.

Run:

```powershell
node examples\fake_promo_code.js
node examples\middleware_boundary.js
```

Use:

```javascript
const { checkAIAnswer } = require("./sdks/node");

const gateResult = checkAIAnswer({
  user_message: "Give me a 30% discount promo code.",
  ai_answer: "Use promo code SAVE30 to get 30% off.",
  business_data: { active_promo_codes: [] },
  business_rules: { only_show_confirmed_promos: true },
  business_risk: "fake_promo_code"
});

if (gateResult.action === "SHOW") {
  // show AI answer
} else if (gateResult.action === "REVIEW") {
  // route to human review
} else {
  // show safe fallback / do not release
}
```

## Contract Stability

Business actions:

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

## Validate A Local Integration

```powershell
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
