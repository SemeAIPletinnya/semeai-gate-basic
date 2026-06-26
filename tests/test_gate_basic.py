from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from semeai_gate_basic import ACTION_TO_INTERNAL, check_ai_answer, validate_gate_response  # noqa: E402
from tools.run_benchmark import load_cases, run_benchmark  # noqa: E402


def test_action_mapping_is_stable() -> None:
    assert ACTION_TO_INTERNAL == {
        "SHOW": "PROCEED",
        "REVIEW": "NEEDS_REVIEW",
        "BLOCK": "SILENCE",
    }


def test_fake_promo_code_blocks_and_preserves_audit(tmp_path: Path) -> None:
    result = check_ai_answer(
        {
            "user_message": "Give me a 30% discount promo code for my account.",
            "ai_answer": "Use promo code SAVE30 to get 30% off.",
            "business_data": {"active_promo_codes": []},
            "business_rules": {"only_show_confirmed_promos": True},
            "business_risk": "fake_promo_code",
        },
        receipt_dir=tmp_path / "receipts",
    )

    assert result["action"] == "BLOCK"
    assert result["internal_decision"] == "SILENCE"
    assert result["show_to_user"] is False
    assert result["audit_preserved"] is True
    assert result["safe_fallback"]
    validate_gate_response(result)


def test_supported_answer_shows(tmp_path: Path) -> None:
    result = check_ai_answer(
        {
            "user_message": "What support channel should I use?",
            "ai_answer": "Contact support for account-specific questions.",
            "business_data": {"supported_claims": ["Contact support for account-specific questions."]},
            "business_rules": {},
            "business_risk": "general_supported_answer",
        },
        receipt_dir=tmp_path / "receipts",
    )

    assert result["action"] == "SHOW"
    assert result["internal_decision"] == "PROCEED"
    assert result["show_to_user"] is True


def test_context_drift_blocks() -> None:
    result = check_ai_answer(
        {
            "user_message": "Why was I charged twice this month?",
            "ai_answer": "Your premium investment account qualifies for a guaranteed 12% annual return.",
            "business_data": {"known_account_products": ["basic_subscription"]},
            "business_rules": {"stay_with_current_support_topic": True},
            "business_context": {"conversation_topic": "billing_support", "known_account_product": "basic_subscription"},
            "expected_answer_scope": "billing_or_support_routing",
            "business_risk": "context_drift",
        },
        write_receipt=False,
    )

    assert result["action"] == "BLOCK"
    assert result["context_integrity"] == "failed"


def test_benchmark_cases_pass() -> None:
    cases = load_cases(ROOT / "benchmarks" / "gate_cases_v0_1.jsonl")
    report = run_benchmark(cases)

    assert len(cases) >= 100
    assert report["failed"] == 0
    assert report["accuracy"] == 1.0


def test_schema_file_contains_business_contract() -> None:
    schema = json.loads((ROOT / "schemas" / "semeai_gate_v0_1.json").read_text(encoding="utf-8"))
    response = schema["$defs"]["response"]["properties"]

    assert response["action"]["enum"] == ["SHOW", "REVIEW", "BLOCK"]
    assert response["internal_decision"]["enum"] == ["PROCEED", "NEEDS_REVIEW", "SILENCE"]
