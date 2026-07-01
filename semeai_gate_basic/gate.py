from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "0.1"

ACTION_TO_INTERNAL = {
    "SHOW": "PROCEED",
    "REVIEW": "NEEDS_REVIEW",
    "BLOCK": "SILENCE",
}
INTERNAL_TO_ACTION = {value: key for key, value in ACTION_TO_INTERNAL.items()}
DECISION_PRIORITY = {"PROCEED": 0, "NEEDS_REVIEW": 1, "SILENCE": 2}

REQUIRED_REQUEST_KEYS = {
    "user_message",
    "ai_answer",
    "business_data",
    "business_rules",
    "business_risk",
}

REQUIRED_RESPONSE_KEYS = {
    "schema_version",
    "action",
    "internal_decision",
    "show_to_user",
    "reason",
    "business_risk",
    "risk_details",
    "next_step",
    "audit_id",
    "audit_preserved",
    "context_integrity",
}


def check_ai_answer(request: dict[str, Any], *, receipt_dir: str | Path | None = None) -> dict[str, Any]:
    """Check an AI answer before showing it to a user.

    This is the small public-facing SemeAI Gate contract:

    AI answer -> SemeAI Gate -> SHOW / REVIEW / BLOCK -> receipt

    It is deterministic and local. It does not call an LLM, cloud API, network
    service, or external telemetry.
    """

    normalized = _normalize_request(request)
    business = _evaluate_business_rules(normalized)
    context = _evaluate_context_integrity(normalized)
    internal_decision = _strictest_decision(business["decision"], context["decision"])
    action = INTERNAL_TO_ACTION[internal_decision]
    show_to_user = internal_decision == "PROCEED"
    reason = context["reason"] if context["decision"] == internal_decision and context["decision"] != "PROCEED" else business["reason"]
    risk_details = _dedupe([*business["risk_details"], *context["risk_details"]])

    receipt = _write_receipt(
        normalized,
        internal_decision=internal_decision,
        action=action,
        show_to_user=show_to_user,
        reason=reason,
        risk_details=risk_details,
        context_integrity=context["context_integrity"],
        receipt_dir=receipt_dir,
    )

    result = {
        "schema_version": SCHEMA_VERSION,
        "action": action,
        "internal_decision": internal_decision,
        "show_to_user": show_to_user,
        "reason": reason,
        "business_risk": normalized["business_risk"],
        "context_integrity": context["context_integrity"],
        "risk_details": risk_details,
        "next_step": _next_step(action, normalized["business_risk"]),
        "audit_id": receipt["receipt_id"],
        "audit_preserved": True,
        "safe_fallback": None if show_to_user else _safe_fallback(normalized["business_risk"]),
        "technical_details": {
            "receipt_path": receipt["path"],
            "prompt_hash": receipt["prompt_hash"],
            "answer_hash": receipt["answer_hash"],
            "canonical_mapping": ACTION_TO_INTERNAL,
            "silence_means": "release_denied_execution_withheld_audit_preserved",
        },
    }
    validate_gate_response(result)
    return result


def validate_gate_request(request: dict[str, Any]) -> None:
    if not isinstance(request, dict):
        raise TypeError("SemeAI Gate request must be an object")
    missing = sorted(key for key in REQUIRED_REQUEST_KEYS if key not in request)
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")
    for key in ("user_message", "ai_answer", "business_risk"):
        if not str(request.get(key) or "").strip():
            raise ValueError(f"{key} must be a non-empty string")
    if not isinstance(request.get("business_data"), (dict, list)):
        raise TypeError("business_data must be an object or array")
    if not isinstance(request.get("business_rules"), dict):
        raise TypeError("business_rules must be an object")
    if "business_context" in request and not isinstance(request.get("business_context"), dict):
        raise TypeError("business_context must be an object when present")


