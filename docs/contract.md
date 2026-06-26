# SemeAI Gate Contract v0.1

SemeAI Gate Basic receives an AI answer and returns a business action:

```text
SHOW = PROCEED
REVIEW = NEEDS_REVIEW
BLOCK = SILENCE
```

Machine payload values must remain canonical. Do not translate `PROCEED`,
`NEEDS_REVIEW`, or `SILENCE` in JSON payloads.

## Input

- `user_message`
- `ai_answer`
- `business_data`
- `business_rules`
- `business_context`
- `hidden_context_marker`
- `expected_answer_scope`
- `business_risk`
- `metadata`

## Output

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

## Release Meaning

- `SHOW`: host product may show the AI answer.
- `REVIEW`: host product should route the answer to a human/operator queue.
- `BLOCK`: host product should not show the AI answer; use fallback or support handoff.

`BLOCK / SILENCE` suppresses release and preserves audit. It is not deletion.
