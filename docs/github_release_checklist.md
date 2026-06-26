# GitHub Release Checklist

Before publishing this basic repo:

- Review `LICENSE` and confirm the chosen license.
- Confirm no private memory, receipts, screenshots, archives, or local paths are included.
- Run `python -m pytest`.
- Run `python tools/run_benchmark.py`.
- Run `node examples/fake_promo_code.js`.
- Confirm the README makes no production SLA or certification claims.
- Confirm canonical payload states remain:
  - `PROCEED`
  - `NEEDS_REVIEW`
  - `SILENCE`
- Confirm public actions remain:
  - `SHOW`
  - `REVIEW`
  - `BLOCK`

This basic package is suitable for open-source demonstration and SDK review. It
is not the full private SemeAI Local workspace.