def validate_gate_response(response: dict[str, Any]) -> None:
    if not isinstance(response, dict):
        raise TypeError("SemeAI Gate response must be an object")
    missing = sorted(key for key in REQUIRED_RESPONSE_KEYS if key not in response)
    if missing:
        raise ValueError(f"missing response fields: {', '.join(missing)}")
    action = str(response.get("action") or "").upper()
    internal = str(response.get("internal_decision") or "").upper()
    if ACTION_TO_INTERNAL.get(action) != internal:
        raise ValueError(f"invalid action/internal_decision mapping: {action} -> {internal}")
    if bool(response.get("show_to_user")) != (action == "SHOW"):
        raise ValueError("show_to_user must be true only for SHOW")
    if response.get("audit_preserved") is not True:
        raise ValueError("audit_preserved must be true")


def _normalize_request(request: dict[str, Any]) -> dict[str, Any]:
    validate_gate_request(request)
    context = request.get("business_context") if isinstance(request.get("business_context"), dict) else {}
    return {
        "user_message": str(request.get("user_message") or "").strip(),
        "ai_answer": str(request.get("ai_answer") or "").strip(),
        "business_data": request.get("business_data") if isinstance(request.get("business_data"), (dict, list)) else {},
        "business_rules": request.get("business_rules") if isinstance(request.get("business_rules"), dict) else {},
        "business_context": context,
        "expected_answer_scope": str(request.get("expected_answer_scope") or context.get("expected_answer_scope") or "").strip(),
        "business_risk": str(request.get("business_risk") or "unspecified_business_risk").strip(),
        "metadata": request.get("metadata") if isinstance(request.get("metadata"), dict) else {},
    }


def _evaluate_business_rules(request: dict[str, Any]) -> dict[str, Any]:
    risk = request["business_risk"]
    answer = request["ai_answer"]
    data = request["business_data"]
    rules = request["business_rules"]

    if risk == "fake_promo_code":
        codes = _extract_promo_codes(answer)
        active = _active_promo_codes(data)
        unsupported = [code for code in codes if code not in active]
        if unsupported and rules.get("only_show_confirmed_promos", True):
            return _decision(
                "SILENCE",
                f"The promo code {unsupported[0]} is not found in business data.",
                ["promo_code_not_confirmed", f"unsupported_code:{unsupported[0]}"],
            )
        if codes and not unsupported:
            return _decision("PROCEED", "The promo code is confirmed by supplied business data.", [])

    if risk in {"unsupported_financial_claim", "unsupported_product_claim"}:
        if not _claim_supported(answer, data):
            block = bool(
                rules.get("block_unsupported_claims")
                or (risk == "unsupported_financial_claim" and rules.get("block_unsupported_financial_claims"))
                or (risk == "unsupported_financial_claim" and _contains_severe_financial_claim(answer))
            )
            return _decision(
                "SILENCE" if block else "NEEDS_REVIEW",
                "The AI answer makes a business claim that is not supported by the supplied business data.",
                ["business_claim_not_supported"],
            )

    if risk == "unsafe_action" or _contains_unsafe_action(answer):
        return _decision(
            "SILENCE",
            "The AI answer recommends an action that requires explicit approval and must not be released automatically.",
            ["explicit_approval_required", "unsafe_action"],
        )

    if _claim_supported(answer, data):
        return _decision("PROCEED", "The AI answer is supported by supplied business data.", [])

    return _decision(
        "NEEDS_REVIEW",
        "The AI answer is not clearly supported by supplied business data.",
        ["support_not_confirmed"],
    )


