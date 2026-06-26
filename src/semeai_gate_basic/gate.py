from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "0.1"
ACTION_TO_INTERNAL = {"SHOW": "PROCEED", "REVIEW": "NEEDS_REVIEW", "BLOCK": "SILENCE"}
INTERNAL_TO_ACTION = {value: key for key, value in ACTION_TO_INTERNAL.items()}
DECISION_PRIORITY = {"PROCEED": 0, "NEEDS_REVIEW": 1, "SILENCE": 2}
REQUIRED_REQUEST_KEYS = {"user_message", "ai_answer", "business_data", "business_rules", "business_risk"}
REQUIRED_RESPONSE_KEYS = {
    "schema_version",
    "action",
    "internal_decision",
    "show_to_user",
    "reason",
    "business_risk",
    "context_integrity",
    "risk_details",
    "next_step",
    "audit_id",
    "audit_preserved",
}


def check_ai_answer(
    request: dict[str, Any],
    *,
    receipt_dir: str | Path | None = None,
    write_receipt: bool = True,
) -> dict[str, Any]:
    """Check one AI answer through the SemeAI Gate Basic contract."""

    validate_gate_request(request)
    normalized = _normalize_request(request)
    business = _evaluate_business_rules(normalized)
    context = _evaluate_context_integrity(normalized)
    decision = _strictest_decision(business["decision"], context["decision"])
    action = INTERNAL_TO_ACTION[decision]
    show_to_user = decision == "PROCEED"
    reason = _select_reason(decision, business, context)
    risk_details = _dedupe([*business["risk_details"], *context["risk_details"]])
    receipt = (
        _write_receipt(normalized, decision, reason, risk_details, receipt_dir)
        if write_receipt
        else {"audit_id": None, "status": "disabled", "path": None}
    )
    result = {
        "schema_version": SCHEMA_VERSION,
        "action": action,
        "internal_decision": decision,
        "show_to_user": show_to_user,
        "reason": reason,
        "business_risk": normalized["business_risk"],
        "context_integrity": context["context_integrity"],
        "context_drift": context["context_drift"],
        "business_context_mismatch": context["business_context_mismatch"],
        "risk_details": risk_details,
        "next_step": _next_step(action, normalized["business_risk"], context),
        "audit_id": receipt["audit_id"],
        "audit_preserved": receipt["status"] == "saved",
        "safe_fallback": None if show_to_user else _safe_fallback(normalized["business_risk"]),
        "technical_details": {
            "canonical_mapping": ACTION_TO_INTERNAL,
            "receipt_path": receipt["path"],
            "candidate_hash": _sha256(normalized["ai_answer"]),
            "released_output_hash": _sha256(normalized["ai_answer"]) if show_to_user else None,
        },
    }
    validate_gate_response(result)
    return result


def validate_gate_request(request: dict[str, Any]) -> None:
    if not isinstance(request, dict):
        raise TypeError("SemeAI Gate request must be an object")
    missing = sorted(key for key in REQUIRED_REQUEST_KEYS if key not in request)
    if missing:
        raise ValueError(f"SemeAI Gate request missing required fields: {', '.join(missing)}")
    for key in ("user_message", "ai_answer", "business_risk"):
        if not str(request.get(key) or "").strip():
            raise ValueError(f"{key} must be a non-empty string")
    if not isinstance(request.get("business_data"), (dict, list)):
        raise TypeError("business_data must be an object or array")
    if not isinstance(request.get("business_rules"), dict):
        raise TypeError("business_rules must be an object")
    if "business_context" in request and not isinstance(request.get("business_context"), dict):
        raise TypeError("business_context must be an object when present")
    if "metadata" in request and not isinstance(request.get("metadata"), dict):
        raise TypeError("metadata must be an object when present")


def validate_gate_response(response: dict[str, Any]) -> None:
    missing = sorted(key for key in REQUIRED_RESPONSE_KEYS if key not in response)
    if missing:
        raise ValueError(f"SemeAI Gate response missing required fields: {', '.join(missing)}")
    if response.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported schema_version")
    action = str(response.get("action") or "").upper()
    decision = str(response.get("internal_decision") or "").upper()
    if ACTION_TO_INTERNAL.get(action) != decision:
        raise ValueError(f"invalid action/internal_decision mapping: {action} -> {decision}")
    if bool(response.get("show_to_user")) != (action == "SHOW"):
        raise ValueError("show_to_user must be true only for SHOW")
    if response.get("context_integrity") not in {"ok", "warning", "failed"}:
        raise ValueError("context_integrity must be ok, warning, or failed")


def _normalize_request(request: dict[str, Any]) -> dict[str, Any]:
    context = request.get("business_context") if isinstance(request.get("business_context"), dict) else {}
    return {
        "user_message": str(request["user_message"]).strip(),
        "ai_answer": str(request["ai_answer"]).strip(),
        "business_data": request.get("business_data") if isinstance(request.get("business_data"), (dict, list)) else {},
        "business_rules": request.get("business_rules") if isinstance(request.get("business_rules"), dict) else {},
        "business_context": context,
        "hidden_context_marker": str(request.get("hidden_context_marker") or request.get("context_marker") or "").strip(),
        "expected_answer_scope": str(request.get("expected_answer_scope") or context.get("expected_answer_scope") or "").strip(),
        "business_risk": str(request.get("business_risk") or "unspecified_business_risk").strip(),
        "metadata": request.get("metadata") if isinstance(request.get("metadata"), dict) else {},
    }


