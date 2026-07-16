# Architecture Decision Record · SemeAI Gate v0.1

**Status:** Accepted for pilot  
**Date:** 2026-07-16  
**Scope:** `semeai-gate-basic` runtime + `semeai.tech` product surface + hosted API

---

## 1. Context

SemeAI Gate sits after LLM generation and before user release:

```text
host chatbot → candidate answer → SemeAI Gate → SHOW | REVIEW | BLOCK → user / operator / audit
```

We need a product that:

1. ships a clear business contract (not “another chatbot”);
2. is auditable and deterministic for support / promo / policy risks;
3. can run open source, self-hosted, or as a small SaaS pilot;
4. does not pretend to be universal hallucination detection.

---

## 2. Decisions

### ADR-001 · Deterministic rule engine, not an LLM judge

**Decision:** Core gate logic (`gate.py`) is pure Python rules over host-supplied
`business_data`, `business_rules`, and optional `business_context`. No model call
inside the gate.

**Why:** Latency (sub-ms class), auditability, no second LLM cost, no opaque scores.

**Consequence:** Coverage is scoped to implemented risk classes (promo codes,
unsupported claims, unsafe actions, context drift). Host must supply facts.

---

### ADR-002 · Canonical machine values

**Decision:** Product actions map 1:1 to Silence-as-Control internals:

| Product | Internal |
| --- | --- |
| SHOW | PROCEED |
| REVIEW | NEEDS_REVIEW |
| BLOCK | SILENCE |

Labels may be localized in UI; machine JSON stays English/canonical.

**Why:** Replay, cross-repo governance alignment, no silent synonym drift.

---

### ADR-003 · Payment is never release authority

**Decision:** Billing status (USDT/TRC20 pilot, future Stripe) is metadata for
subscription/ops only. Gate decisions do not read payment state.

**Why:** Prevent “paid so release anything” anti-pattern; keep release control honest.

---

### ADR-004 · File-backed multi-tenant for pilot only

**Decision:** Accounts, keys (hashed), receipts, billing intents live as JSON under
`SEMEAI_GATE_ACCOUNT_DIR` / `SEMEAI_GATE_RECEIPT_DIR` on a Fly volume.

**Why:** Zero ops for first pilots; works with single small machine + mount.

**Consequence (debt):** Not safe for high concurrency, complex queries, or multi-region HA.
Migrate to Postgres when a paying design partner needs it — not before.

---

### ADR-005 · stdlib HTTP server for v0.1 API

**Decision:** `ThreadingHTTPServer` + hand-rolled routing in `server.py`.

**Why:** Minimal deps, easy Docker/Fly, full control of CORS and auth headers.

**Consequence (debt):** No framework middleware ecosystem. Replace with FastAPI/uvicorn
when load, OpenAPI productization, or team size justifies it.

---

### ADR-006 · Three public surfaces, three repos

| Host | Repo | Role |
| --- | --- | --- |
| `api.semeai.tech` | `semeai-gate-basic` | Runtime API |
| `gate.semeai.tech` | `semeai-gate-basic` demo | Live console |
| `semeai.tech` | `semeai.tech` | Marketing + register + dashboard |

**Why:** Separate governance research (`silence-as-control`) from product adapter and site.

---

### ADR-007 · API keys only (no password / OAuth) in v0.1

**Decision:** Workspace auth = Bearer API key. Key shown once at verify/rotate.
Stored only as hash server-side; browser uses `sessionStorage` for dashboard.

**Why:** Fast pilot onboarding; matches middleware integration model.

**Consequence:** No SSO/SCIM yet. Operators must treat keys as secrets.

---

### ADR-008 · Manual USDT/TRC20 pilot billing

**Decision:** Default pilot 25 USDT TRC20 + invoice intent + TXID submit + operator review email.

**Why:** Avoid Stripe complexity before demand; crypto-native early buyers.

**Consequence:** Not self-serve activation. Admin activate path remains human-in-loop.

---

### ADR-009 · Static product UI, no SPA build

**Decision:** `semeai.tech` is static HTML + shared CSS/JS (GitHub Pages). Tailwind CDN on core conversion pages; shared `site.css` for secondary pages.

**Why:** Velocity, cache-bust via query `?v=`, no frontend CI.

**Consequence (debt):** Duplicated tokens across some pages until fully consolidated; CDN Tailwind not ideal long-term perf.

---

### ADR-010 · Demo free checks are client-limited

**Decision:** Landing free checks use browser `localStorage` counter (5).

**Why:** Simple public demo without abuse accounts.

**Consequence:** Easy reset; not a security boundary. Rate limits on API still apply for authenticated usage.

---

## 3. Current system shape

```text
┌──────────────────────────────────────────────────┐
│  semeai.tech  (static)                           │
│  landing · register · dashboard · contract pages │
└────────────────────┬─────────────────────────────┘
                     │ HTTPS JSON
┌────────────────────▼─────────────────────────────┐
│  api.semeai.tech  (Fly · Python · volume)        │
│  /v0/check · register · keys · receipts · bill   │
│  gate.py  →  receipts JSON                       │
└────────────────────┬─────────────────────────────┘
                     │ vocabulary only
┌────────────────────▼─────────────────────────────┐
│  silence-as-control  (research)                  │
│  PROCEED / NEEDS_REVIEW / SILENCE                │
└──────────────────────────────────────────────────┘
```

---

## 4. Technical debt register

| ID | Item | Risk | When to pay |
| --- | --- | --- | --- |
| TD-01 | JSON file tenancy | data races, hard analytics | first multi-seat paid pilot |
| TD-02 | stdlib HTTP server | ops/features ceiling | sustained > pilot traffic |
| TD-03 | Hard-coded risk rules | integration friction | after 2–3 vertical designs |
| TD-04 | Host must pick `business_risk` | wrong risk → weak gate | policy templates UI |
| TD-05 | Style tokens split across HTML | visual drift | shared theme only (in progress) |
| TD-06 | Manual billing ops | activation lag | Stripe or full on-chain auto |
| TD-07 | Fly `min_machines=0` | cold starts | set min 1 for paid SLA |
| TD-08 | No formal backup runbook for volume | data loss | before any paid SLA |
| TD-09 | Client free-check counter | demo abuse | IP/key rate limit if abused |
| TD-10 | Secondary docs scattered | partner confusion | pilot packet (this sprint) |

---

## 5. Explicit non-goals (v0.1)

- Hosting customer models
- Universal hallucination detection
- SOC2 / ISO marketing claims
- Multi-region active-active
- Autonomous “fix” of blocked answers
- Payment-as-permission for SHOW

---

## 6. Success criteria for this architecture

Pilot is successful when a design partner:

1. wires `POST /v0/check` (or local `check_ai_answer`) after their LLM;
2. supplies real or redacted business data for one risk class (start: fake promo);
3. measures false accepts reduced on that class;
4. keeps receipts for REVIEW/BLOCK cases.

Not required for pilot success: enterprise SSO, Stripe, multi-region, custom model training.

---

## 7. Related docs

- [Contract](contract.md)
- [SaaS MVP plan](saas_mvp_plan.md)
- [Pilot packet](pilot_packet.md)
- [Integration checklist](integration_checklist.md)
- [Deployment modes](deployment_modes.md)
- [Fly deploy](fly_api_deploy.md)
