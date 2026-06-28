from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from semeai_gate_basic import check_ai_answer


def existing_chatbot_answer(user_message: str) -> str:
    """Placeholder for the host product's existing LLM/chatbot answer."""

    if "discount" in user_message.lower() or "promo" in user_message.lower():
        return "Use promo code SAVE30 to get 30% off."
    return "Support can help check account-specific questions."


def load_business_context(user_message: str) -> dict:
    """Placeholder for product data lookup before release."""

    return {
        "business_data": {"active_promo_codes": []},
        "business_rules": {"only_show_confirmed_promos": True},
        "business_context": {
            "conversation_topic": "billing_support",
            "active_promotions_available": False,
            "expected_answer_scope": "billing_or_support_routing",
        },
        "business_risk": "fake_promo_code",
    }


def release_to_customer(user_message: str, *, receipt_dir: str | Path | None = None) -> dict:
    ai_answer = existing_chatbot_answer(user_message)
    context = load_business_context(user_message)
    gate_result = check_ai_answer(
        {
            "user_message": user_message,
            "ai_answer": ai_answer,
            **context,
        },
        receipt_dir=receipt_dir,
    )

    if gate_result["action"] == "SHOW":
        customer_response = ai_answer
        host_next_step = "show_ai_answer"
    elif gate_result["action"] == "REVIEW":
        customer_response = "A support operator should review this answer before release."
        host_next_step = "route_to_human_review"
    else:
        customer_response = gate_result["safe_fallback"]
        host_next_step = "show_safe_fallback"

    return {
        "boundary": "existing_chatbot -> semeai_gate -> customer",
        "user_message": user_message,
        "ai_answer_generated": True,
        "gate_action": gate_result["action"],
        "internal_decision": gate_result["internal_decision"],
        "show_to_user": gate_result["show_to_user"],
        "host_next_step": host_next_step,
        "customer_response": customer_response,
        "audit_id": gate_result["audit_id"],
        "audit_preserved": gate_result["audit_preserved"],
    }


if __name__ == "__main__":
    print(
        json.dumps(
            release_to_customer("Give me a 30% discount promo code for my account."),
            ensure_ascii=False,
            indent=2,
        )
    )
