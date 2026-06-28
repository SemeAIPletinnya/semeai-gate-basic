# Basic Audit v0.1

## Status

`semeai-gate-basic` is a small local product spine for SemeAI Gate.

It is intentionally not the full SemeAI Local workspace.

## What Exists

- business-facing contract;
- Python package;
- CLI;
- Node adapter;
- local receipts;
- JSON schema;
- runnable examples;
- deterministic benchmark;
- pytest contract tests;
- static UI demo.

## What It Proves

- An AI answer can be treated as a candidate.
- A separate gate can return `SHOW`, `REVIEW`, or `BLOCK`.
- Business actions map to canonical internal states.
- Fake promo codes can be blocked before release.
- Unsupported financial/product claims can be reviewed or blocked.
- Unsafe actions can be blocked.
- Each decision can leave a metadata receipt.

## What It Does Not Claim

- not AGI;
- not a foundation model;
- not a cloud service;
- not a compliance certification;
- not universal hallucination detection;
- not production SLA;
- not a replacement for human review.

## Current Validation

Expected local commands:

```powershell
python tools\run_benchmark.py
python -m pytest
node examples\fake_promo_code.js
```

Expected state:

```text
benchmark failed=0
pytest passed
fake promo action=BLOCK
```

## Recommended Next Polish

- continue expanding benchmark coverage beyond 100 public-safe cases;
- add a small screenshot or GIF of the static demo;
- collect external pilot feedback;
- keep examples aligned with the versioned contract.
