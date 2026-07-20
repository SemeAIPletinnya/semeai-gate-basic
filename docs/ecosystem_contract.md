# SemeAI Ecosystem Contract

SemeAI is intentionally split into dependent layers instead of one overloaded
repository. Each repository has a different authority boundary.

```text
silence-as-control
-> semeai-gate-basic
-> semeai.tech
-> future SemeAI Local / workspace memory products
```

## Layer 1: silence-as-control

Repository:

```text
https://github.com/SemeAIPletinnya/silence-as-control
```

Role:

- governance source context;
- research and benchmark evidence;
- canonical release-control vocabulary;
- proof that generation is not release authority.

This layer owns the core release-state language:

```text
PROCEED
NEEDS_REVIEW
SILENCE
```

`SILENCE` means release denied, execution withheld, and audit preserved. It does
not mean deletion.

## Layer 2: semeai-gate-basic

Repository:

```text
https://github.com/SemeAIPletinnya/semeai-gate-basic
```

Role:

- open-source B2B adapter;
- Python package and examples;
- versioned API contract;
- deterministic business gate;
- hosted API runtime reference;
- receipt and pilot account surface.

This layer exposes business-readable actions:

```text
SHOW   = PROCEED
REVIEW = NEEDS_REVIEW
BLOCK  = SILENCE
```

The public demo endpoint is browser-safe:

```text
POST https://api.semeai.tech/v0/demo/check
```

The production/pilot endpoint requires authentication:

```text
POST https://api.semeai.tech/v0/check
```

Payment, subscription, and account metadata are never release authority.

## Layer 3: semeai.tech

Repository:

```text
https://github.com/SemeAIPletinnya/semeai.tech
```

Role:

- public landing page;
- product explanation;
- registration flow;
- account dashboard shell;
- live demo entry points;
- research and proof links.

This layer should explain the product clearly in business language:

```text
AI answer
-> SemeAI Gate
-> SHOW / REVIEW / BLOCK
-> user, operator, or safe fallback
-> audit record
```

## Future layer: SemeAI Local workspace

SemeAI Local is the private/local governed memory workspace. It can use the same
core thesis, but it has a different job:

- local memory;
- receipts;
- replay;
- source inventory;
- SaC-in memory admission;
- private archives;
- workspace-level evidence and lineage.

Large user archives, including exported ChatGPT archives, are raw archive
evidence first. They are not admitted memory by default.

## ChatGPT archive handling rule

A raw archive export may be registered as source evidence, but it must not become
trusted memory automatically.

Correct path:

```text
raw archive
-> source inventory
-> SaC-in admission review
-> admitted / review / rejected
-> retrieval only if admitted or explicitly marked safe
```

This prevents memory poisoning and preserves the project invariant:

```text
raw archive is not admitted memory
```

## Deployment modes

The ecosystem supports three delivery modes:

- Open Source: inspect and run the adapter yourself.
- Self-hosted Enterprise: deploy inside the customer's infrastructure.
- SaaS API: fast hosted pilot when security policy allows scoped request data.

Deployment mode does not change gate semantics.

## Non-negotiable invariants

- Generation is not release authority.
- Candidate output is not a released answer.
- Public actions remain `SHOW`, `REVIEW`, and `BLOCK`.
- Internal decisions remain `PROCEED`, `NEEDS_REVIEW`, and `SILENCE`.
- Machine payload values must not be translated.
- `SILENCE` means release denied, execution withheld, and audit preserved.
- Payment metadata is never gate authority.
- Raw archive evidence is not admitted memory by default.
- `silence-as-control` should not be modified by product-surface work unless
  explicitly required.
