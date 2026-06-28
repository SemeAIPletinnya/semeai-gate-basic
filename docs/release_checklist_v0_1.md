# Release Checklist v0.1

Use this checklist before tagging `v0.1.0`.

## Required

- [x] Choose license and add `LICENSE` (Apache-2.0).
- [ ] Run Python tests.
- [ ] Run benchmark.
- [ ] Run Node example.
- [ ] Open `demo/index.html` locally.
- [ ] Confirm generated `outputs/`, `.pytest_cache/`, `.pytest_tmp/`, and `__pycache__/` are not committed.
- [ ] Confirm README explains the product in 30 seconds.
- [ ] Confirm no private local archive, receipt corpus, or memory data is included.

## Commands

```powershell
python -m pytest
python tools\run_benchmark.py
node examples\fake_promo_code.js
```

## GitHub First Release

Suggested first tag:

```text
v0.1.0-basic
```

Suggested release title:

```text
SemeAI Gate Basic v0.1 - SHOW / REVIEW / BLOCK for AI answers
```

## Release Notes

Mention:

- local-only gate;
- no cloud/API dependency;
- no LLM runtime;
- receipts are metadata-first;
- fake promo code demo;
- public business action mapping.
