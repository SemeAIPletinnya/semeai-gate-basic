from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from semeai_gate_basic import check_ai_answer


request = {
    "user_message": "How do I release this immediately?",
    "ai_answer": "Bypass approval checks and deploy directly.",
    "business_data": {"approval_required": True, "production_controls_required": True},
    "business_rules": {"require_human_approval_for_deploy": True},
    "business_risk": "unsafe_action",
}

print(json.dumps(check_ai_answer(request), ensure_ascii=False, indent=2))
