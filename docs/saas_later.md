# SaaS Later

Do not start with SaaS.

Start with:

```text
GitHub basic repo -> SDK/demo proof -> 2-3 pilots -> SaaS/API wrapper
```

## Why Not SaaS First

SaaS adds work that does not prove the core value:

- authentication;
- billing;
- hosted storage;
- compliance claims;
- uptime/SLA;
- tenant isolation;
- security review;
- deployment and support.

The current core value is simpler:

```text
AI answer -> Gate -> SHOW / REVIEW / BLOCK -> Receipt
```

## SaaS MVP Shape

Only after basic repo and pilot proof, SaaS can expose:

- `/check` API endpoint;
- versioned schema `0.1`;
- API keys;
- dashboard for receipts;
- exportable audit packets;
- latency and fail-closed metrics.

## Non-Negotiable SaaS Invariants

- `SHOW / REVIEW / BLOCK` remain business-facing states.
- `PROCEED / NEEDS_REVIEW / SILENCE` remain canonical internal states.
- `SILENCE` means release denied / execution withheld / audit preserved.
- Raw prompt/answer storage is off by default or explicitly configured.
- Receipts are metadata-first.
- The gate does not become an LLM provider.

## SaaS Readiness Gate

Do not begin SaaS until:

- 2-3 design partner pilots exist;
- false positive / false negative notes exist;
- benchmark has at least 100-500 cases in the basic repo;
- license is selected;
- security boundary is documented;
- receipt retention policy is defined.
