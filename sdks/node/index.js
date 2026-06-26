"use strict";

const crypto = require("crypto");

const ACTION_TO_INTERNAL = Object.freeze({
  SHOW: "PROCEED",
  REVIEW: "NEEDS_REVIEW",
  BLOCK: "SILENCE"
});

function checkAIAnswer(request) {
  validateGateRequest(request);
  const normalized = normalizeRequest(request);
  const business = evaluateBusinessRules(normalized);
  const context = evaluateContextIntegrity(normalized);
  const decision = strictestDecision(business.decision, context.decision);
  const action = Object.entries(ACTION_TO_INTERNAL).find(([, value]) => value === decision)[0];
  const showToUser = decision === "PROCEED";
  const reason = context.decision === decision ? context.reason : business.reason;
  return {
    schema_version: "0.1",
    action,
    internal_decision: decision,
    show_to_user: showToUser,
    reason,
    business_risk: normalized.business_risk,
    context_integrity: context.context_integrity,
    context_drift: context.context_drift,
    business_context_mismatch: context.business_context_mismatch,
    risk_details: Array.from(new Set([...business.risk_details, ...context.risk_details])),
    next_step: nextStep(action, normalized.business_risk, context),
    audit_id: sha256(`${Date.now()}|${normalized.user_message}|${normalized.ai_answer}|${decision}`).slice(0, 12),
    audit_preserved: true,
    safe_fallback: showToUser ? null : safeFallback(normalized.business_risk),
    technical_details: {
      canonical_mapping: ACTION_TO_INTERNAL,
      candidate_hash: sha256(normalized.ai_answer),
      released_output_hash: showToUser ? sha256(normalized.ai_answer) : null
    }
  };
}

function validateGateRequest(request) {
  for (const key of ["user_message", "ai_answer", "business_data", "business_rules", "business_risk"]) {
    if (!(key in request)) throw new Error(`missing required field: ${key}`);
  }
}

function normalizeRequest(request) {
  const context = isObject(request.business_context) ? request.business_context : {};
  return {
    user_message: String(request.user_message || "").trim(),
    ai_answer: String(request.ai_answer || "").trim(),
    business_data: isObject(request.business_data) || Array.isArray(request.business_data) ? request.business_data : {},
    business_rules: isObject(request.business_rules) ? request.business_rules : {},
    business_context: context,
    expected_answer_scope: String(request.expected_answer_scope || context.expected_answer_scope || "").trim(),
    business_risk: String(request.business_risk || "unspecified_business_risk").trim()
  };
}

function evaluateBusinessRules(data) {
  if (data.business_risk === "fake_promo_code") {
    const codes = extractPromoCodes(data.ai_answer);
    const active = new Set((data.business_data.active_promo_codes || []).map((x) => String(x).toUpperCase()));
    const unsupported = codes.filter((code) => !active.has(code));
    if (unsupported.length && data.business_rules.only_show_confirmed_promos !== false) {
      return decision("SILENCE", `The promo code ${unsupported[0]} is not found in business data.`, ["promo_code_not_confirmed"]);
    }
  }
  if (data.business_risk === "unsafe_action" || containsUnsafeAction(data.ai_answer)) {
    return decision("SILENCE", "The AI answer recommends an action that requires explicit approval.", ["unsafe_action"]);
  }
  if (["unsupported_financial_claim", "unsupported_product_claim"].includes(data.business_risk)) {
    if (claimSupported(data.ai_answer, data.business_data)) {
      return decision("PROCEED", "The AI answer is supported by business data.", []);
    }
    if (data.business_risk === "unsupported_financial_claim") {
      return containsHighImpactFinance(data.ai_answer) || data.business_rules.block_unsupported_financial_claims
        ? decision("SILENCE", "The AI answer makes an unsupported high-impact financial claim.", ["unsupported_financial_claim"])
        : decision("NEEDS_REVIEW", "The AI answer makes an unsupported business claim.", ["business_claim_not_supported"]);
    }
    return containsHighImpactProductClaim(data.ai_answer) || data.business_rules.block_unsupported_claims
      ? decision("SILENCE", "The AI answer makes an unsupported product claim.", ["unsupported_product_claim"])
      : decision("NEEDS_REVIEW", "The AI answer makes an unsupported business claim.", ["business_claim_not_supported"]);
  }
  if (claimSupported(data.ai_answer, data.business_data)) {
    return decision("PROCEED", "The AI answer is supported by business data.", []);
  }
  return decision("PROCEED", "The AI answer does not violate supplied business rules.", []);
}

