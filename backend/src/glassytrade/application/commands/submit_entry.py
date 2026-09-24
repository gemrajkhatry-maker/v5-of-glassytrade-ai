"""Application command for finalizing strategy entry output."""

from __future__ import annotations

from decimal import Decimal

from glassytrade.domain.execution.types import OrderIntent, OrderPurpose, OrderSide
from glassytrade.domain.strategy.intent import EntryIntent


def finalize_entry_intent(
    intent: EntryIntent,
    *,
    executable_quantity: int,
    idempotency_key: str | None = None,
) -> OrderIntent:
    if executable_quantity <= 0:
        raise ValueError("executable_quantity must be positive")
    return OrderIntent(
        intent_id=intent.intent_id,
        idempotency_key=idempotency_key or intent.intent_id,
        contract_id=intent.contract_id,
        purpose=OrderPurpose.ENTRY.value,
        side=OrderSide(intent.side).value,
        requested_quantity=executable_quantity,
        reference_price=Decimal(str(intent.entry_price)),
        stop_price=Decimal(str(intent.stop_price)),
        target_price=Decimal(str(intent.target_price)),
    )
