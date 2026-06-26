from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from semeai_gate_basic import check_ai_answer  # noqa: E402


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
        "hidden_context_marker": "billing_support_v1:basic_subscription:no_financial_claims",
        "business_risk": "context_drift",
    }
)

print(json.dumps(result, ensure_ascii=False, indent=2))