def _evaluate_business_rules(data: dict[str, Any]) -> dict[str, Any]:
    risk = data["business_risk"]
    answer = data["ai_answer"]
    business_data = data["business_data"]
    rules = data["business_rules"]

    if risk == "fake_promo_code":
        codes = _extract_promo_codes(answer)
        active = _active_promo_codes(business_data)
        unsupported = [code for code in codes if code not in active]
        if rules.get("only_show_confirmed_promos", True) and unsupported:
            code = unsupported[0]
            return _decision("SILENCE", f"The promo code {code} is not found in business data.", ["promo_code_not_confirmed"])
        if not codes and rules.get("only_show_confirmed_promos", True):
            return _decision("NEEDS_REVIEW", "The AI answer discusses a promotion but no confirmed code could be verified.", ["promo_code_not_verifiable"])

    if risk in {"unsupported_financial_claim", "unsupported_product_claim"}:
        if _claim_supported(answer, business_data):
            return _decision("PROCEED", "The AI answer is supported by the supplied business data.", [])
        if risk == "unsupported_financial_claim":
            if rules.get("block_unsupported_financial_claims") or _contains_high_impact_finance(answer):
                return _decision("SILENCE", "The AI answer makes an unsupported high-impact financial claim.", ["unsupported_financial_claim"])
            return _decision("NEEDS_REVIEW", "The AI answer makes a business claim that is not supported by the supplied business data.", ["business_claim_not_supported"])
        if rules.get("block_unsupported_claims") or _contains_high_impact_product_claim(answer):
            return _decision("SILENCE", "The AI answer makes an unsupported product claim that should not be auto-released.", ["unsupported_product_claim"])
        return _decision("NEEDS_REVIEW", "The AI answer makes a business claim that is not supported by the supplied business data.", ["business_claim_not_supported"])

    if risk == "unsafe_action" or _contains_unsafe_action(answer):
        return _decision("SILENCE", "The AI answer recommends an action that requires explicit approval and must not be released automatically.", ["unsafe_action", "explicit_approval_required"])

    if business_data and _claim_supported(answer, business_data):
        return _decision("PROCEED", "The AI answer is supported by the supplied business data.", [])

    return _decision("PROCEED", "The AI answer does not violate the supplied business rules.", [])


def _evaluate_context_integrity(data: dict[str, Any]) -> dict[str, Any]:
    context = data["business_context"]
    scope = _normalize_text(data["expected_answer_scope"])
    if not context and not scope:
        return {
            "decision": "PROCEED",
            "context_integrity": "ok",
            "context_drift": False,
            "business_context_mismatch": False,
            "reason": "No business context integrity check was requested.",
            "risk_details": [],
        }

    answer = _normalize_text(data["ai_answer"])
    topic = _normalize_text(str(context.get("conversation_topic") or ""))
    details: list[str] = []
    context_drift = False
    mismatch = False
    severe = False

    if topic == "billing_support" or "billing" in scope:
        billing_terms = ("billing", "support", "charge", "charged", "payment", "invoice", "refund", "subscription")
        drift_terms = ("marketing", "growth", "funnel", "advertising", "social media")
        severe_drift_terms = ("product team", "campaign planning", "product analyst")
        finance_terms = ("investment", "guaranteed return", "annual return", "yield", "profit", "portfolio", "risk free")
        if any(term in answer for term in finance_terms):
            severe = True
            context_drift = True
            details.append("unsupported_financial_claim")
        elif any(term in answer for term in severe_drift_terms):
            severe = True
            context_drift = True
            details.append("context_drift")
        elif any(term in answer for term in drift_terms) or not any(term in answer for term in billing_terms):
            context_drift = True
            details.append("context_drift")

    known = _known_products(data["business_data"], context)
    mentioned = _mentioned_products(answer)
    if known and mentioned and not mentioned.issubset(known):
        mismatch = True
        severe = True
        details.append("business_context_mismatch")

    if not details:
        return {
            "decision": "PROCEED",
            "context_integrity": "ok",
            "context_drift": False,
            "business_context_mismatch": False,
            "reason": "The AI answer remains within the current business conversation.",
            "risk_details": [],
        }
    reason = "AI answer does not match the current business context."
    if severe:
        reason = "AI answer does not match the current business context and includes unsupported or mismatched claims."
    return {
        "decision": "SILENCE" if severe else "NEEDS_REVIEW",
        "context_integrity": "failed" if severe else "warning",
        "context_drift": context_drift,
        "business_context_mismatch": mismatch,
        "reason": reason,
        "risk_details": details,
    }


