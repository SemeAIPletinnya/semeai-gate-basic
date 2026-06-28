# Benchmark v0.3

SemeAI Gate Basic includes a deterministic local benchmark for the public
`SHOW / REVIEW / BLOCK` contract.

## Scope

Benchmark v0.3 contains 100 cases across:

- fake promo codes;
- unsupported financial claims;
- unsupported product claims;
- unsafe actions;
- billing context drift;
- account-product mismatch;
- safe supported answers;
- general uncertain answers.

## Run

```powershell
python tools\run_benchmark.py
```

Expected current result:

```text
cases=100 passed=100 failed=0 accuracy=1.0
```

## What Changed Since v0.2

Benchmark v0.2 contained 50 cases. v0.3 adds 50 more deterministic cases with
more variation across:

- fake promo-code variants;
- supported vs unsupported product/account claims;
- severe financial-claim blocking;
- unsafe action blocking;
- billing-support context drift and account-product mismatch.

## Boundaries

The benchmark is local and deterministic.

It does not:

- call an LLM;
- call cloud APIs;
- use network services;
- claim universal hallucination detection;
- claim production certification.

The benchmark validates the small public contract only:

```text
AI answer -> SemeAI Gate -> SHOW / REVIEW / BLOCK -> receipt metadata
```
