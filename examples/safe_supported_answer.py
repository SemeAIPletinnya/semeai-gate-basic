from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from semeai_gate_basic import check_ai_answer


answer = "Support can help check subscription charges."
request = {
    "user_message": "Why was I charged twice this month?",
    "ai_answer": answer,
    "business_data": {
        "supported_claims": [answer],
        "known_account_products": ["basic_subscription"],
    },
    "business_rules": {"stay_with_current_support_topic": True},
    "business_context": {
        "conversation_topic": "billing_support",
        "known_account_product": "basic_subscription",
    },
    "expected_answer_scope": "billing_or_support_routing",
    "business_risk": "billing_support",
}

print(json.dumps(check_ai_answer(request), ensure_ascii=False, indent=2))