def _evaluate_context_integrity(request: dict[str, Any]) -> dict[str, Any]:
    context = request["business_context"]
    scope = request["expected_answer_scope"]
    if not context and not scope:
        return {
            "decision": "PROCEED",
            "context_integrity": "ok",
            "reason": "No business context integrity check was requested.",
            "risk_details": [],
        }

    answer = _normalize_text(request["ai_answer"])
    topic = _normalize_text(str(context.get("conversation_topic") or ""))
    expected_scope = _normalize_text(scope)
    risk_details: list[str] = []
    severe = False

    if topic == "billing_support" or "billing" in expected_scope:
        billing_terms = ("charge", "charged", "billing", "invoice", "payment", "refund", "subscription", "support")
        support_scope_terms = billing_terms
        if _promo_answer_belongs_to_promo_flow(request):
            support_scope_terms = (*support_scope_terms, "promo code", "discount code")
        finance_terms = ("investment", "annual return", "guaranteed return", "fixed return", "yield", "profit", "portfolio", "risk free", "risk-free", "cannot lose")
        known_products = _known_account_products(request)
        mentioned_products = _mentioned_account_products(answer)
        if any(term in answer for term in finance_terms):
            risk_details.append("unsupported_financial_claim")
            severe = True
        if known_products and mentioned_products and not mentioned_products.issubset(known_products):
            risk_details.extend(["business_context_mismatch", "account_product_mismatch"])
            severe = True
        if not any(term in answer for term in support_scope_terms):
            risk_details.append("context_drift")

    if not risk_details:
        return {
            "decision": "PROCEED",
            "context_integrity": "ok",
            "reason": "The AI answer remains within the current business conversation.",
            "risk_details": [],
        }

    return {
        "decision": "SILENCE" if severe else "NEEDS_REVIEW",
        "context_integrity": "failed" if severe else "warning",
        "reason": "AI answer does not match the current business context.",
        "risk_details": _dedupe(risk_details),
    }


def _decision(decision: str, reason: str, risk_details: list[str]) -> dict[str, Any]:
    return {"decision": decision, "reason": reason, "risk_details": risk_details}


def _strictest_decision(*decisions: str) -> str:
    valid = [decision for decision in decisions if decision in DECISION_PRIORITY]
    return max(valid or ["PROCEED"], key=lambda item: DECISION_PRIORITY[item])


def _write_receipt(
    request: dict[str, Any],
    *,
    internal_decision: str,
    action: str,
    show_to_user: bool,
    reason: str,
    risk_details: list[str],
    context_integrity: str,
    receipt_dir: str | Path | None,
) -> dict[str, str]:
    target = Path(receipt_dir or Path.cwd() / "outputs" / "receipts")
    target.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    prompt_hash = _sha256_text(request["user_message"])
    answer_hash = _sha256_text(request["ai_answer"])
    seed = f"{timestamp}|{prompt_hash}|{answer_hash}|{internal_decision}"
    receipt_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    path = target / f"{timestamp.replace(':', '').replace('-', '')[:15]}_{receipt_id}.json"
    receipt = {
        "receipt_version": "semeai_gate_basic_receipt_v0.1",
        "receipt_id": receipt_id,
        "timestamp": timestamp,
        "receipt_type": "release_decision",
        "action": action,
        "internal_decision": internal_decision,
        "show_to_user": show_to_user,
        "release_allowed": show_to_user,
        "execution_status": "RELEASED" if show_to_user else "WITHHELD",
        "audit_preserved": True,
        "reason": reason,
        "business_risk": request["business_risk"],
        "context_integrity": context_integrity,
        "risk_details": risk_details,
        "prompt_hash": prompt_hash,
        "answer_hash": answer_hash,
        "raw_text_stored": False,
    }
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "receipt_id": receipt_id,
        "path": str(path),
        "prompt_hash": prompt_hash,
        "answer_hash": answer_hash,
    }


def _extract_promo_codes(text: str) -> list[str]:
    matches = re.findall(r"\b[A-Z][A-Z0-9_-]{3,}\b", text or "")
    excluded = {"PROMO", "CODE", "DISCOUNT", "SAVE"}
    return _dedupe([match for match in matches if match not in excluded])


def _active_promo_codes(data: Any) -> set[str]:
    if not isinstance(data, dict):
        return set()
    raw = data.get("active_promo_codes")
    return {str(item).strip().upper() for item in raw if str(item).strip()} if isinstance(raw, list) else set()


