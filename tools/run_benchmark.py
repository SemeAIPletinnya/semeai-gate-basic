from __future__ import annotations

import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from semeai_gate_basic import check_ai_answer

CASES_PATH = ROOT / "benchmarks" / "gate_cases_v0_2.jsonl"
OUTPUT_DIR = ROOT / "outputs" / "benchmarks"


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    cases = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                cases.append(json.loads(line))
    return cases


def run_benchmark(cases: list[dict]) -> dict:
    rows = []
    for case in cases:
        started = time.perf_counter()
        result = check_ai_answer(case["input"], receipt_dir=ROOT / "outputs" / "benchmark_receipts")
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        passed = (
            result["action"] == case["expected_action"]
            and result["internal_decision"] == case["expected_internal_decision"]
            and result["show_to_user"] == case["expected_show_to_user"]
        )
        rows.append(
            {
                "id": case["id"],
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
    latencies = sorted(row["latency_ms"] for row in rows)
    return {
        "benchmark_version": "semeai_gate_basic_benchmark_v0.2",
        "case_count": len(rows),
        "passed": passed_count,
        "failed": len(rows) - passed_count,
        "accuracy": round(passed_count / len(rows), 4) if rows else 0,
        "latency_ms": {
            "p50": latencies[len(latencies) // 2] if latencies else 0,
            "p95": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else 0,
        },
        "rows": rows,
    }


def write_report(report: dict) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "benchmark_latest.json"
    md_path = OUTPUT_DIR / "benchmark_latest.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# SemeAI Gate Basic Benchmark",
        "",
        f"- cases: {report['case_count']}",
        f"- passed: {report['passed']}",
        f"- failed: {report['failed']}",
        f"- accuracy: {report['accuracy']}",
        f"- latency p50: {report['latency_ms']['p50']} ms",
        f"- latency p95: {report['latency_ms']['p95']} ms",
        "",
        "| case | expected | actual | passed | latency ms |",
        "| --- | --- | --- | --- | ---: |",
    ]
    for row in report["rows"]:
        lines.append(f"| {row['id']} | {row['expected_action']} | {row['actual_action']} | {row['passed']} | {row['latency_ms']} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    report = run_benchmark(load_cases())
    json_path, md_path = write_report(report)
    print(f"cases={report['case_count']} passed={report['passed']} failed={report['failed']} accuracy={report['accuracy']}")
    print(f"json={json_path}")
    print(f"markdown={md_path}")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
