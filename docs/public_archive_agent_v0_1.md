# Public archive agent v0.1

`POST /v0/archive/query` is a deterministic, PUBLIC-only archive query path for
the Axiom shell. It performs four bounded steps:

```text
question
-> frozen public evidence index
-> deterministic candidate
-> existing SemeAI Gate
-> exact candidate for SHOW, otherwise null
```

It does not call an LLM, network service, private archive, raw archive, or
online-ingestion source.

## Request

```json
{
  "question": "What is the Gate release authority?",
  "routeContext": "gate",
  "limit": 5
}
```

`question` is required and limited to 256 characters. `limit` is optional and
must be from 1 through 8.

## Authority boundary

- Retrieval is not truth.
- Retrieved evidence is marked `UNTRUSTED_DATA`.
- Generation creates a candidate, not a released answer.
- The existing SaC/PoR Gate remains the final release authority.
- Public actions remain `SHOW`, `REVIEW`, and `BLOCK`; their internal states
  remain `PROCEED`, `NEEDS_REVIEW`, and `SILENCE`.
- `SILENCE` means release denied, execution withheld, and audit preserved.
- `releasedAnswer` is the exact candidate only for `SHOW`; it is `null` for
  `REVIEW` or `BLOCK`.
- No fallback or warning text substitutes for a held candidate.
- The release-decision receipt ID is returned as both `decisionReceiptId` and
  legacy-compatible `receipt_id`.
- The persisted decision receipt carries an allowlisted `candidate_trace` with
  candidate ID/hash, route context, and public source IDs. This trace metadata
  is explicitly not Gate authority and stores no raw question or answer.
- `executionReceiptId` remains separate and `null` because this endpoint does
  not execute a downstream action.

When retrieval finds no matching evidence, no candidate is generated and the
Gate is not invoked. The response states that condition without manufacturing
an answer or receipt.

## Frozen index

The packaged `semeai_gate_basic/data/axiom_public_evidence.json` mirrors the
public-site index with SHA-256
`b2c681a99141ca69125cf3704f3517a00ef8770575cf7ac69371f0ae7a29b9cf`.
Runtime validation rejects private entries, raw-archive inclusion, online
ingestion, duplicate source IDs, incomplete provenance, or authority drift.

The public endpoint shares the process-local public-demo abuse guard. It does
not count against Workspace quota and stores only a short hash of the client
identity in memory for the active rate-limit window.
