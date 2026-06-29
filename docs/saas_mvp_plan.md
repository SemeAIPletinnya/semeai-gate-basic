# SaaS MVP Plan

This document describes the SaaS direction for SemeAI Gate without turning the
basic repository into a hosted service.

The current repo remains:

```text
open-source core + local examples + contract + benchmark
```

The next commercial shape is:

```text
hosted check endpoint + simple operator dashboard + audit list
```

## Strategy

Do not build a full SaaS platform first.

Build in this order:

1. SaaS-visible static demo;
2. API contract for `POST /check`;
3. design-partner pilot;
4. minimal hosted endpoint;
5. receipt/audit dashboard;
6. authentication and billing only after demand is proven.

## What The SaaS MVP Should Do

The first hosted MVP should do one thing:

```text
AI answer + business data + rules -> SHOW / REVIEW / BLOCK + audit id
```

Minimum features:

- paste or send a user message;
- paste or send an AI answer;
- provide business data and rules;
- return `SHOW`, `REVIEW`, or `BLOCK`;
- show reason, risk details, safe fallback, and audit id;
- list recent checks in a simple dashboard.

## What To Avoid In The First SaaS

Do not start with:

- billing;
- multi-tenant enterprise admin;
- SOC2/compliance claims;
- customer data lake;
- complex prompt management;
- model hosting;
- autonomous remediation;
- external LLM API dependency.

## SaaS MVP Boundary

The SaaS should be a release-control layer, not a chatbot.

```text
existing chatbot / LLM app
-> SemeAI Gate SaaS
-> SHOW / REVIEW / BLOCK
-> host product action
```

The host product remains responsible for:

- generating the AI answer;
- supplying business data and rules;
- deciding what the user sees after the gate result;
- managing account/customer identity.

Machine payload values should remain canonical and untranslated:

```text
SHOW / REVIEW / BLOCK
PROCEED / NEEDS_REVIEW / SILENCE
```

## First Endpoint

```text
POST /check
```

Input:

- `user_message`
- `ai_answer`
- `business_data`
- `business_rules`
- `business_context`
- `expected_answer_scope`
- `business_risk`
- `metadata`

Output:

- `schema_version`
- `action`
- `internal_decision`
- `show_to_user`
- `reason`
- `business_risk`
- `context_integrity`
- `risk_details`
- `next_step`
- `audit_id`
- `audit_preserved`
- `safe_fallback`

## First Dashboard

Minimum dashboard cards:

- total checks;
- `SHOW` count;
- `REVIEW` count;
- `BLOCK` count;
- latest audit id;
- latest blocked reason;
- recent checks table.

## Pilot-To-SaaS Decision

Build the hosted MVP only when at least one of these is true:

- a design partner wants to test against their chatbot flow;
- repeated outreach feedback says "we need an endpoint";
- local demo is clear but integration friction is too high;
- a team asks for receipt/audit visibility across multiple checks.

## Non-Claims

The SaaS MVP must not claim:

- compliance certification;
- universal hallucination detection;
- autonomous approval authority;
- replacement for human review;
- model-level safety proof.

It may claim:

```text
SemeAI Gate checks AI answers against supplied business data and rules before
release, returning SHOW / REVIEW / BLOCK and preserving an audit id.
```
