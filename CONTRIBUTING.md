# Contributing

Thanks for considering a contribution to SemeAI Gate Basic.

This repo is intentionally small. Please keep changes aligned with the core
product spine:

```text
AI answer -> SemeAI Gate -> SHOW / REVIEW / BLOCK -> Receipt
```

## Core Invariants

- Generation is not release authority.
- Candidate output is not a released answer.
- Public business actions remain `SHOW`, `REVIEW`, `BLOCK`.
- Canonical internal decisions remain `PROCEED`, `NEEDS_REVIEW`, `SILENCE`.
- `SILENCE` means release denied / execution withheld / audit preserved.
- Raw prompt and AI answer text should not be stored in receipts by default.
- Do not add cloud/API/network behavior to the default path.
- Do not turn this repo into a full chatbot, model runtime, or hosted SaaS.

## Local Checks

Run before opening a pull request:

```powershell
python -m py_compile semeai_gate_basic\gate.py semeai_gate_basic\__main__.py tools\run_benchmark.py tests\test_gate_basic.py
python -m pytest
python tools\run_benchmark.py
node examples\fake_promo_code.js
```

## What Makes A Good Contribution

- new deterministic examples;
- clearer docs;
- stronger tests;
- safer receipt metadata;
- additional benchmark cases;
- bug fixes that preserve the public contract.

## What To Avoid

- external LLM API dependencies;
- background network calls;
- generated customer data;
- model fine-tuning;
- changing machine values or translating canonical payload states;
- adding a large UI framework before the basic contract is stable.
