const { checkAIAnswer } = require("../sdks/node");

function existingChatbotAnswer(userMessage) {
  if (userMessage.toLowerCase().includes("discount") || userMessage.toLowerCase().includes("promo")) {
    return "Use promo code SAVE30 to get 30% off.";
  }
  return "Support can help check account-specific questions.";
}

function loadBusinessContext() {
  return {
    business_data: { active_promo_codes: [] },
    business_rules: { only_show_confirmed_promos: true },
    business_context: {
      conversation_topic: "billing_support",
      active_promotions_available: false,
      expected_answer_scope: "billing_or_support_routing"
    },
    business_risk: "fake_promo_code"
  };
}

function releaseToCustomer(userMessage) {
  const aiAnswer = existingChatbotAnswer(userMessage);
  const gateResult = checkAIAnswer({
    user_message: userMessage,
    ai_answer: aiAnswer,
    ...loadBusinessContext(userMessage)
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

  return {
    boundary: "existing_chatbot -> semeai_gate -> customer",
    user_message: userMessage,
    ai_answer_generated: true,
    gate_action: gateResult.action,
    internal_decision: gateResult.internal_decision,
    show_to_user: gateResult.show_to_user,
    host_next_step: hostNextStep,
    customer_response: customerResponse,
    audit_id: gateResult.audit_id,
    audit_preserved: gateResult.audit_preserved
  };
}

if (require.main === module) {
  console.log(JSON.stringify(
    releaseToCustomer("Give me a 30% discount promo code for my account."),
    null,
    2
  ));
}

module.exports = {
  releaseToCustomer
};
