# Benchmark v0.2

SemeAI Gate Basic includes a deterministic local benchmark for the public
`SHOW / REVIEW / BLOCK` contract.

## Scope

Benchmark v0.2 contains 50 cases across:

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
cases=50 passed=50 failed=0 accuracy=1.0
```

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
