from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Mapping


DEFAULT_OPERATOR_EMAIL = "anton_semenenko@semeai.tech"
DEFAULT_FROM_NAME = "SemeAI Gate"
DEFAULT_FROM_EMAIL = "onboarding@resend.dev"  # Resend sandbox default; override in prod


class EmailDeliveryError(RuntimeError):
    """Raised when an email provider fails hard."""


def email_provider_status(*, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    values = env or os.environ
    provider = _detect_provider(values)
    return {
        "configured": provider != "outbox_only",
        "provider": provider,
        "from_email": _from_email(values),
        "operator_email": _operator_email(values),
        "feedback_email": _feedback_email(values),
        "automatic_email_delivery": provider in {"resend", "smtp"},
        "outbox_dir_env": "SEMEAI_GATE_EMAIL_OUTBOX_DIR",
        "resend_key_env": "SEMEAI_GATE_RESEND_API_KEY",
        "note": (
            "When Resend/SMTP is configured, verification and operator notices are emailed automatically. "
            "Otherwise messages are written to a durable outbox for manual delivery."
        ),
    }


def send_email(
    *,
    to: str,
    subject: str,
    text: str,
    html: str | None = None,
    reply_to: str | None = None,
    tags: list[str] | None = None,
    env: Mapping[str, str] | None = None,
    account_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Send email via Resend, SMTP, or durable outbox fallback."""

    values = env or os.environ
    provider = _detect_provider(values)
    payload = {
        "to": to,
        "subject": subject,
        "text": text,
        "html": html or _text_to_html(text),
        "reply_to": reply_to or _feedback_email(values),
        "tags": tags or [],
        "from_email": _from_email(values),
        "from_name": str(values.get("SEMEAI_GATE_EMAIL_FROM_NAME") or DEFAULT_FROM_NAME),
        "provider": provider,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    outbox_path = _write_outbox(payload, account_dir=account_dir, env=values)

    if provider == "resend":
        try:
            remote = _send_resend(payload, values)
            return {
                "ok": True,
                "provider": "resend",
                "delivery": "sent",
                "message_id": remote.get("id"),
                "outbox_path": str(outbox_path),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "provider": "resend",
                "delivery": "outbox_fallback",
                "error": str(exc),
                "outbox_path": str(outbox_path),
            }

    if provider == "smtp":
        try:
            remote_id = _send_smtp(payload, values)
            return {
                "ok": True,
                "provider": "smtp",
                "delivery": "sent",
                "message_id": remote_id,
                "outbox_path": str(outbox_path),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "provider": "smtp",
                "delivery": "outbox_fallback",
                "error": str(exc),
                "outbox_path": str(outbox_path),
            }

    return {
        "ok": True,
        "provider": "outbox_only",
        "delivery": "queued_for_manual_send",
        "outbox_path": str(outbox_path),
        "operator_email": _operator_email(values),
        "note": "No Resend/SMTP key configured. Message saved to outbox for operator delivery.",
    }


def send_verification_email(
    *,
    to: str,
    verification_url: str,
    registration_id: str,
    company: str,
    env: Mapping[str, str] | None = None,
    account_dir: str | Path | None = None,
) -> dict[str, Any]:
    subject = "Verify your SemeAI Gate workspace"
    text = (
        f"Welcome to SemeAI Gate.\n\n"
        f"Company/project: {company}\n"
        f"Registration id: {registration_id}\n\n"
        f"Verify your workspace (link expires):\n{verification_url}\n\n"
        f"After verification you will receive an API key once.\n"
        f"Generation is not release authority. SHOW / REVIEW / BLOCK remain canonical.\n\n"
        f"— SemeAI Gate\n"
        f"Feedback: {_feedback_email(env or os.environ)}\n"
    )
    html = f"""
    <div style="font-family:Inter,Segoe UI,Arial,sans-serif;max-width:560px;margin:0 auto;color:#0f1720">
      <h1 style="font-size:22px;margin:0 0 12px">Verify your SemeAI Gate workspace</h1>
      <p style="color:#475569;line-height:1.55">Company/project: <strong>{_esc(company)}</strong></p>
      <p style="color:#475569;line-height:1.55">Registration id: <code>{_esc(registration_id)}</code></p>
      <p style="margin:24px 0">
        <a href="{_esc(verification_url)}"
           style="display:inline-block;background:#0f766e;color:#fff;text-decoration:none;
                  padding:12px 18px;border-radius:10px;font-weight:700">
          Verify workspace
        </a>
      </p>
      <p style="color:#64748b;font-size:13px;line-height:1.5">
        After verification, your API key is shown once. Generation is not release authority.
      </p>
    </div>
    """
    user_result = send_email(
        to=to,
        subject=subject,
        text=text,
        html=html,
        tags=["verification", "registration"],
        env=env,
        account_dir=account_dir,
    )

    operator = _operator_email(env or os.environ)
    operator_result = send_email(
        to=operator,
        subject=f"[SemeAI] New registration {registration_id}",
        text=(
            f"New workspace registration.\n\n"
            f"email: {to}\ncompany: {company}\nregistration_id: {registration_id}\n"
            f"verification_url: {verification_url}\n"
            f"user_delivery: {user_result.get('delivery')} ({user_result.get('provider')})\n"
        ),
        tags=["operator_notice", "registration"],
        env=env,
        account_dir=account_dir,
    )
    return {"user": user_result, "operator": operator_result}


def send_billing_review_email(
    *,
    workspace_id: str,
    invoice_id: str,
    txid: str,
    workspace_name: str = "",
    env: Mapping[str, str] | None = None,
    account_dir: str | Path | None = None,
) -> dict[str, Any]:
    operator = _operator_email(env or os.environ)
    subject = f"[SemeAI] Billing review {invoice_id}"
    text = (
        f"Manual USDT/TRC20 payment submitted for review.\n\n"
        f"workspace_id: {workspace_id}\n"
        f"workspace_name: {workspace_name}\n"
        f"invoice_id: {invoice_id}\n"
        f"txid: {txid}\n\n"
        f"Activate only after on-chain verification.\n"
        f"Payment metadata is not gate authority.\n"
    )
    return send_email(
        to=operator,
        subject=subject,
        text=text,
        tags=["billing_review"],
        env=env,
        account_dir=account_dir,
    )


def _detect_provider(values: Mapping[str, str]) -> str:
    if str(values.get("SEMEAI_GATE_RESEND_API_KEY") or values.get("RESEND_API_KEY") or "").strip():
        return "resend"
    if str(values.get("SEMEAI_GATE_SMTP_HOST") or values.get("SMTP_HOST") or "").strip():
        return "smtp"
    return "outbox_only"


def _from_email(values: Mapping[str, str]) -> str:
    raw = str(
        values.get("SEMEAI_GATE_EMAIL_FROM")
        or values.get("SEMEAI_GATE_FROM_EMAIL")
        or DEFAULT_FROM_EMAIL
    ).strip()
    # Accept either bare email or "Name <email@domain>" and return bare address.
    if "<" in raw and ">" in raw:
        inner = raw.split("<", 1)[1].split(">", 1)[0].strip()
        if "@" in inner:
            return inner
    return raw


def _from_header(payload: Mapping[str, Any]) -> str:
    """Build a Resend-compatible From header."""
    address = str(payload.get("from_email") or DEFAULT_FROM_EMAIL).strip()
    # If already formatted, keep as-is.
    if "<" in address and ">" in address:
        return address
    name = str(payload.get("from_name") or DEFAULT_FROM_NAME).strip() or DEFAULT_FROM_NAME
    return f"{name} <{address}>"


def _operator_email(values: Mapping[str, str]) -> str:
    return str(
        values.get("SEMEAI_GATE_OPERATOR_EMAIL")
        or values.get("SEMEAI_GATE_FEEDBACK_EMAIL")
        or DEFAULT_OPERATOR_EMAIL
    ).strip()


def _feedback_email(values: Mapping[str, str]) -> str:
    return str(
        values.get("SEMEAI_GATE_FEEDBACK_EMAIL")
        or values.get("SEMEAI_GATE_OPERATOR_EMAIL")
        or DEFAULT_OPERATOR_EMAIL
    ).strip()


def _account_root(account_dir: str | Path | None, env: Mapping[str, str]) -> Path:
    return Path(account_dir or env.get("SEMEAI_GATE_ACCOUNT_DIR") or Path("outputs") / "api_accounts")


def _write_outbox(
    payload: dict[str, Any],
    *,
    account_dir: str | Path | None,
    env: Mapping[str, str],
) -> Path:
    root = Path(env.get("SEMEAI_GATE_EMAIL_OUTBOX_DIR") or (_account_root(account_dir, env) / "email_outbox"))
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    safe_to = "".join(ch if ch.isalnum() or ch in "._-@" else "_" for ch in str(payload.get("to") or "unknown"))[:60]
    path = root / f"{stamp}_{safe_to}.json"
    # Never persist provider secrets
    safe = dict(payload)
    path.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _send_resend(payload: dict[str, Any], values: Mapping[str, str]) -> dict[str, Any]:
    api_key = str(values.get("SEMEAI_GATE_RESEND_API_KEY") or values.get("RESEND_API_KEY") or "").strip()
    if not api_key:
        raise EmailDeliveryError("Resend API key missing")
    body = {
        "from": _from_header(payload),
        "to": [payload["to"]],
        "subject": payload["subject"],
        "text": payload["text"],
        "html": payload["html"],
    }
    if payload.get("reply_to"):
        body["reply_to"] = payload["reply_to"]
    data = json.dumps(body).encode("utf-8")
    # Cloudflare can reject bare-python urllib defaults (HTTP 403 / error 1010)
    # from some cloud egress paths. Send explicit client headers.
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "semeai-gate-basic/0.2 (+https://semeai.tech)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise EmailDeliveryError(f"Resend HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise EmailDeliveryError(f"Resend network error: {exc}") from exc


def _send_smtp(payload: dict[str, Any], values: Mapping[str, str]) -> str:
    host = str(values.get("SEMEAI_GATE_SMTP_HOST") or values.get("SMTP_HOST") or "").strip()
    port = int(values.get("SEMEAI_GATE_SMTP_PORT") or values.get("SMTP_PORT") or "587")
    user = str(values.get("SEMEAI_GATE_SMTP_USER") or values.get("SMTP_USER") or "").strip()
    password = str(values.get("SEMEAI_GATE_SMTP_PASSWORD") or values.get("SMTP_PASSWORD") or "").strip()
    use_tls = str(values.get("SEMEAI_GATE_SMTP_TLS") or "true").lower() in {"1", "true", "yes"}

    msg = EmailMessage()
    msg["Subject"] = payload["subject"]
    msg["From"] = _from_header(payload)
    msg["To"] = payload["to"]
    if payload.get("reply_to"):
        msg["Reply-To"] = payload["reply_to"]
    msg.set_content(payload["text"])
    msg.add_alternative(payload["html"], subtype="html")

    if use_tls:
        context = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls(context=context)
            if user:
                server.login(user, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=20) as server:
            if user:
                server.login(user, password)
            server.send_message(msg)
    return f"smtp:{host}:{port}"


def _text_to_html(text: str) -> str:
    escaped = _esc(text).replace("\n", "<br/>")
    return f"<div style='font-family:Inter,Segoe UI,Arial,sans-serif;line-height:1.55'>{escaped}</div>"


def _esc(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
