from __future__ import annotations

from pathlib import Path

from semeai_gate_basic.email_provider import (
    _from_email,
    _from_header,
    email_provider_status,
    send_verification_email,
)


def test_from_header_formats_and_parses_named_addresses() -> None:
    assert _from_email({"SEMEAI_GATE_EMAIL_FROM": "SemeAI Gate <onboarding@resend.dev>"}) == "onboarding@resend.dev"
    assert _from_email({"SEMEAI_GATE_EMAIL_FROM": "onboarding@resend.dev"}) == "onboarding@resend.dev"
    header = _from_header({"from_name": "SemeAI Gate", "from_email": "onboarding@resend.dev"})
    assert header == "SemeAI Gate <onboarding@resend.dev>"
    # Do not double-wrap already-formatted values accidentally fed as from_email.
    header2 = _from_header({"from_name": "SemeAI Gate", "from_email": "SemeAI Gate <onboarding@resend.dev>"})
    assert header2 == "SemeAI Gate <onboarding@resend.dev>"


def test_outbox_email_delivery_without_provider(tmp_path: Path) -> None:
    env = {
        "SEMEAI_GATE_ACCOUNT_DIR": str(tmp_path),
        "SEMEAI_GATE_OPERATOR_EMAIL": "anton_semenenko@semeai.tech",
        "SEMEAI_GATE_FEEDBACK_EMAIL": "support@semeai.tech",
    }
    status = email_provider_status(env=env)
    assert status["provider"] == "outbox_only"
    assert status["automatic_email_delivery"] is False

    result = send_verification_email(
        to="pilot@example.com",
        verification_url="https://semeai.tech/register.html#verify=token",
        registration_id="reg_test",
        company="Acme",
        env=env,
        account_dir=tmp_path,
    )
    assert result["user"]["ok"] is True
    assert result["user"]["delivery"] == "queued_for_manual_send"
    outbox = tmp_path / "email_outbox"
    assert outbox.exists()
    files = list(outbox.glob("*.json"))
    assert len(files) >= 2  # user + operator
