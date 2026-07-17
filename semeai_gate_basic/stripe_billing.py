"""Stripe Checkout + webhook for SaaS subscriptions (stdlib urllib)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from .accounts import AccountError, DEFAULT_ACCOUNT_DIR, _account_root, _now, _workspaces_dir
from .plans import get_plan, list_plans, usage_tier_for_plan


class StripeError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def stripe_status(*, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    values = env or os.environ
    secret = bool(str(values.get("SEMEAI_GATE_STRIPE_SECRET_KEY") or "").strip())
    wh = bool(str(values.get("SEMEAI_GATE_STRIPE_WEBHOOK_SECRET") or "").strip())
    return {
        "enabled": secret,
        "webhook_configured": wh,
        "publishable_key_configured": bool(str(values.get("SEMEAI_GATE_STRIPE_PUBLISHABLE_KEY") or "").strip()),
        "checkout_path": "/v0/billing/stripe/checkout",
        "portal_path": "/v0/billing/stripe/portal",
        "webhook_path": "/v0/billing/stripe/webhook",
        "payment_is_never_gate_authority": True,
    }


def _stripe_request(
    method: str,
    path: str,
    *,
    data: Mapping[str, Any] | None = None,
    env: Mapping[str, str],
) -> dict[str, Any]:
    secret = str(env.get("SEMEAI_GATE_STRIPE_SECRET_KEY") or "").strip()
    if not secret:
        raise StripeError("Stripe is not configured", status_code=503)
    body = urllib.parse.urlencode(data or {}, doseq=True).encode("utf-8") if data is not None else None
    req = urllib.request.Request(
        f"https://api.stripe.com/v1{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise StripeError(f"Stripe API error: {err_body}", status_code=400) from exc


def create_checkout_session(
    auth: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    values = env or os.environ
    workspace_id = str(auth.get("workspace_id") or "")
    if not workspace_id:
        raise StripeError("workspace auth required", status_code=403)
    plan_id = str(payload.get("plan") or "starter").lower()
    plan = get_plan(plan_id)
    if not plan or plan.get("contact_only") or plan_id == "free":
        raise StripeError("plan is not available for Stripe checkout", status_code=400)
    env_key = plan.get("stripe_price_env")
    price_id = str(values.get(str(env_key)) or payload.get("stripe_price_id") or "").strip()
    if not price_id:
        raise StripeError(
            f"Stripe price not configured for plan '{plan_id}'. Set {env_key} secret.",
            status_code=503,
        )

    public_site = str(values.get("SEMEAI_GATE_PUBLIC_SITE_URL") or "https://semeai.tech").rstrip("/")
    success_url = str(payload.get("success_url") or f"{public_site}/dashboard.html?billing=success")
    cancel_url = str(payload.get("cancel_url") or f"{public_site}/pricing.html?billing=cancel")

    session = _stripe_request(
        "POST",
        "/checkout/sessions",
        data={
            "mode": "subscription",
            "success_url": success_url + "&session_id={CHECKOUT_SESSION_ID}",
            "cancel_url": cancel_url,
            "client_reference_id": workspace_id,
            "customer_email": str(auth.get("email") or ""),
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
            "metadata[workspace_id]": workspace_id,
            "metadata[plan]": plan_id,
            "subscription_data[metadata][workspace_id]": workspace_id,
            "subscription_data[metadata][plan]": plan_id,
        },
        env=values,
    )
    return {
        "status": "created",
        "checkout_url": session.get("url"),
        "session_id": session.get("id"),
        "plan": plan_id,
        "payment_is_never_gate_authority": True,
    }


def create_portal_session(
    auth: Mapping[str, Any],
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    values = env or os.environ
    root = _account_root(account_dir or values.get("SEMEAI_GATE_ACCOUNT_DIR") or DEFAULT_ACCOUNT_DIR)
    workspace_id = str(auth.get("workspace_id") or "")
    path = _workspaces_dir(root) / f"{workspace_id}.json"
    if not path.exists():
        raise StripeError("workspace not found", status_code=404)
    workspace = json.loads(path.read_text(encoding="utf-8"))
    customer_id = str((workspace.get("billing") or {}).get("stripe_customer_id") or "")
    if not customer_id:
        raise StripeError("no Stripe customer on this workspace yet — complete checkout first", status_code=400)
    public_site = str(values.get("SEMEAI_GATE_PUBLIC_SITE_URL") or "https://semeai.tech").rstrip("/")
    session = _stripe_request(
        "POST",
        "/billing_portal/sessions",
        data={
            "customer": customer_id,
            "return_url": f"{public_site}/dashboard.html",
        },
        env=values,
    )
    return {"status": "created", "portal_url": session.get("url")}


def handle_webhook(
    raw_body: bytes,
    signature_header: str,
    *,
    account_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    values = env or os.environ
    secret = str(values.get("SEMEAI_GATE_STRIPE_WEBHOOK_SECRET") or "").strip()
    if secret:
        _verify_stripe_signature(raw_body, signature_header, secret)

    try:
        event = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise StripeError("invalid webhook JSON") from exc

    etype = str(event.get("type") or "")
    data_obj = (event.get("data") or {}).get("object") or {}
    root = _account_root(account_dir or values.get("SEMEAI_GATE_ACCOUNT_DIR") or DEFAULT_ACCOUNT_DIR)

    if etype in {"checkout.session.completed", "customer.subscription.updated", "customer.subscription.created"}:
        workspace_id = (
            str((data_obj.get("metadata") or {}).get("workspace_id") or "")
            or str(data_obj.get("client_reference_id") or "")
        )
        plan_id = str((data_obj.get("metadata") or {}).get("plan") or "starter")
        customer = str(data_obj.get("customer") or "")
        subscription = str(data_obj.get("subscription") or data_obj.get("id") or "")
        if workspace_id:
            _apply_paid_plan(
                root,
                workspace_id,
                plan_id=plan_id,
                stripe_customer_id=customer,
                stripe_subscription_id=subscription,
                status="active",
            )
    elif etype in {"customer.subscription.deleted", "invoice.payment_failed"}:
        workspace_id = str((data_obj.get("metadata") or {}).get("workspace_id") or "")
        if workspace_id:
            _apply_paid_plan(
                root,
                workspace_id,
                plan_id="free",
                stripe_customer_id=str(data_obj.get("customer") or ""),
                stripe_subscription_id=str(data_obj.get("id") or ""),
                status="unpaid",
            )

    return {"received": True, "type": etype, "payment_is_never_gate_authority": True}


def _apply_paid_plan(
    root: Path,
    workspace_id: str,
    *,
    plan_id: str,
    stripe_customer_id: str,
    stripe_subscription_id: str,
    status: str,
) -> None:
    path = _workspaces_dir(root) / f"{workspace_id}.json"
    if not path.exists():
        return
    workspace = json.loads(path.read_text(encoding="utf-8"))
    tier = usage_tier_for_plan(plan_id)
    plan = get_plan(plan_id) or {}
    billing = workspace.get("billing") if isinstance(workspace.get("billing"), dict) else {}
    billing.update(
        {
            "status": status if status != "unpaid" else "trial",
            "payment_status": "paid" if status == "active" else "unpaid",
            "billing_provider": "stripe",
            "plan": plan_id,
            "stripe_customer_id": stripe_customer_id or billing.get("stripe_customer_id"),
            "stripe_subscription_id": stripe_subscription_id or billing.get("stripe_subscription_id"),
            "updated_at": _now(),
            "external_billing_calls": True,
            "payment_metadata_is_gate_authority": False,
        }
    )
    workspace["billing"] = billing
    workspace["plan"] = tier
    sub = workspace.get("subscription") if isinstance(workspace.get("subscription"), dict) else {}
    sub.update(
        {
            "status": "active" if status == "active" else "unpaid",
            "tier": tier,
            "plan": plan_id,
            "billing_provider": "stripe",
            "external_billing_calls": True,
            "seats": plan.get("seats"),
            "checks_per_day": plan.get("checks_per_day"),
        }
    )
    workspace["subscription"] = sub
    path.write_text(json.dumps(workspace, ensure_ascii=False, indent=2), encoding="utf-8")


def _verify_stripe_signature(payload: bytes, header: str, secret: str) -> None:
    # Stripe-Signature: t=timestamp,v1=signature
    parts = {}
    for item in str(header or "").split(","):
        if "=" in item:
            k, v = item.split("=", 1)
            parts.setdefault(k.strip(), []).append(v.strip())
    timestamp = (parts.get("t") or [""])[0]
    signatures = parts.get("v1") or []
    if not timestamp or not signatures:
        raise StripeError("missing Stripe signature", status_code=400)
    signed = f"{timestamp}.".encode("utf-8") + payload
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in signatures):
        raise StripeError("invalid Stripe signature", status_code=400)
