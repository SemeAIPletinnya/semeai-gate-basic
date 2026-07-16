# Short outreach emails · SemeAI Gate pilot

Copy-paste templates based on the [pilot packet](pilot_packet.md).  
Keep the ask narrow. Do not lead with “AI safety platform.”

**From (recommended):** `anton_semenenko@semeai.tech` or `support@semeai.tech`  
**Attach / link:** pilot packet · live console · register  

---

## 1. Cold email · Support / e-commerce chatbot (primary)

**Subject options**
- Stop invented promo codes before customers see them  
- 2-week pilot: fake promo release-control for your support bot  
- Quick question: does your bot invent discount codes?

```text
Hi <Name>,

Quick one: when a support chatbot invents a promo or refund code that is not
in your system of record, customers still try it — and trust takes the hit.

I built SemeAI Gate: a thin release-control layer that sits after your LLM and
before the user. It returns SHOW / REVIEW / BLOCK against your business data
(e.g. active_promo_codes), with an audit id.

It does not replace your bot. First pilot is intentionally narrow:
fake promo-code prevention on 20–50 sample answers.

• Live console: https://gate.semeai.tech/demo/saas_visible.html
• Product: https://semeai.tech
• Open source: https://github.com/SemeAIPletinnya/semeai-gate-basic

Would you be open to a 15–20 min call this week to see if a 2-week pilot fits
your support flow?

Best,
Anton Semenenko
SemeAI · support@semeai.tech
```

---

## 2. Cold email · SaaS product / platform eng

**Subject options**
- Middleware after generation, not another model  
- SHOW / REVIEW / BLOCK for product-assistant claims  

```text
Hi <Name>,

Teams shipping product AI often discover the same failure mode: fluent answers
that are not supported by current plan/feature/account data.

SemeAI Gate is a deterministic check after generation:

  AI answer + business data/rules → SHOW | REVIEW | BLOCK + audit id

No second LLM. Hosted pilot API or self-hosted. First design-partner scope is
one risk class (promo, plan claims, or unsafe ops advice).

Demo: https://gate.semeai.tech/demo/saas_visible.html
Register (API key): https://semeai.tech/register.html

Open to a short call if this matches a problem you are already seeing?

Anton
SemeAI Gate · anton_semenenko@semeai.tech
```

---

## 3. Follow-up (no reply, day 4–7)

**Subject:** Re: <original subject>

```text
Hi <Name> — bumping once in case this landed under the pile.

Concrete ask: one risk class (usually fake promos), 20–50 redacted samples,
2-week wire of POST /v0/check after your model. Pilot fee is 25 USDT if you
want the hosted workspace; open-source local eval is free.

One-pager: https://github.com/SemeAIPletinnya/semeai-gate-basic/blob/master/docs/pilot_packet.md

Happy to send a 5-min screen recording of the console if useful.

Anton
```

---

## 4. Warm intro / reply after “send more”

```text
Hi <Name>,

Thanks — here is the short pilot shape:

Goal: prove we can stop one class of unsupported AI answer before release
while keeping an audit id (recommended: fake promo codes).

You provide: 20–50 messages + candidate answers + active promo list (or synthetic).
We provide: hosted API / dashboard, contract SHOW·REVIEW·BLOCK, integration checklist.

Timeline: ~2 weeks to first measured false-accept drop on that class.
Commercial: 25 USDT TRC20 pilot for hosted workspace (payment is not gate authority).

Links
• Pilot packet: https://github.com/SemeAIPletinnya/semeai-gate-basic/blob/master/docs/pilot_packet.md
• Integration checklist: https://github.com/SemeAIPletinnya/semeai-gate-basic/blob/master/docs/integration_checklist.md
• Live console: https://gate.semeai.tech/demo/saas_visible.html
• Register: https://semeai.tech/register.html

If useful, propose two times for a 15-min call or send 5 sample bad answers and
I will run them live.

Anton Semenenko · support@semeai.tech
```

---

## 5. LinkedIn / X DM (ultra-short)

```text
Hi <Name> — building a release-control layer for support bots:
AI invents SAVE30 → Gate BLOCKS if code not in business data.
SHOW/REVIEW/BLOCK + audit. 2-week pilot, one risk class.
Demo: gate.semeai.tech/demo/saas_visible.html — open to a quick look?
```

---

## 6. Investor / design-partner (not salesy)

```text
Hi <Name>,

Thesis: generation is not release authority. Production LLM answers should be
candidates until checked against business facts.

SemeAI Gate is the adapter: deterministic SHOW/REVIEW/BLOCK, open-source core,
hosted pilot API, USDT pilot billing. First wedge = support bots inventing
promos/refunds.

Repo: https://github.com/SemeAIPletinnya/semeai-gate-basic
Site: https://semeai.tech
ADR: https://github.com/SemeAIPletinnya/semeai-gate-basic/blob/master/docs/architecture_adr_v0_1.md

Would value 20 minutes of feedback on pilot packaging and design-partner fit.

Anton
```

---

## Send checklist

- [ ] Personalize first line (their bot / vertical / recent post)  
- [ ] One CTA only (call **or** “send 5 samples”)  
- [ ] No SOC2 / “we stop all hallucinations” claims  
- [ ] Link live demo early  
- [ ] Log outreach in a simple sheet: name · company · date · template · status  

**Related:** [partner_outreach_templates.md](partner_outreach_templates.md) · [pilot_packet.md](pilot_packet.md)
