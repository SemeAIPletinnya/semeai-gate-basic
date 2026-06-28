# UI Demo Recommendation

The basic repository should start without a heavy UI.

First ship:

- Python SDK;
- Node SDK;
- JSON schema;
- three runnable examples;
- small benchmark;
- local receipts.

Then add a minimal UI demo if the contract stays stable.

## Recommended UI

A single-page static demo is enough:

```text
User Message
AI Answer
Business Data
Business Rules
SemeAI Gate Result
Receipt
```

Do not build a large dashboard first. The UI should make one thing obvious:

```text
AI invented SAVE30 -> Gate returned BLOCK -> audit receipt preserved
```

The full Evidence Workspace belongs in SemeAI Local. The basic repo should stay
small and easy to audit.
