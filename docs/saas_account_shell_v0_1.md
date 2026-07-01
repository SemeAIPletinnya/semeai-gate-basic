# SemeAI Gate SaaS Account Shell v0.1

This document describes the first browser-safe SaaS account shell for SemeAI
Gate Basic.

It is a product demo surface, not a complete customer account system.

## Purpose

The static site at `gate.semeai.tech` needs to show how a hosted SemeAI Gate
product could feel:

```text
workspace -> gate checks -> review queue -> audit records -> schema -> settings
```

The shell gives early pilots a visible product shape while the core contract
remains small:

```text
user_message + ai_answer + business_data + business_rules
-> SemeAI Gate
-> SHOW / REVIEW / BLOCK
```

## Public Demo Metadata

The browser can call:

```text
GET https://api.semeai.tech/v0/demo/account
```

This endpoint returns demo-safe metadata:

- schema and API version;
- demo workspace name;
- plan/status labels;
- product links;
- manual activation placeholder;
- invariants.

It does not return API keys, customer secrets, receipt contents, or raw customer
data.

## Activation Boundary

v0.1 does not implement Stripe, card collection, invoices, subscriptions, or
automatic payment processing.

The public demo may display a manual crypto activation placeholder for early
pilots:

```text
USDT / TRC20
TJmrrUrpsRpG3u9H4FE9oVyCRPYQYEpG27
```

This is manual. A human confirmation step is required before any account or
pilot access is activated.

## Product Integration Links

The account shell intentionally links the product pieces:

- `gate.semeai.tech` for the static SaaS-visible demo;
- `api.semeai.tech/health` for the live API health check;
- `api.semeai.tech/v0/demo/check` for browser-safe demo checks;
- `api.semeai.tech/v0/check` for authenticated pilot/API checks;
- `SemeAIPletinnya/semeai-gate-basic` for the open-source adapter;
- `SemeAIPletinnya/silence-as-control` for the governance source context.

## Invariants

- Generation is not release authority.
- Business actions remain `SHOW`, `REVIEW`, `BLOCK`.
- Internal decisions remain `PROCEED`, `NEEDS_REVIEW`, `SILENCE`.
- `SHOW = PROCEED`, `REVIEW = NEEDS_REVIEW`, `BLOCK = SILENCE`.
- `SILENCE` means release denied, execution withheld, and audit preserved.
- Subscription metadata is not gate authority.
- Browser demo metadata is not authentication.
- No API key is exposed in the browser.
