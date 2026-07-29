from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from semeai_gate_basic.public_archive import (
    build_archive_candidate,
    load_public_index,
    release_public_archive_answer,
)


PILOT_TASKS = [
    {
        "task_id": "authority",
        "question": "What is the Gate release authority?",
        "routeContext": "gate",
        "expected_source": "public:gate:runtime-decision-contract:v0.1",
    },
    {
        "task_id": "skill-admission",
        "question": "What is the GET JOB admission status?",
        "routeContext": "skills",
        "expected_source": "public:skills:registry:v0.1",
    },
    {
        "task_id": "benchmark",
        "question": "What does the public repository benchmark fixture report?",
        "routeContext": "benchmark",
        "expected_source": "public:benchmark:canonical-fallback:v1",
    },
    {
        "task_id": "engineering-book",
        "question": "What does the Engineering Book cover about receipts?",
        "routeContext": "home",
        "expected_source": "public:book:engineering:v0.1",
    },
    {
        "task_id": "genesis",
        "question": "What public Genesis evidence describes historical admission?",
        "routeContext": "genesis",
        "expected_source": "public:genesis:chronicle:v04",
    },
    {
        "task_id": "no-evidence",
        "question": "qzvxyl orbital marmalade",
        "routeContext": "home",
        "expected_source": None,
    },
]


def run_pilot() -> dict[str, Any]:
    """Run a local contract dry run. This is not a substitute for human pilot evidence."""

    index = load_public_index()
    known_sources = {entry["sourceId"] for entry in index["entries"]}
    results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="semeai-axiom-pilot-") as receipt_dir:
        for task in PILOT_TASKS:
            payload = {
                "question": task["question"],
                "routeContext": task["routeContext"],
                "limit": 5,
            }
            built = build_archive_candidate(payload)
            started = time.perf_counter()
            response = release_public_archive_answer(payload, receipt_dir=receipt_dir)
            latency_ms = round((time.perf_counter() - started) * 1_000, 3)
            evidence = response["evidenceBundle"]["evidence"]
            source_ids = [item["sourceId"] for item in evidence]
            expected_source = task["expected_source"]
            no_evidence_expected = expected_source is None
            citations_resolve = all(source_id in known_sources for source_id in source_ids)
            exact_release = (
                response["releasedAnswer"] == built["candidate"]["candidateText"]
                if built["candidate"]
                else response["releasedAnswer"] is None
            )
            expected_source_found = (
                response["evidenceBundle"]["noEvidence"] is True
                if no_evidence_expected
                else bool(source_ids) and source_ids[0] == expected_source
            )
            gate_contract = (
                response["release"]["gateEvaluated"] is False
                and response["release"]["decisionReceiptId"] is None
                if no_evidence_expected
                else response["release"]["action"] == "SHOW"
                and response["release"]["internalDecision"] == "PROCEED"
                and response["release"]["receipt_id"]
                == response["release"]["decisionReceiptId"]
                and response["release"]["executionReceiptId"] is None
            )
            passed = all(
                (
                    citations_resolve,
                    exact_release,
                    expected_source_found,
                    gate_contract,
                )
            )
            results.append(
                {
                    "taskId": task["task_id"],
                    "routeContext": task["routeContext"],
                    "expectedSource": expected_source,
                    "topSource": source_ids[0] if source_ids else None,
                    "sourceCount": len(source_ids),
                    "noEvidence": response["evidenceBundle"]["noEvidence"],
                    "gateAction": response["release"]["action"],
                    "internalDecision": response["release"]["internalDecision"],
                    "decisionReceiptCreated": bool(response["release"]["decisionReceiptId"]),
                    "executionReceiptCreated": bool(response["release"]["executionReceiptId"]),
                    "citationsResolve": citations_resolve,
                    "releasedAnswerMatchesCandidate": exact_release,
                    "latencyMs": latency_ms,
                    "passed": passed,
                }
            )

    latencies = [row["latencyMs"] for row in results]
    return {
        "schemaVersion": "semeai.axiom-public-pilot-dry-run.v0.1",
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "status": "DRY_RUN_NOT_HUMAN_EVALUATION",
        "onlineIngestionEnabled": False,
        "externalModelCalls": 0,
        "privateArchiveIncluded": False,
        "tasks": results,
        "summary": {
            "tasks": len(results),
            "passed": sum(1 for row in results if row["passed"]),
            "failed": sum(1 for row in results if not row["passed"]),
            "sourceCoverage": sorted(
                {
                    row["topSource"]
                    for row in results
                    if isinstance(row.get("topSource"), str)
                }
            ),
            "medianLatencyMs": round(statistics.median(latencies), 3),
            "maximumLatencyMs": max(latencies),
            "humanPilotCompleted": False,
        },
    }


def _markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    rows = [
        "# Axiom public archive pilot dry run",
        "",
        f"Status: `{report['status']}`",
        "",
        (
            f"{summary['passed']}/{summary['tasks']} contract tasks passed. "
            f"Median local latency: {summary['medianLatencyMs']} ms; "
            f"maximum: {summary['maximumLatencyMs']} ms."
        ),
        "",
        "| Task | Route | Top source | Gate | Latency (ms) | Result |",
        "| --- | --- | --- | --- | ---: | --- |",
    ]
    for row in report["tasks"]:
        gate = (
            f"{row['gateAction']} / {row['internalDecision']}"
            if row["gateAction"]
            else "NOT EVALUATED"
        )
        rows.append(
            "| {task} | {route} | {source} | {gate} | {latency} | {result} |".format(
                task=row["taskId"],
                route=row["routeContext"],
                source=row["topSource"] or "NO EVIDENCE",
                gate=gate,
                latency=row["latencyMs"],
                result="PASS" if row["passed"] else "FAIL",
            )
        )
    rows.extend(
        [
            "",
            "This artifact verifies the deterministic local contract only. It does not claim",
            "that a human usability pilot, production deployment, or private Workspace",
            "evaluation has occurred.",
        ]
    )
    return "\n".join(rows) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the bounded Axiom public archive pilot dry run.")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    report = run_pilot()
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    print(serialized)

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(serialized + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(_markdown(report), encoding="utf-8")
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
