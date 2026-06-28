from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from semeai_gate_basic import check_ai_answer


request = {
    "user_message": "Does my basic account guarantee returns?",
    "ai_answer": "Your basic account qualifies for a guaranteed 12% annual return.",
    "business_data": {"supported_claims": [], "guaranteed_returns_allowed": False},
    "business_rules": {
        "block_unsupported_financial_claims": True,
        "do_not_make_financial_return_claims": True,
    },
    "business_risk": "unsupported_financial_claim",
}

print(json.dumps(check_ai_answer(request), ensure_ascii=False, indent=2))