function evaluateContextIntegrity(data) {
  const answer = normalize(data.ai_answer);
  const topic = normalize(data.business_context.conversation_topic || "");
  const scope = normalize(data.expected_answer_scope || "");
  if (!topic && !scope) {
    return { decision: "PROCEED", context_integrity: "ok", context_drift: false, business_context_mismatch: false, reason: "No context check requested.", risk_details: [] };
  }
  if (topic === "billing_support" || scope.includes("billing")) {
    const finance = ["investment", "guaranteed return", "annual return", "yield", "profit", "portfolio"];
    const drift = ["marketing", "campaign", "growth", "funnel", "advertising", "product team", "product analyst"];
    if (finance.some((term) => answer.includes(term))) {
      return { decision: "SILENCE", context_integrity: "failed", context_drift: true, business_context_mismatch: true, reason: "AI answer does not match the current billing context.", risk_details: ["unsupported_financial_claim"] };
    }
    if (drift.some((term) => answer.includes(term))) {
      return { decision: "NEEDS_REVIEW", context_integrity: "warning", context_drift: true, business_context_mismatch: false, reason: "AI answer does not match the current business context.", risk_details: ["context_drift"] };
    }
  }
  return { decision: "PROCEED", context_integrity: "ok", context_drift: false, business_context_mismatch: false, reason: "The AI answer remains in context.", risk_details: [] };
}

function decision(decision, reason, riskDetails) {
  return { decision, reason, risk_details: riskDetails };
}

function strictestDecision(...decisions) {
  const order = { PROCEED: 0, NEEDS_REVIEW: 1, SILENCE: 2 };
  return decisions.sort((a, b) => order[b] - order[a])[0] || "NEEDS_REVIEW";
}

function nextStep(action) {
  if (action === "SHOW") return "Show the AI answer to the user.";
  if (action === "REVIEW") return "Do not auto-release. Send to human review.";
  return "Do not show the AI answer. Show a safe fallback or transfer to support.";
}

function safeFallback(risk) {
  if (risk === "fake_promo_code") return "I can't confirm an active discount code for your account. Please contact support.";
  return "I can't safely confirm this answer. Please contact a human operator.";
}

function extractPromoCodes(text) {
  return Array.from(String(text).matchAll(/\b[A-Z][A-Z0-9_-]{3,}\b/g)).map((m) => m[0]).filter((x) => !["PROMO", "CODE", "SAVE"].includes(x));
}

function claimSupported(answer, businessData) {
  const claims = businessData.supported_claims || businessData.confirmed_claims || [];
  const normalized = normalize(answer);
  return claims.some((claim) => normalized.includes(normalize(claim)));
}

function containsHighImpactFinance(text) {
  const value = normalize(text);
  return ["guaranteed", "always", "every", "lifetime", "premium", "annual return", "investment", "yield", "profit", "cannot lose", "risk free"].some((term) => value.includes(term));
}

function containsHighImpactProductClaim(text) {
  const value = normalize(text);
  return ["unlimited", "premium", "enterprise", "white glove", "dedicated", "reporting exports", "onboarding assistance", "extended storage"].some((term) => value.includes(term));
}

function containsUnsafeAction(text) {
  const value = normalize(text);
  return ["bypass approval", "skip review", "deploy directly", "disable checks", "force push", "rm rf", "override gate"].some((term) => value.includes(term));
}

function normalize(text) {
  return String(text || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function sha256(text) {
  return crypto.createHash("sha256").update(String(text)).digest("hex");
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

module.exports = { ACTION_TO_INTERNAL, checkAIAnswer, validateGateRequest };
