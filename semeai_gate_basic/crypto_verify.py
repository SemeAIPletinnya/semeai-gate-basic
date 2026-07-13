from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Mapping


# USDT TRC20 mainnet contract
USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
DEFAULT_TRONGRID = "https://api.trongrid.io"


class CryptoVerifyError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def verify_usdt_trc20_txid(
    txid: str,
    *,
    expected_to: str,
    expected_amount_usdt: str | float | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Best-effort public verification of a USDT/TRC20 transfer via TronGrid.

    Does not store private keys. If TronGrid is unreachable, returns
    verification_status=unavailable so operator can still review manually.
    """
    values = env or os.environ
    base = str(values.get("SEMEAI_GATE_TRONGRID_URL") or DEFAULT_TRONGRID).rstrip("/")
    api_key = str(values.get("SEMEAI_GATE_TRONGRID_API_KEY") or "").strip()
    txid = str(txid or "").strip()
    if len(txid) != 64:
        raise CryptoVerifyError("txid must be 64 hex characters")

    headers = {
        "Accept": "application/json",
        "User-Agent": "semeai-gate-basic/0.2 (+https://semeai.tech)",
    }
    if api_key:
        headers["TRON-PRO-API-KEY"] = api_key

    url = f"{base}/v1/transactions/{txid}/events"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return {
            "verification_status": "unavailable",
            "provider": "trongrid",
            "ok": False,
            "error": f"HTTP {exc.code}: {detail[:300]}",
            "txid": txid,
            "automatic_onchain_verification": False,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "verification_status": "unavailable",
            "provider": "trongrid",
            "ok": False,
            "error": str(exc),
            "txid": txid,
            "automatic_onchain_verification": False,
        }

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        data = []

    expected_to_norm = expected_to.strip()
    matches: list[dict[str, Any]] = []
    for event in data:
        if not isinstance(event, dict):
            continue
        # Transfer events often expose contract + result.to / result.value
        contract = str(event.get("contract_address") or event.get("contract") or "")
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        to_addr = str(result.get("to") or result.get("to_address") or event.get("to") or "")
        # value may be sun-like integer string for token decimals 6
        raw_value = result.get("value") or result.get("amount") or event.get("value")
        amount = None
        try:
            if raw_value is not None:
                amount = float(raw_value) / 1_000_000.0
        except (TypeError, ValueError):
            amount = None
        event_name = str(event.get("event_name") or event.get("name") or "")
        if event_name and event_name.lower() not in {"transfer", "transferfrom"}:
            # keep scanning other shapes
            pass
        matches.append(
            {
                "contract": contract,
                "to": to_addr,
                "amount_usdt": amount,
                "event_name": event_name,
            }
        )

    # Also try transaction info endpoint for more reliable transfer parsing
    info = _fetch_tx_info(base, txid, headers)
    if info:
        matches.extend(info)

    paid_to_wallet = False
    observed_amount = None
    usdt_contract_seen = False
    for item in matches:
        to_addr = str(item.get("to") or "")
        contract = str(item.get("contract") or "")
        if USDT_TRC20_CONTRACT.lower() in contract.lower() or contract.endswith(USDT_TRC20_CONTRACT):
            usdt_contract_seen = True
        if expected_to_norm and expected_to_norm in to_addr:
            paid_to_wallet = True
            if item.get("amount_usdt") is not None:
                observed_amount = item.get("amount_usdt")

    amount_ok = True
    if expected_amount_usdt is not None and observed_amount is not None:
        try:
            amount_ok = abs(float(observed_amount) - float(expected_amount_usdt)) < 0.01
        except (TypeError, ValueError):
            amount_ok = True

    if not matches:
        status = "not_found"
        ok = False
    elif paid_to_wallet and amount_ok:
        status = "matched"
        ok = True
    elif paid_to_wallet:
        status = "partial_match"
        ok = False
    else:
        status = "mismatch"
        ok = False

    return {
        "verification_status": status,
        "provider": "trongrid",
        "ok": ok,
        "txid": txid,
        "expected_to": expected_to_norm,
        "observed_amount_usdt": observed_amount,
        "expected_amount_usdt": str(expected_amount_usdt) if expected_amount_usdt is not None else None,
        "usdt_contract_seen": usdt_contract_seen,
        "paid_to_expected_wallet": paid_to_wallet,
        "amount_ok": amount_ok,
        "events_scanned": len(matches),
        "automatic_onchain_verification": True,
        "note": "On-chain match is evidence for operator review; it does not auto-activate gate authority.",
    }


def _fetch_tx_info(base: str, txid: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    url = f"{base}/wallet/gettransactioninfobyid"
    body = json.dumps({"value": txid}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={**headers, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return []
    out: list[dict[str, Any]] = []
    log = payload.get("log") if isinstance(payload, dict) else None
    if not isinstance(log, list):
        return out
    for item in log:
        if not isinstance(item, dict):
            continue
        # topics/data hex — leave coarse signal only
        out.append(
            {
                "contract": str(item.get("address") or ""),
                "to": "",
                "amount_usdt": None,
                "event_name": "log",
            }
        )
    return out
