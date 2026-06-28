# SemeAI Gate Basic Contract

## Input

```json
{
  "user_message": "...",
  "ai_answer": "...",
  "business_data": {},
  "business_rules": {},
  "business_context": {},
  "expected_answer_scope": "...",
  "business_risk": "...",
  "metadata": {}
}
```

## Output

```json
{
  "schema_version": "0.1",
  "action": "SHOW | REVIEW | BLOCK",
  "internal_decision": "PROCEED | NEEDS_REVIEW | SILENCE",
  "show_to_user": true,
  "reason": "...",
  "business_risk": "...",
  "context_integrity": "ok | warning | failed",
  "risk_details": [],
  "next_step": "...",
  "audit_id": "...",
  "audit_preserved": true
}
```

## Mapping

```text
SHOW   = PROCEED
REVIEW = NEEDS_REVIEW
BLOCK  = SILENCE
```

Do not translate these machine values in payloads.

## Receipt

Each check writes a local metadata-only receipt by default.

The receipt stores hashes, decision metadata, and audit status. It does not
store raw user message or raw AI answer text.

## Contract Fixtures

Example request/response payloads live in:

```text
examples/contracts/
```

Check schema/runtime alignment with:

```powershell
python tools\check_contract.py
```

The contract checker verifies:

- required request fields;
- required response fields;
- `schema_version`;
- `SHOW / REVIEW / BLOCK` action values;
- `PROCEED / NEEDS_REVIEW / SILENCE` internal decisions;
- stable action-to-decision mapping.
