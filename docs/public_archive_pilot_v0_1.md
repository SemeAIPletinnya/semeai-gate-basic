# Axiom public archive pilot v0.1

The first bounded pilot has two deliberately separate layers.

## Local contract dry run

Run:

```powershell
python tools\run_public_archive_pilot.py `
  --json-output outputs\axiom_public_pilot.json `
  --markdown-output outputs\axiom_public_pilot.md
```

The six fixed tasks cover Gate authority, Skill Forge admission state,
Repository Evidence Benchmark, Engineering Book receipts, Genesis historical
admission, and truthful no-evidence behavior. The runner measures local latency,
source coverage, citation identity, exact candidate/released-answer equality,
Gate mapping, decision-receipt creation, and absence of an execution receipt.

The output is explicitly labeled `DRY_RUN_NOT_HUMAN_EVALUATION`. It makes no
claim about production deployment, real-user usability, or private Workspace
behavior.

## Human pilot (held for release and participants)

After both draft PRs pass independent release authority and production smoke,
run the same tasks with 3–5 participants. Record:

- whether the participant finds an evidence-backed answer;
- whether they can identify the cited source and its provenance;
- whether they correctly distinguish the candidate, Gate decision, and release;
- whether they understand that `SILENCE` preserves the audit;
- completion time and any route-context ambiguity;
- every no-evidence, wrong-source, stale-context, or citation failure.

Do not retain raw participant questions beyond the approved pilot retention
contract. A human pilot result must remain a separate admitted artifact; the
local dry run does not auto-admit it.
