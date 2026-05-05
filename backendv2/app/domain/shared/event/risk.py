"""Risk events — risk management and circuit breakers."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.shared.event.base import DomainEvent, _generate_idempotency_key


@dataclass(frozen=True)
class RiskCheckFailed(DomainEvent):
    """Risk check failed — signal rejected.

    Published by RiskManager when a signal fails validation.
    Consumed by alert manager and state snapshot builder.
    """

    signal_id: str = ""
    symbol: str = ""
    check_name: str = ""  # "DAILY_LOSS", "POSITION_LIMIT", "CONCENTRATION", etc.
    reason: str = ""

    @staticmethod
    def create(
        signal_id: str, symbol: str, check_name: str, reason: str
    ) -> "RiskCheckFailed":
        idempotency_key = _generate_idempotency_key(
            signal_id, "risk_failed", check_name
        )
        return RiskCheckFailed(
            idempotency_key=idempotency_key,
            signal_id=signal_id,
            symbol=symbol,
            check_name=check_name,
            reason=reason,
        )


@dataclass(frozen=True)
class DailyLossLimitReached(DomainEvent):
    """Daily loss limit reached — trading halted for the day.

    Published by RiskManager when daily drawdown threshold is hit.
    Consumed by session phase manager (halt trading), alert manager.
    """

    symbol: str = ""
    current_loss: float = 0.0
    limit: float = 0.0

    @staticmethod
    def create(symbol: str, current_loss: float, limit: float) -> "DailyLossLimitReached":
        idempotency_key = _generate_idempotency_key(
            symbol, "daily_loss_limit", str(int(current_loss))
        )
        return DailyLossLimitReached(
            idempotency_key=idempotency_key,
            symbol=symbol,
            current_loss=current_loss,
            limit=limit,
        )


@dataclass(frozen=True)
class ConsecutiveLossesLimitReached(DomainEvent):
    """Consecutive losses limit reached — trading paused."""

    symbol: str = ""
    consecutive_losses: int = 0
    limit: int = 0


@dataclass(frozen=True)
class PositionLimitReached(DomainEvent):
    """Maximum concurrent positions reached."""

    symbol: str = ""
    current_positions: int = 0
    limit: int = 0


@dataclass(frozen=True)
class TradingResumed(DomainEvent):
    """Trading resumed after halt."""

    symbol: str = ""
    reason: str = ""
