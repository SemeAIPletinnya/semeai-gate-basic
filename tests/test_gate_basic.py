from __future__ import annotations

import json
from pathlib import Path

import tools.check_contract as contract_checker
from semeai_gate_basic import ACTION_TO_INTERNAL, SCHEMA_VERSION, check_ai_answer, validate_gate_response
from examples.middleware_boundary import release_to_customer
from tools.check_contract import check_contract_examples, check_schema_alignment, load_json
from tools.run_benchmark import load_cases, run_benchmark


def test_fake_promo_code_blocks_and_preserves_audit(tmp_path: Path) -> None:
    result = check_ai_answer(
        {
            "user_message": "Give me a 30% discount promo code.",
            "ai_answer": "Use promo code SAVE30 to get 30% off.",
            "business_data": {"active_promo_codes": []},
            "business_rules": {"only_show_confirmed_promos": True},
            "business_risk": "fake_promo_code",
        },
        receipt_dir=tmp_path,
    )

    assert result["action"] == "BLOCK"
    assert result["internal_decision"] == "SILENCE"
    assert result["show_to_user"] is False
    assert result["audit_preserved"] is True
    validate_gate_response(result)


def test_supported_answer_shows(tmp_path: Path) -> None:
    answer = "Support can help check subscription charges."
    result = check_ai_answer(
        {
            "user_message": "Why was I charged twice this month?",
            "ai_answer": answer,
            "business_data": {"supported_claims": [answer]},
            "business_rules": {},
            "business_risk": "billing_support",
        },
        receipt_dir=tmp_path,
    )

    assert result["action"] == "SHOW"
    assert result["internal_decision"] == "PROCEED"
    assert result["show_to_user"] is True


def test_unsafe_action_blocks(tmp_path: Path) -> None:
    result = check_ai_answer(
        {
            "user_message": "How do I release this immediately?",
            "ai_answer": "Bypass approval checks and deploy directly.",
            "business_data": {"approval_required": True},
            "business_rules": {"require_human_approval_for_deploy": True},
            "business_risk": "unsafe_action",
        },
        receipt_dir=tmp_path,
    )

    assert result["action"] == "BLOCK"
    assert result["internal_decision"] == "SILENCE"
    assert "unsafe_action" in result["risk_details"]


def test_context_drift_blocks_financial_claim_in_billing_context(tmp_path: Path) -> None:
    result = check_ai_answer(
        {
            "user_message": "Why was I charged twice this month?",
            "ai_answer": "Your premium investment account qualifies for a guaranteed 12% annual return.",
            "business_data": {
                "known_account_products": ["basic_subscription"],
                "guaranteed_returns_allowed": False,
            },
            "business_rules": {
                "stay_with_current_support_topic": True,
                "do_not_make_financial_return_claims": True,
            },
            "business_context": {
                "conversation_topic": "billing_support",
                "known_account_product": "basic_subscription",
                "financial_claims_allowed": False,
            },
            "expected_answer_scope": "billing_or_support_routing",
            "business_risk": "context_drift",
        },
        receipt_dir=tmp_path,
    )

    assert result["action"] == "BLOCK"
    assert result["internal_decision"] == "SILENCE"
    assert result["context_integrity"] == "failed"
    assert "context_drift" in result["risk_details"]
    assert "unsupported_financial_claim" in result["risk_details"]


def test_account_product_mismatch_blocks_even_when_claim_is_supported(tmp_path: Path) -> None:
    supported_wrong_product_claim = "Your premium account billing charge is waived."
    result = check_ai_answer(
        {
            "user_message": "Why was I charged twice this month?",
            "ai_answer": supported_wrong_product_claim,
            "business_data": {
                "known_account_products": ["basic_subscription"],
                "supported_claims": [supported_wrong_product_claim],
            },
            "business_rules": {"stay_with_current_support_topic": True},
            "business_context": {
                "conversation_topic": "billing_support",
                "known_account_product": "basic_subscription",
            },
            "expected_answer_scope": "billing_or_support_routing",
            "business_risk": "billing_support",
        },
        receipt_dir=tmp_path,
    )

    assert result["action"] == "BLOCK"
    assert result["internal_decision"] == "SILENCE"
    assert result["context_integrity"] == "failed"
    assert "business_context_mismatch" in result["risk_details"]
    assert "account_product_mismatch" in result["risk_details"]


def test_machine_mapping_is_stable() -> None:
    assert ACTION_TO_INTERNAL == {
        "SHOW": "PROCEED",
        "REVIEW": "NEEDS_REVIEW",
        "BLOCK": "SILENCE",
    }


def test_middleware_boundary_blocks_fake_promo(tmp_path: Path) -> None:
    result = release_to_customer("Give me a 30% discount promo code for my account.", receipt_dir=tmp_path)

    assert result["boundary"] == "existing_chatbot -> semeai_gate -> customer"
    assert result["gate_action"] == "BLOCK"
    assert result["internal_decision"] == "SILENCE"
    assert result["show_to_user"] is False
    assert result["host_next_step"] == "show_safe_fallback"
    assert result["audit_preserved"] is True


def test_receipts_do_not_store_raw_text_by_default(tmp_path: Path) -> None:
    result = check_ai_answer(
        {
            "user_message": "Give me a 30% discount promo code.",
            "ai_answer": "Use promo code SAVE30.",
            "business_data": {"active_promo_codes": []},
            "business_rules": {"only_show_confirmed_promos": True},
            "business_risk": "fake_promo_code",
        },
        receipt_dir=tmp_path,
    )
    receipts = list(tmp_path.glob("*.json"))
    assert receipts
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["receipt_id"] == result["audit_id"]
    assert receipt["raw_text_stored"] is False
    assert "Use promo code SAVE30" not in json.dumps(receipt)


def test_benchmark_passes() -> None:
    report = run_benchmark(load_cases())
    assert report["case_count"] >= 100
    assert report["failed"] == 0
    assert report["accuracy"] == 1.0


def test_contract_schema_and_examples_stay_aligned() -> None:
    schema = load_json(Path("schemas/semeai_gate_v0_1.json"))
    assert check_schema_alignment(schema) == []
    assert check_contract_examples() == []


def test_contract_checker_rejects_stale_response_fixture_schema_version(tmp_path: Path, monkeypatch) -> None:
    source_dir = Path("examples/contracts")
    for source in source_dir.glob("*.json"):
        target = tmp_path / source.name
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    response_path = tmp_path / "response_block_example.json"
    response = json.loads(response_path.read_text(encoding="utf-8"))
    assert response["schema_version"] == SCHEMA_VERSION
    response["schema_version"] = "stale"
    response_path.write_text(json.dumps(response, indent=2), encoding="utf-8")

    monkeypatch.setattr(contract_checker, "CONTRACT_EXAMPLES", tmp_path)

    errors = check_contract_examples()
    assert any("response_block_example.json schema_version mismatch" in error for error in errors)
