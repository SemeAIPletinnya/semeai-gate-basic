# Partner Outreach Templates

Use these templates to start conversations with teams that already have an
LLM/chatbot and care about unsupported answers reaching users.

**Primary short emails (recommended):** [outreach_emails.md](outreach_emails.md)  
**Pilot 1-pager:** [pilot_packet.md](pilot_packet.md)  
**After they pay:** [operator_txid_activation_runbook.md](operator_txid_activation_runbook.md)

Keep the ask narrow:

```text
Can we test one risk class, such as fake promo-code prevention, with local
business data and a small sample of chatbot answers?
```

Do not lead with broad AI-safety claims. Lead with a concrete release-control
problem.

## Short Fintech / Support Message

```text
Hi <name>, I am building SemeAI Gate Basic, a small release-control layer for
LLM/chatbot answers.

The narrow use case: if a chatbot invents a promo code, account term, or
unsupported financial/product claim, the gate returns SHOW / REVIEW / BLOCK
before the answer reaches the user.

It does not replace your chatbot. It sits between the chatbot answer and the
customer. The first pilot can be local and narrow: fake promo-code prevention
using your current business data/rules.

Would you be open to a 20-minute call to see if this is relevant for your
support flow?
```

## SaaS Product Team Message

```text
Hi <name>, quick idea for teams adding AI support to SaaS products:

Your chatbot may generate a plausible answer that is not actually supported by
current product data. SemeAI Gate Basic checks the AI answer before release and
returns:

SHOW = release it
REVIEW = send to a human/operator
BLOCK = do not show it; use a safe fallback

The first pilot does not need a new model or cloud service. It can run locally
against one risk class, such as unsupported plan/feature claims.

Is this close to a problem your team is seeing?
```

## AI Chatbot Builder Message

```text
Hi <name>, I saw you are working on chatbot/product AI.

I am testing a small open-source release-control adapter: SemeAI Gate Basic.
It does not generate answers. It checks an answer your chatbot already produced
and returns SHOW / REVIEW / BLOCK based on supplied business data and rules.

Example: user asks for a 30% discount, chatbot invents SAVE30, business data
has no active promo code, gate returns BLOCK and preserves an audit id.

Would you be interested in trying the fake promo-code or unsupported claim
case on a small local sample?
```

## Investor / Design Partner Message

```text
Hi <name>, I am working on SemeAI Gate Basic, an open-source release-control
adapter for LLM products.

The thesis is simple: generation is not release authority. A chatbot answer
should be treated as a candidate until it is checked against business data,
rules, and current context.

The current basic repo includes Python/Node examples, a JSON contract,
middleware quickstart, a deterministic benchmark, and a five-minute demo
script. The first design-partner pilot is intentionally narrow: stop fake
promo codes or unsupported product/account claims before they reach users.

Would you be open to reviewing the repo and giving feedback on the first pilot
shape?
```

## Twitter / LinkedIn Short Post

```text
LLM chatbots can confidently invent business facts: fake promo codes,
unsupported plan terms, risky actions.

I am building SemeAI Gate Basic: a small release-control layer between an
existing chatbot and the user.

AI answer -> Gate -> SHOW / REVIEW / BLOCK -> audit id

Open-source basic repo:
https://github.com/SemeAIPletinnya/semeai-gate-basic
```

## Follow-Up After Interest

```text
Thanks. The cleanest first test is a one-week local pilot:

1. pick one risk class;
2. collect 20-50 representative chatbot answers;
3. provide the relevant business data/rules;
4. run the gate locally;
5. review SHOW / REVIEW / BLOCK outcomes and audit ids.

Suggested first risk: fake promo-code prevention or unsupported product claim.
```

## What Not To Say

Avoid:

- "universal hallucination detection";
- "compliance certified";
- "replaces human review";
- "autonomous approval";
- "solves AI safety";
- "production SLA".

Better:

```text
SemeAI Gate Basic can be piloted as a local release-control adapter for one
well-defined class of unsupported AI answer.
```