def _write_receipt(data: dict[str, Any], decision: str, reason: str, risk_details: list[str], receipt_dir: str | Path | None) -> dict[str, Any]:
    target = Path(receipt_dir or ".semeai_gate_receipts")
    target.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    seed = "|".join([timestamp, data["user_message"], data["ai_answer"], decision])
    audit_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    candidate_hash = _sha256(data["ai_answer"])
    payload = {
        "receipt_version": "semeai_gate_basic_v0.1",
        "receipt_type": "release_decision",
        "audit_id": audit_id,
        "timestamp": timestamp,
        "schema_version": SCHEMA_VERSION,
        "action": INTERNAL_TO_ACTION[decision],
        "internal_decision": decision,
        "show_to_user": decision == "PROCEED",
        "reason": reason,
        "business_risk": data["business_risk"],
        "risk_details": risk_details,
        "prompt_hash": _sha256(data["user_message"]),
        "candidate_hash": candidate_hash,
        "released_output_hash": candidate_hash if decision == "PROCEED" else None,
        "release_output_present": decision == "PROCEED",
        "audit_preserved": True,
        "canonical_mapping": ACTION_TO_INTERNAL,
    }
    path = target / f"{timestamp.replace(':', '').replace('-', '')}_{audit_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"audit_id": audit_id, "status": "saved", "path": str(path)}


def _decision(decision: str, reason: str, risk_details: list[str]) -> dict[str, Any]:
    return {"decision": decision, "reason": reason, "risk_details": risk_details}


def _select_reason(decision: str, business: dict[str, Any], context: dict[str, Any]) -> str:
    for check in (context, business):
        if check["decision"] == decision:
            return str(check["reason"])
    return str(business["reason"])


def _next_step(action: str, risk: str, context: dict[str, Any]) -> str:
    if context.get("context_integrity") in {"warning", "failed"}:
        return "Do not auto-release. Route to the owner of the current business context."
    if action == "SHOW":
        return "Show the AI answer to the user."
    if action == "REVIEW":
        return "Do not auto-release. Send the answer to a human operator or reviewer."
    return "Do not show the AI answer. Show a safe fallback or transfer to a human operator."


def _safe_fallback(risk: str) -> str:
    if risk == "fake_promo_code":
        return "I can't confirm an active discount code for your account. Please check current offers or contact support."
    if risk in {"unsupported_financial_claim", "unsupported_product_claim"}:
        return "I can't confirm that account or product condition from the available business data. Please contact support."
    if risk == "unsafe_action":
        return "This action requires explicit approval. Please contact an authorized operator."
    if risk == "context_drift":
        return "I can't confirm that answer within the current business context. Please contact support."
    return "I can't safely confirm this answer. Please contact a human operator."


def _strictest_decision(*decisions: str) -> str:
    valid = [item if item in DECISION_PRIORITY else "NEEDS_REVIEW" for item in decisions]
    return max(valid, key=lambda item: DECISION_PRIORITY[item])


def _extract_promo_codes(text: str) -> list[str]:
    matches = re.findall(r"\b[A-Z][A-Z0-9_-]{3,}\b", text or "")
    return _dedupe([match for match in matches if match not in {"PROMO", "CODE", "DISCOUNT", "SAVE"}])


def _active_promo_codes(data: dict[str, Any] | list[Any]) -> set[str]:
    if not isinstance(data, dict):
        return set()
    return {str(item).strip().upper() for item in data.get("active_promo_codes", []) if str(item).strip()}


def _claim_supported(answer: str, data: dict[str, Any] | list[Any]) -> bool:
    if isinstance(data, dict) and data.get("claim_supported") is True:
        return True
    if not isinstance(data, dict):
        return False
    claims = data.get("supported_claims") or data.get("confirmed_claims") or []
    normalized = _normalize_text(answer)
    return any(_normalize_text(str(claim)) in normalized for claim in claims if str(claim).strip())


def _contains_high_impact_finance(text: str) -> bool:
    lowered = _normalize_text(text)
    terms = ("guaranteed", "premium", "annual return", "investment", "yield", "profit", "cannot lose", "risk free")
    return any(term in lowered for term in terms)


def _contains_high_impact_product_claim(text: str) -> bool:
    lowered = _normalize_text(text)
    terms = ("reporting exports", "onboarding assistance", "extended storage")
    return any(term in lowered for term in terms)


def _contains_unsafe_action(text: str) -> bool:
    lowered = _normalize_text(text)
    terms = ("bypass approval", "skip review", "deploy directly", "disable checks", "disable monitoring", "force push", "rm rf", "override gate", "ignore approval")
    return any(term in lowered for term in terms)


def _known_products(data: dict[str, Any] | list[Any], context: dict[str, Any]) -> set[str]:
    products = set()
    if isinstance(data, dict):
        products.update(_normalize_text(str(item)) for item in data.get("known_account_products", []) if str(item).strip())
    if context.get("known_account_product"):
        products.add(_normalize_text(str(context["known_account_product"])))
    return products


def _mentioned_products(answer: str) -> set[str]:
    lowered = _normalize_text(answer)
    result = set()
    for product in ("basic subscription", "premium investment account", "enterprise account", "gold investment plan"):
        if product in lowered:
            result.add(_normalize_text(product))
    return result


def _normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _sha256(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result
