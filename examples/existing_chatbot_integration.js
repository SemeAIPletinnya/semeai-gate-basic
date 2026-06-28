const { checkAIAnswer } = require("../sdks/node");

function existingChatbotAnswer(userMessage) {
  if (userMessage.toLowerCase().includes("discount")) {
    return "Use promo code SAVE30 to get 30% off.";
  }
  return "Contact support for account-specific questions.";
}

const userMessage = "Give me a 30% discount promo code for my account.";
const aiAnswer = existingChatbotAnswer(userMessage);

const gateResult = checkAIAnswer({
  user_message: userMessage,
  ai_answer: aiAnswer,
  business_data: { active_promo_codes: [] },
  business_rules: { only_show_confirmed_promos: true },
  business_risk: "fake_promo_code"
});

let customerResponse;
let hostNextStep;
if (gateResult.action === "SHOW") {
  customerResponse = aiAnswer;
  hostNextStep = "show_ai_answer";
} else if (gateResult.action === "REVIEW") {
  customerResponse = "A support operator should review this answer before release.";
  hostNextStep = "route_to_human_review";
} else {
  customerResponse = gateResult.safe_fallback;
  hostNextStep = "show_safe_fallback";
}

console.log(JSON.stringify({
  flow: "existing_chatbot -> semeai_gate -> customer",
  gate_action: gateResult.action,
  internal_decision: gateResult.internal_decision,
  host_next_step: hostNextStep,
  customer_response: customerResponse,
  audit_id: gateResult.audit_id,
  audit_preserved: gateResult.audit_preserved
}, null, 2));
