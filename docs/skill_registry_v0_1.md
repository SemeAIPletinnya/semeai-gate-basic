# Governed Workspace Skill Registry v0.1

The Workspace skill registry retains bounded candidate identity and evaluation
evidence for one authenticated account workspace.

It does not store raw skill source, install a skill, create a marketplace, or
grant runtime release authority.

## Contract

Authenticated account/session endpoints:

- `GET /v0/workspace/skills`
- `GET /v0/workspace/skills/{skill_record_id}`
- `POST /v0/workspace/skills`

The POST body retains:

- `skill_id`;
- `name`;
- `version`;
- `skill_hash` (SHA-256);
- bounded `evidence_cases`;
- `evaluated_domains`;
- `failures`;
- `limitations`;
- declared evaluation context and provenance.

The server always creates the candidate in `REVIEW`. Candidate input cannot set
an admission decision, availability, a receipt, or raw skill content. Repeating
the same workspace + skill ID + version + hash is idempotent and returns the
existing immutable candidate snapshot.

## Admission authority

Skill decisions use a separate operator endpoint:

`POST /v0/operator/workspaces/{workspace_id}/skills/{skill_record_id}/decision`

The endpoint requires the dedicated `SEMEAI_GATE_SKILL_AUTHORITY_KEY`. It accepts
`REVIEW`, `WITHHELD`, or `ADMITTED` plus a reason. `ADMITTED` remains disabled
unless the operator explicitly sets:

`SEMEAI_GATE_SKILL_ADMISSION_ENABLED=true`

This authority is only skill-admission authority. It is not SaC/PoR runtime
release authority and cannot change `PROCEED / NEEDS_REVIEW / SILENCE`.

## Receipt boundary

Every operator decision creates a separate immutable receipt with:

- `receipt_type: skill_admission_decision`;
- candidate identity;
- evidence snapshot hash;
- decision, reason, timestamp, and authority fingerprint;
- canonical SHA-256 integrity hash.

The receipt is a retained decision trace, not a signature, certification, or
proof of universal skill validity. Skill receipts are stored separately from
runtime release-decision and execution/result receipts.

## Storage

By default records are stored beneath:

`SEMEAI_GATE_ACCOUNT_DIR/skill_registry`

`SEMEAI_GATE_SKILL_DIR` may override that location. Records remain scoped by the
authenticated immutable workspace ID. The API never returns local storage paths.

## Environment

```text
SEMEAI_GATE_SKILL_DIR=
SEMEAI_GATE_SKILL_AUTHORITY_KEY=
SEMEAI_GATE_SKILL_ADMISSION_ENABLED=false
```

Do not commit real keys.
