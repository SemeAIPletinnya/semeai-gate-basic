from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from semeai_gate_basic import check_ai_answer  # noqa: E402


CASES_PATH = ROOT / "benchmarks" / "gate_cases_v0_1.jsonl"
OUTPUT_DIR = ROOT / "output" / "benchmarks"


def load_cases(path: str | Path = CASES_PATH) -> list[dict[str, Any]]:
    cases = []
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        case = json.loads(line)
        for key in ("id", "category", "input", "expected_action", "expected_internal_decision", "expected_show_to_user"):
            if key not in case:
                raise ValueError(f"{path}:{line_no} missing {key}")
        cases.append(case)
    return cases


def run_benchmark(cases: list[dict[str, Any]]) -> dict[str, Any]:
    receipt_dir = OUTPUT_DIR / "receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    latencies = []
    confusion = Counter()
    for case in cases:
        started = perf_counter()
        result = check_ai_answer(case["input"], receipt_dir=receipt_dir)
        elapsed_ms = round((perf_counter() - started) * 1000, 2)
        passed = (
            result["action"] == case["expected_action"]
            and result["internal_decision"] == case["expected_internal_decision"]
            and bool(result["show_to_user"]) == bool(case["expected_show_to_user"])
        )
        confusion[(case["expected_action"], result["action"])] += 1
        latencies.append(elapsed_ms)
        rows.append(
            {
                "id": case["id"],
                "category": case["category"],
                "expected_action": case["expected_action"],
                "actual_action": result["action"],
                "expected_internal_decision": case["expected_internal_decision"],
                "actual_internal_decision": result["internal_decision"],
                "passed": passed,
                "latency_ms": elapsed_ms,
                "audit_id": result["audit_id"],
            }
        )
    passed_count = sum(1 for row in rows if row["passed"])
    return {
        "benchmark_version": "semeai_gate_basic_benchmark_v0.1",
        "case_count": len(rows),
        "passed": passed_count,
        "failed": len(rows) - passed_count,
        "accuracy": round(passed_count / len(rows), 4) if rows else 0,
        "latency_ms": _latency(latencies),
        "confusion_by_action": {f"{expected}->{actual}": count for (expected, actual), count in sorted(confusion.items())},
        "rows": rows,
        "notes": [
            "Synthetic deterministic benchmark cases.",
            "No customer data.",
            "Raw prompts and answers are not copied into this report.",
        ],
    }


def write_outputs(report: dict[str, Any]) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "gate_benchmark_latest.json"
    md_path = OUTPUT_DIR / "gate_benchmark_latest.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, md_path


def _latency(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"count": 0, "min": 0, "p50": 0, "p95": 0, "max": 0, "mean": 0}
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return {
        "count": len(values),
        "min": min(values),
        "p50": statistics.median(values),
        "p95": ordered[p95_index],
        "max": max(values),
        "mean": round(statistics.mean(values), 2),
    }


def _markdown(report: dict[str, Any]) -> str:
    latency = report["latency_ms"]
    lines = [
        "# SemeAI Gate Basic Benchmark",
        "",
        f"- Cases: {report['case_count']}",
        f"- Passed: {report['passed']}",
        f"- Failed: {report['failed']}",
        f"- Accuracy: {report['accuracy']}",
        f"- Latency p50: {latency['p50']} ms",
        f"- Latency p95: {latency['p95']} ms",
        "",
        "| Case | Category | Expected | Actual | Passed |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in report["rows"]:
        lines.append(f"| {row['id']} | {row['category']} | {row['expected_action']} | {row['actual_action']} | {row['passed']} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    report = run_benchmark(load_cases())
    json_path, md_path = write_outputs(report)
    print(f"cases={report['case_count']} passed={report['passed']} failed={report['failed']} accuracy={report['accuracy']}")
    print(f"latency_p50_ms={report['latency_ms']['p50']} latency_p95_ms={report['latency_ms']['p95']}")
    print(f"json={json_path}")
    print(f"markdown={md_path}")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
