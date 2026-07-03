# Manual Crypto Billing v0.1

SemeAI Gate v0.1 includes a minimal manual USDT/TRC20 billing path for early
paid pilots.

This is not automatic crypto processing.

It is a local account-billing metadata flow:

```text
verified workspace
-> create manual payment intent
-> show USDT/TRC20 address and invoice id
-> user submits transaction id
-> operator reviews the transfer
-> paid access can be activated manually later
```

## Boundaries

- No private keys are stored.
- No wallet signing is performed.
- No blockchain API is called.
- No external payment processor is called.
- No automatic on-chain verification is performed.
- Submitting a TXID does not activate paid access.
- Billing metadata is not release authority.
- Subscription metadata is not gate authority.

The gate semantics remain unchanged:

```text
SHOW   = PROCEED
REVIEW = NEEDS_REVIEW
BLOCK  = SILENCE
```

`SILENCE` still means release denied, execution withheld, and audit preserved.

## Environment

```text
SEMEAI_GATE_USDT_TRC20_ADDRESS=TJmrrUrpsRpG3u9H4FE9oVyCRPYQYEpG27
SEMEAI_GATE_MANUAL_USDT_AMOUNT=25.00
```

The address is public payment metadata. It is not a secret.

## Endpoints

All billing endpoints require an issued workspace API key from `/v0/verify`.
Static server API keys are not enough for workspace billing.

```text
GET /v0/billing/status
POST /v0/billing/manual-crypto-intent
POST /v0/billing/submit-txid
```

### Create Manual Payment Intent

```json
{
  "plan": "pilot",
  "amount_usdt": "25.00"
}
```

Response includes:

- `invoice.invoice_id`
- `invoice.payment_address`
- `invoice.network = "TRC20"`
- `invoice.asset = "USDT"`
- `invoice.payment_status = "pending_payment"`
- `automatic_onchain_verification = false`
- `private_keys_stored = false`

### Submit TXID

```json
{
  "invoice_id": "inv_...",
  "txid": "64_hex_character_transaction_id"
}
```

Response status is `pending_review`.

The TXID is a public blockchain identifier. It is stored as review evidence and
hashed in public summaries. It is not treated as proof of payment until an
operator verifies the transfer.

## Storage

The account store contains billing metadata under:

```text
outputs/api_accounts/billing_intents
outputs/api_accounts/billing_proofs
outputs/api_accounts/billing_events.jsonl
```

The workspace record receives a compact `billing` object. This object can show
`trial`, `pending_payment`, or `pending_review`, but it does not change gate
decisions.

## Future Processor Path

A later version can replace the manual review step with a processor or webhook
such as a hosted crypto payment provider. That future version should still keep
these boundaries:

- processor event is billing evidence, not release authority;
- activation requires a verified payment event;
- receipts and workspace audit stay scoped to the authenticated workspace;
- private keys remain outside SemeAI Gate;
- failed or timed out verification fails closed.
