from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from semeai_gate_basic import (  # noqa: E402
    ACTION_TO_INTERNAL,
    SCHEMA_VERSION,
    check_ai_answer,
    validate_gate_request,
    validate_gate_response,
)
from semeai_gate_basic.gate import REQUIRED_REQUEST_KEYS, REQUIRED_RESPONSE_KEYS  # noqa: E402


SCHEMA_PATH = ROOT / "schemas" / "semeai_gate_v0_1.json"
CONTRACT_EXAMPLES = ROOT / "examples" / "contracts"


EXPECTED_REQUEST_ACTIONS = {
    "block_fake_promo_request.json": "BLOCK",
    "review_uncertain_claim_request.json": "REVIEW",
    "show_supported_answer_request.json": "SHOW",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def check_schema_alignment(schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    defs = schema.get("$defs", {})
    request = defs.get("request", {})
    response = defs.get("response", {})

    schema_request_required = set(request.get("required", []))
    schema_response_required = set(response.get("required", []))
    if schema_request_required != REQUIRED_REQUEST_KEYS:
        errors.append(
            "request required mismatch: "
            f"schema={sorted(schema_request_required)} runtime={sorted(REQUIRED_REQUEST_KEYS)}"
        )
    if schema_response_required != REQUIRED_RESPONSE_KEYS:
        errors.append(
            "response required mismatch: "
            f"schema={sorted(schema_response_required)} runtime={sorted(REQUIRED_RESPONSE_KEYS)}"
        )

    action_enum = set(response.get("properties", {}).get("action", {}).get("enum", []))
    internal_enum = set(response.get("properties", {}).get("internal_decision", {}).get("enum", []))
    if action_enum != set(ACTION_TO_INTERNAL):
        errors.append(f"action enum mismatch: schema={sorted(action_enum)} runtime={sorted(ACTION_TO_INTERNAL)}")
    if internal_enum != set(ACTION_TO_INTERNAL.values()):
        errors.append(
            "internal decision enum mismatch: "
            f"schema={sorted(internal_enum)} runtime={sorted(ACTION_TO_INTERNAL.values())}"
        )

    schema_version = response.get("properties", {}).get("schema_version", {}).get("const")
    if schema_version != SCHEMA_VERSION:
        errors.append(f"schema_version mismatch: schema={schema_version!r} runtime={SCHEMA_VERSION!r}")

    return errors


def check_contract_examples() -> list[str]:
    errors: list[str] = []
    for filename, expected_action in EXPECTED_REQUEST_ACTIONS.items():
        path = CONTRACT_EXAMPLES / filename
        request = load_json(path)
        try:
            validate_gate_request(request)
            result = check_ai_answer(request, receipt_dir=ROOT / "outputs" / "contract_check_receipts")
            validate_gate_response(result)
        except Exception as exc:  # pragma: no cover - surfaced by CLI output
            errors.append(f"{filename} failed validation: {exc}")
            continue
        if result["action"] != expected_action:
            errors.append(f"{filename} expected {expected_action}, got {result['action']}")
        if ACTION_TO_INTERNAL[result["action"]] != result["internal_decision"]:
            errors.append(f"{filename} has unstable action/internal mapping")

    response_example = load_json(CONTRACT_EXAMPLES / "response_block_example.json")
    try:
        validate_gate_response(response_example)
    except Exception as exc:  # pragma: no cover - surfaced by CLI output
        errors.append(f"response_block_example.json failed validation: {exc}")

    return errors


def main() -> int:
    schema = load_json(SCHEMA_PATH)
    errors = [*check_schema_alignment(schema), *check_contract_examples()]
    if errors:
        print("contract_check=failed")
        for error in errors:
            print(f"- {error}")
        return 1
    print("contract_check=passed")
    print(f"schema_version={SCHEMA_VERSION}")
    print(f"request_fixtures={len(EXPECTED_REQUEST_ACTIONS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
