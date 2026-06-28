# Five-Minute Demo Script

This script is for a reviewer, design partner, or integrator opening SemeAI
Gate Basic for the first time.

Goal:

Show that SemeAI Gate Basic sits between an existing chatbot answer and the
real user, returns `SHOW / REVIEW / BLOCK`, and preserves an audit id.

## One-Line Product Story

SemeAI Gate Basic stops unsupported AI answers before they reach users.

## Demo Setup

```powershell
git clone https://github.com/SemeAIPletinnya/semeai-gate-basic.git
cd semeai-gate-basic
```

No cloud service, API key, external LLM, or network call is required after the
repository is cloned.

## Minute 1: Fake Promo Code

Run:

```powershell
python examples\fake_promo_code.py
```

Narration:

The user asks for a discount. The AI answer invents `SAVE30`. Business data
says there are no active promo codes. The gate returns `BLOCK`, internally
mapped to `SILENCE`.

Expected signal:

```text
action: BLOCK
internal_decision: SILENCE
show_to_user: false
audit_preserved: true
```

Meaning:

The host product should not show the fake promo code. It should show a safe
fallback or route to an operator.

## Minute 2: Middleware Boundary

Run:

```powershell
python examples\middleware_boundary.py
node examples\middleware_boundary.js
```

Narration:

This is the intended B2B integration shape:

```text
existing chatbot -> SemeAI Gate -> customer response or safe fallback
```

Expected signal:

```text
gate_action: BLOCK
internal_decision: SILENCE
host_next_step: show_safe_fallback
audit_preserved: true
```

Business interpretation:

The host app keeps its existing chatbot. SemeAI Gate becomes the release
checkpoint before the customer sees the answer.

## Minute 3: REVIEW Is Not BLOCK

Show the host-app branch:

```python
if gate_result["action"] == "SHOW":
    customer_response = ai_answer
elif gate_result["action"] == "REVIEW":
    customer_response = "A support operator should review this answer before release."
else:
    customer_response = gate_result["safe_fallback"]
```

Narration:

`REVIEW` is a separate human-review route. It should not silently fall through
to the same branch as `BLOCK`.

Internal mapping remains stable:

```text
SHOW   = PROCEED
REVIEW = NEEDS_REVIEW
BLOCK  = SILENCE
```

Machine payload values must not be translated.

## Minute 4: Contract and Benchmark

Run:

```powershell
python tools\check_contract.py
python tools\run_benchmark.py
```

Expected signal:

```text
contract_check=passed
schema_version=0.1
cases=50 passed=50 failed=0 accuracy=1.0
```

Narration:

The current basic release has a deterministic local contract checker and a
small local benchmark. These are not claims of universal hallucination
detection. They are regression checks for the public basic contract.

## Minute 5: Tests and Boundaries

Run:

```powershell
python -m pytest
```

Expected signal:

```text
11 passed
```

Close with the boundaries:

- no cloud/API/network behavior;
- no external LLM API calls;
- no model runtime;
- no fine-tuning;
- no compliance certification claim;
- no universal hallucination-detection claim.

## What To Remember

Transformer or chatbot output is a candidate answer.

SemeAI Gate decides whether that answer should be:

- shown to the user;
- routed to review;
- blocked from release.

The audit id preserves the decision trace.

```text
generation proposes
gate decides release
host app acts on SHOW / REVIEW / BLOCK
audit is preserved
```
