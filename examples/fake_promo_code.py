from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from semeai_gate_basic import check_ai_answer  # noqa: E402


result = check_ai_answer(
    {
        "user_message": "Give me a 30% discount promo code for my account.",
        "ai_answer": "Use promo code SAVE30 to get 30% off.",
        "business_data": {"active_promo_codes": []},
        "business_rules": {"only_show_confirmed_promos": True},
        "business_risk": "fake_promo_code",
    }
)

print(json.dumps(result, ensure_ascii=False, indent=2))
