from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from semeai_gate_basic import check_ai_answer


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
if gate_result["action"] == "SHOW":
    customer_response = ai_answer
    host_next_step = "show_ai_answer"
elif gate_result["action"] == "REVIEW":
    customer_response = "A support operator should review this answer before release."
    host_next_step = "route_to_human_review"
else:
    customer_response = gate_result["safe_fallback"]
    host_next_step = "show_safe_fallback"

print(
    json.dumps(
        {
            "flow": "existing_chatbot -> semeai_gate -> customer",
            "gate_action": gate_result["action"],
            "internal_decision": gate_result["internal_decision"],
            "host_next_step": host_next_step,
            "customer_response": customer_response,
            "audit_id": gate_result["audit_id"],
            "audit_preserved": gate_result["audit_preserved"],
        },
        ensure_ascii=False,
        indent=2,
    )
)
