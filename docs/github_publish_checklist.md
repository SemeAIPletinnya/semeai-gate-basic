# GitHub Publish Checklist

Use this checklist before publishing `semeai-gate-basic`.

## Must Be True

- README explains the product in 30 seconds.
- Python example runs.
- Node example runs.
- Benchmark passes.
- Tests pass.
- Static demo opens locally.
- No private local archives are included.
- No SemeAI Local memory folders are included.
- No generated receipts or cache files are included.
- No cloud/API/network behavior is required.
- Apache-2.0 license is included in `LICENSE`.

## Suggested Commands

```powershell
cd "D:\SemeAi\from git\semeai-gate-basic"
python examples\fake_promo_code.py
node examples\fake_promo_code.js
python tools\run_benchmark.py
python -m pytest
```

## Recommended First Public Scope

Publish only the basic repo:

- `semeai_gate_basic/`
- `examples/`
- `benchmarks/`
- `schemas/`
- `sdks/node/`
- `tests/`
- `tools/`
- `demo/`
- `docs/`
- `README.md`
- `LICENSE`
- `pyproject.toml`
- `.gitignore`

Do not publish:

- private SemeAI Local workspace;
- Twitter/X archive;
- memory folders;
- receipts from private runs;
- `silence-as-control` dependency copy;
- generated build/cache artifacts.

## Positioning

Use this line:

```text
SemeAI Gate Basic stops unsupported AI answers before they reach users.
```

Avoid claiming:

- AGI;
- production certification;
- universal hallucination detection;
- enterprise security guarantee;
- customer usage before pilots.
