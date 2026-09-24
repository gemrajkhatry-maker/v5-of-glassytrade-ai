"""Application command for finalizing strategy exit output."""

from __future__ import annotations

from glassytrade.domain.execution.types import OrderIntent, OrderPurpose, OrderSide
from glassytrade.domain.strategy.intent import ExitIntent


def finalize_exit_intent(intent: ExitIntent, *, idempotency_key: str | None = None) -> OrderIntent:
    return OrderIntent(
        intent_id=intent.intent_id,
        idempotency_key=idempotency_key or intent.intent_id,
        contract_id=intent.contract_id,
        purpose=OrderPurpose.EXIT.value,
        side=OrderSide(intent.side).value,
        requested_quantity=intent.quantity,
        reference_price=None,
        stop_price=None,
        target_price=None,
    )