def _claim_supported(answer: str, data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    normalized = _normalize_text(answer)
    claims = data.get("supported_claims") or data.get("confirmed_claims") or []
    return any(_normalize_text(str(claim)) in normalized for claim in claims if str(claim).strip())


def _contains_severe_financial_claim(text: str) -> bool:
    lowered = _normalize_text(text)
    terms = ("guaranteed return", "annual return", "fixed return", "guaranteed", "investment return", "yield", "profit", "risk free", "risk-free", "cannot lose")
    return any(term in lowered for term in terms)


def _contains_unsafe_action(text: str) -> bool:
    lowered = _normalize_text(text)
    terms = (
        "bypass approval",
        "skip review",
        "disable checks",
        "deploy directly",
        "force push",
        "ignore policy",
        "override gate",
        "disable monitoring",
        "rm rf",
        "delete production",
    )
    return any(term in lowered for term in terms)


def _promo_answer_belongs_to_promo_flow(request: dict[str, Any]) -> bool:
    """Keep promo-code checks in scope without allowing unrelated offers.

    Billing/support conversations can legitimately mention a promo code when
    the host product has explicitly asked the gate to verify a promo-code
    answer. Generic promotions, discounts, or offers remain out of scope unless
    they are represented as a concrete code in the fake-promo flow.
    """

    if request.get("business_risk") != "fake_promo_code":
        return False
    return bool(_extract_promo_codes(request.get("ai_answer", "")))


def _known_account_products(request: dict[str, Any]) -> set[str]:
    products: set[str] = set()
    context = request.get("business_context") if isinstance(request.get("business_context"), dict) else {}
    data = request.get("business_data") if isinstance(request.get("business_data"), dict) else {}

    for key in ("known_account_product", "current_account_product", "account_product"):
        products.update(_product_aliases(context.get(key)))
        products.update(_product_aliases(data.get(key)))

    for key in ("known_account_products", "current_account_products", "account_products"):
        products.update(_product_aliases_from_iterable(context.get(key)))
        products.update(_product_aliases_from_iterable(data.get(key)))

    return products


def _mentioned_account_products(normalized_answer: str) -> set[str]:
    product_patterns = {
        "basic_subscription": ("basic account", "basic plan", "basic product", "basic subscription"),
        "premium_account": ("premium account", "premium plan", "premium product", "premium subscription"),
        "enterprise_account": ("enterprise account", "enterprise plan", "enterprise product", "enterprise subscription"),
        "investment_account": ("investment account", "investment plan", "investment product", "investment subscription"),
    }
    return {
        product
        for product, patterns in product_patterns.items()
        if any(pattern in normalized_answer for pattern in patterns)
    }


def _product_aliases_from_iterable(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    aliases: set[str] = set()
    for item in value:
        aliases.update(_product_aliases(item))
    return aliases


def _product_aliases(value: Any) -> set[str]:
    normalized = _normalize_text(str(value or ""))
    aliases: set[str] = set()
    if not normalized:
        return aliases
    if "basic" in normalized:
        aliases.add("basic_subscription")
    if "premium" in normalized:
        aliases.add("premium_account")
    if "enterprise" in normalized:
        aliases.add("enterprise_account")
    if "investment" in normalized:
        aliases.add("investment_account")
    return aliases


def _next_step(action: str, risk: str) -> str:
    if action == "SHOW":
        return "Show the AI answer to the user."
    if action == "REVIEW":
        return "Do not auto-release. Send the answer to a human operator or reviewer."
    if risk == "fake_promo_code":
        return "Do not show this answer. Show a safe fallback or transfer to a human operator."
    if risk == "unsafe_action":
        return "Block release and require explicit approval."
    return "Do not show this answer. Show a safe fallback or transfer to a human operator."


def _safe_fallback(risk: str) -> str:
    if risk == "fake_promo_code":
        return "I can't confirm that promo code from current business data. Please check current offers or contact support."
    if risk in {"unsupported_financial_claim", "unsupported_product_claim"}:
        return "I can't confirm that account or product condition from current business data. Please contact support."
    if risk == "unsafe_action":
        return "This action requires explicit approval. Please contact an authorized operator."
    return "I can't safely confirm this answer. Please contact a human operator."


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
