"""Signal events — trade signal generation and validation."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.shared.event.base import DomainEvent, _generate_idempotency_key


@dataclass(frozen=True)
class SignalGenerated(DomainEvent):
    """A trade signal was generated (not yet risk-validated).

    Published by SignalGenerator / EntryCoordinator.
    Consumed by risk validator and state snapshot builder.
    Idempotency key: symbol + signal_id
    """

    symbol: str = ""
    signal_id: str = ""
    direction: str = "FLAT"  # "LONG", "SHORT", "FLAT"
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    position_size: float = 0.0
    confidence: str = "Medium"
    setup_type: str = ""
    source: str = "AMT"  # "AMT", "LLM", "RL", "AGENT"

    @staticmethod
    def create(
        symbol: str,
        signal_id: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        position_size: float,
        confidence: str,
        setup_type: str,
        source: str = "AMT",
    ) -> "SignalGenerated":
        idempotency_key = _generate_idempotency_key(symbol, signal_id)
        return SignalGenerated(
            idempotency_key=idempotency_key,
            symbol=symbol,
            signal_id=signal_id,
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=position_size,
            confidence=confidence,
            setup_type=setup_type,
            source=source,
        )


@dataclass(frozen=True)
class SignalValidated(DomainEvent):
    """Signal passed risk checks and is ready for execution.

    Published by RiskManager after validation.
    Consumed by execution handler.
    """

    signal_id: str = ""
    symbol: str = ""
    validation_result: str = ""  # "APPROVED", "REJECTED"
    rejection_reason: str = ""

    @staticmethod
    def create(
        signal_id: str, symbol: str, approved: bool, rejection_reason: str = "", reason: str = ""
    ) -> "SignalValidated":
        idempotency_key = _generate_idempotency_key(signal_id, "validated")
        return SignalValidated(
            idempotency_key=idempotency_key,
            signal_id=signal_id,
            symbol=symbol,
            validation_result="APPROVED" if approved else "REJECTED",
            rejection_reason=rejection_reason,
        )
