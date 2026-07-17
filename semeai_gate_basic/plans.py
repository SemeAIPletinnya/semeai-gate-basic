"""Public plan catalog for SemeAI Gate SaaS (Stripe + crypto pilots)."""

from __future__ import annotations

from typing import Any, Mapping

# Daily check limits align with usage.py; keep names stable for billing webhooks.
PLAN_CATALOG: dict[str, dict[str, Any]] = {
    "free": {
        "id": "free",
        "name": "Free",
        "tagline": "Try the gate in minutes",
        "price_usd": 0,
        "price_label": "$0",
        "interval": "forever",
        "currency": "usd",
        "checks_per_day": 100,
        "seats": 1,
        "highlight": False,
        "cta": "Start free",
        "features": [
            "100 gate checks / day",
            "SHOW · REVIEW · BLOCK",
            "Email + password cabinet",
            "1 workspace seat",
            "Community support",
        ],
        "stripe_price_env": None,
        "crypto_amount_usdt": None,
    },
    "starter": {
        "id": "starter",
        "name": "Starter",
        "tagline": "For early product pilots",
        "price_usd": 29,
        "price_label": "$29",
        "interval": "month",
        "currency": "usd",
        "checks_per_day": 1_000,
        "seats": 3,
        "highlight": True,
        "cta": "Start Starter",
        "features": [
            "1,000 checks / day",
            "Receipts + REVIEW queue",
            "3 team seats",
            "Email support",
            "Stripe or USDT pilot path",
        ],
        "stripe_price_env": "SEMEAI_GATE_STRIPE_PRICE_STARTER",
        "crypto_amount_usdt": "29.00",
        "usage_tier": "pilot",
    },
    "growth": {
        "id": "growth",
        "name": "Growth",
        "tagline": "Production support bots",
        "price_usd": 99,
        "price_label": "$99",
        "interval": "month",
        "currency": "usd",
        "checks_per_day": 10_000,
        "seats": 10,
        "highlight": False,
        "cta": "Start Growth",
        "features": [
            "10,000 checks / day",
            "Team invites + roles",
            "10 seats",
            "Priority email support",
            "API keys + sessions",
        ],
        "stripe_price_env": "SEMEAI_GATE_STRIPE_PRICE_GROWTH",
        "crypto_amount_usdt": "99.00",
        "usage_tier": "developer",
    },
    "scale": {
        "id": "scale",
        "name": "Scale",
        "tagline": "High-volume release control",
        "price_usd": 299,
        "price_label": "$299",
        "interval": "month",
        "currency": "usd",
        "checks_per_day": 50_000,
        "seats": 25,
        "highlight": False,
        "cta": "Start Scale",
        "features": [
            "50,000 checks / day",
            "25 seats",
            "SSO-ready path (OAuth)",
            "Billing webhooks",
            "Dedicated onboarding",
        ],
        "stripe_price_env": "SEMEAI_GATE_STRIPE_PRICE_SCALE",
        "crypto_amount_usdt": "299.00",
        "usage_tier": "enterprise_review",
    },
    "enterprise": {
        "id": "enterprise",
        "name": "Enterprise",
        "tagline": "Custom volume · SLA · self-host",
        "price_usd": None,
        "price_label": "Custom",
        "interval": "custom",
        "currency": "usd",
        "checks_per_day": 100_000,
        "seats": 100,
        "highlight": False,
        "cta": "Contact sales",
        "features": [
            "Custom daily volume",
            "Unlimited seats (contract)",
            "Self-host / VPC options",
            "SLA + security review",
            "Named success contact",
        ],
        "stripe_price_env": None,
        "crypto_amount_usdt": None,
        "usage_tier": "enterprise",
        "contact_only": True,
    },
}


def list_plans(*, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    values = env or {}
    plans = []
    for plan in PLAN_CATALOG.values():
        item = dict(plan)
        env_key = plan.get("stripe_price_env")
        price_id = values.get(env_key) if env_key else None
        item["stripe_price_id_configured"] = bool(price_id)
        item["stripe_price_id"] = price_id if price_id else None
        # never leak full price id to public if you prefer — we expose configured flag + id for checkout
        plans.append(item)
    return {
        "schema_version": "0.2-plans",
        "currency_default": "usd",
        "billing_modes": ["stripe_subscription", "manual_usdt_trc20", "free"],
        "payment_is_never_gate_authority": True,
        "plans": plans,
    }


def get_plan(plan_id: str) -> dict[str, Any] | None:
    return PLAN_CATALOG.get(str(plan_id or "").lower())


def usage_tier_for_plan(plan_id: str) -> str:
    plan = get_plan(plan_id) or {}
    return str(plan.get("usage_tier") or plan_id or "developer")
