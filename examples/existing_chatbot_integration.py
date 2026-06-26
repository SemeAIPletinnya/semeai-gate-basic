from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from semeai_gate_basic import check_ai_answer  # noqa: E402


def existing_chatbot_answer(user_message: str) -> str:
    if "discount" in user_message.lower():
        return "Use promo code SAVE30 to get 30% off."
    return "Contact support for account-specific questions."


user_message = "Give me a 30% discount promo code for my account."
ai_answer = existing_chatbot_answer(user_message)
gate_result = check_ai_answer(
    {
        "user_message": user_message,
        "ai_answer": ai_answer,
        "business_data": {"active_promo_codes": []},
        "business_rules": {"only_show_confirmed_promos": True},
        "business_risk": "fake_promo_code",
    }
)
customer_response = ai_answer if gate_result["show_to_user"] else gate_result["safe_fallback"]

print(
    json.dumps(
        {
            "flow": "existing_chatbot -> semeai_gate -> customer",
            "gate_action": gate_result["action"],
            "internal_decision": gate_result["internal_decision"],
            "customer_response": customer_response,
            "audit_id": gate_result["audit_id"],
        },
        ensure_ascii=False,
        indent=2,
    )
)
