"""Wire production EventBus subscribers.

Registers handlers for all domain events so that published events
trigger real side effects (logging, metrics, alerts) instead of
silently accumulating in history with zero consumers.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.domain.shared.event.domain_events import (
    AMTAnalyzed,
    PositionClosed,
    PositionOpened,
    RiskStateChanged,
    SignalGenerated,
    TickReceived,
)

if TYPE_CHECKING:
    from app.infrastructure.messaging.event_bus import EventBus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _on_tick_received(event: TickReceived) -> None:
    logger.debug(
        "TickReceived: symbol=%s price=%.2f volume=%.0f",
        event.symbol, event.price, event.volume,
    )


def _on_amt_analyzed(event: AMTAnalyzed) -> None:
    logger.debug(
        "AMTAnalyzed: symbol=%s setup=%s",
        event.symbol,
        event.phase1_result.get("setup", "unknown") if event.phase1_result else "unknown",
    )


def _on_signal_generated(event: SignalGenerated) -> None:
    if event.direction == "NO_TRADE":
        return
    logger.info(
        "SignalGenerated: symbol=%s direction=%s entry=%.2f sl=%.2f tp=%.2f rr=%.2f confidence=%.2f reason=%s",
        event.symbol, event.direction, event.entry_price, event.stop_loss,
        event.take_profit, event.risk_reward, event.confidence, event.reason,
    )


def _on_position_opened(event: PositionOpened) -> None:
    logger.info(
        "PositionOpened: position_id=%s symbol=%s side=%s entry=%.2f size=%.0f",
        event.position_id, event.symbol, event.side, event.entry_price, event.size,
    )


def _on_position_closed(event: PositionClosed) -> None:
    logger.info(
        "PositionClosed: position_id=%s exit=%.2f pnl=%.2f reason=%s",
        event.position_id, event.exit_price, event.pnl, event.reason,
    )


def _on_risk_state_changed(event: RiskStateChanged) -> None:
    if event.halted:
        logger.warning(
            "RiskStateChanged: HALTED reason=%s daily_pnl=%.2f losses=%d",
            event.reason, event.daily_pnl, event.consecutive_losses,
        )
    else:
        logger.info("RiskStateChanged: RESUMED")


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def wire_event_bus_subscribers(event_bus: EventBus) -> None:
    """Register all production handlers on the event bus."""
    event_bus.subscribe(TickReceived, _on_tick_received)
    event_bus.subscribe(AMTAnalyzed, _on_amt_analyzed)
    event_bus.subscribe(SignalGenerated, _on_signal_generated)
    event_bus.subscribe(PositionOpened, _on_position_opened)
    event_bus.subscribe(PositionClosed, _on_position_closed)
    event_bus.subscribe(RiskStateChanged, _on_risk_state_changed)
