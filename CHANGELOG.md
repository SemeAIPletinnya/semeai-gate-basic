# Changelog

## 0.1.2 - Integration Contract Fixtures

Patch release after v0.1.1.

Added:

- integration patterns guide;
- Node existing-chatbot integration example;
- contract fixtures for `SHOW`, `REVIEW`, and `BLOCK` paths;
- dependency-free contract checker;
- CI contract check.

Validated:

- GitHub Actions CI passes on `master`;
- contract checker passes;
- benchmark v0.2 passes 50/50 cases with accuracy 1.0;
- pytest contract tests pass.

Boundaries:

- no gate behavior change;
- no cloud/API/network behavior;
- no model runtime;
- no fine-tuning;
- no compliance certification claim.

## 0.1.1 - README Flow and Benchmark v0.2

Patch release after the first public basic release.

Added:

- five-second README demo for the fake promo code case;
- lightweight README SVG flow visual;
- benchmark v0.2 with 50 deterministic cases;
- benchmark documentation page;
- CI trigger support for the repository `master` branch.

Validated:

- GitHub Actions CI passes on `master`;
- benchmark v0.2 passes 50/50 cases with accuracy 1.0;
- pytest contract tests pass.

Boundaries:

- no gate behavior change;
- no cloud/API/network behavior;
- no model runtime;
- no fine-tuning;
- no compliance certification claim.

## 0.1.0 - Local Basic

Initial local basic release candidate.

Added:

- Apache-2.0 license;
- business-facing `SHOW / REVIEW / BLOCK` contract;
- canonical mapping to `PROCEED / NEEDS_REVIEW / SILENCE`;
- Python package and CLI;
- Node adapter;
- local metadata receipts;
- fake promo, unsupported financial claim, unsafe action, and safe support examples;
- deterministic benchmark;
- pytest contract tests;
- static local HTML demo;
- GitHub publish checklist and SaaS-later note.

Boundaries:

- no cloud/API/network behavior;
- no model runtime;
- no fine-tuning;
- no hosted SaaS;
- no compliance certification claim.
