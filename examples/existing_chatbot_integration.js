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

const customerResponse = gateResult.show_to_user ? aiAnswer : gateResult.safe_fallback;

console.log(JSON.stringify({
  flow: "existing_chatbot -> semeai_gate -> customer",
  gate_action: gateResult.action,
  internal_decision: gateResult.internal_decision,
  customer_response: customerResponse,
  audit_id: gateResult.audit_id,
  audit_preserved: gateResult.audit_preserved
}, null, 2));
