"""Portfolio Coordinator — cross-symbol signal filtering and execution.

Reads signals from the SignalBus, applies portfolio-level rules, and
routes approved signals to the broker.

This is the ONLY component that writes to the Portfolio aggregate.
Sessions never write — they only produce signals.

Rules (in order):
  RULE-1: MAX_POSITIONS (default 5)
  RULE-2: PORTFOLIO_NOTIONAL (max 60% of capital)
  RULE-3: SYMBOL_NOTIONAL (max 20% of capital per underlying)
  RULE-4: DAILY_LOSS (halt if daily loss >= threshold)
  RULE-5: CORRELATION_GUARD (NIFTY/BANKNIFTY/FINNIFTY same-direction block)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.domain.services.signal_bus import SignalBus, BusSignal

if TYPE_CHECKING:
    from app.domain.trading.models.entities import Signal
    from app.domain.trading.models.aggregates import Portfolio
    from app.domain.ports.broker import BrokerPort

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RejectionResult:
    """Result of portfolio coordinator rule evaluation."""

    rejected: bool
    rule: str  # Rule name that rejected, or "" if approved
    reason: str


class PortfolioCoordinator:
    """Cross-symbol signal filtering and execution.

    Runs as an asyncio coroutine, consuming signals from the SignalBus
    and routing approved signals to the broker.
    """

    # NSE index family — correlated instruments
    CORRELATED_SYMBOLS = frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY"})

    def __init__(
        self,
        signal_bus: SignalBus,
        portfolio: Portfolio,
        broker: BrokerPort,
        capital: float = 5000000.0,
        max_positions: int = 5,
        max_portfolio_notional_pct: float = 0.60,
        max_symbol_notional_pct: float = 0.20,
        max_daily_loss_pct: float = 0.02,
        correlation_guard: bool = True,
    ) -> None:
        self._bus = signal_bus
        self._portfolio = portfolio
        self._broker = broker
        self._capital = capital
        self._max_positions = max_positions
        self._max_portfolio_notional_pct = max_portfolio_notional_pct
        self._max_symbol_notional_pct = max_symbol_notional_pct
        self._max_daily_loss_pct = max_daily_loss_pct
        self._correlation_guard = correlation_guard
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the coordinator loop."""
        self._running = True
        logger.info("PortfolioCoordinator started")
        while self._running:
            try:
                bus_signal = await asyncio.wait_for(self._bus.get(), timeout=1.0)
                await self._process_signal(bus_signal)
            except asyncio.TimeoutError:
                continue  # check running flag
            except Exception as e:
                logger.error("PortfolioCoordinator error: %s", e, exc_info=True)

    def stop(self) -> None:
        """Stop the coordinator loop."""
        self._running = False

    async def _process_signal(self, bus_signal: BusSignal) -> None:
        """Process a signal from the bus."""
        signal = bus_signal.signal

        # Apply portfolio-level rules
        result = self._check_rules(signal)
        if result.rejected:
            self._bus.record_rejection()
            logger.info(
                "Signal REJECTED: %s — %s (%s)",
                bus_signal.symbol,
                result.rule,
                result.reason,
            )
            return

        # Route to broker
        try:
            position = self._broker.execute_order(
                signal, self._portfolio, bus_signal.symbol
            )
            if position:
                self._bus._consumed += 1
                logger.info(
                    "Signal EXECUTED: %s %s via %s",
                    bus_signal.symbol,
                    signal.direction,
                    bus_signal.source,
                )
        except Exception as e:
            logger.error(
                "Execution failed for %s: %s",
                bus_signal.symbol,
                e,
            )

    def _check_rules(self, signal: Signal) -> RejectionResult:
        """Apply portfolio-level rules to a signal."""

        # RULE-1: MAX_POSITIONS
        open_count = len(self._portfolio.open_positions)
        if open_count >= self._max_positions:
            return RejectionResult(
                rejected=True,
                rule="MAX_POSITIONS",
                reason=f"open_positions={open_count} >= {self._max_positions}",
            )

        # RULE-2: PORTFOLIO_NOTIONAL
        total_notional = sum(
            abs(float(p.entry_price) * float(p.size))
            for p in self._portfolio.open_positions.values()
        )
        if total_notional / self._capital > self._max_portfolio_notional_pct:
            return RejectionResult(
                rejected=True,
                rule="PORTFOLIO_NOTIONAL",
                reason=f"notional/total={total_notional / self._capital:.2%} > {self._max_portfolio_notional_pct:.0%}",
            )

        # RULE-3: SYMBOL_NOTIONAL
        signal_underlying = signal.symbol.split(" ")[0] if signal.symbol else ""
        signal_notional = (
            abs(float(signal.entry_price) * float(signal.size))
            if signal.entry_price > 0
            else 0
        )
        existing_notional = sum(
            abs(float(p.entry_price) * float(p.size))
            for p in self._portfolio.open_positions.values()
            if p.symbol.split(" ")[0] == signal_underlying
        )
        if (
            existing_notional + signal_notional
        ) / self._capital > self._max_symbol_notional_pct:
            return RejectionResult(
                rejected=True,
                rule="SYMBOL_NOTIONAL",
                reason=f"symbol notional {(existing_notional + signal_notional) / self._capital:.2%} > {self._max_symbol_notional_pct:.0%}",
            )

        # RULE-4: DAILY_LOSS (simplified — check portfolio stats)
        try:
            stats = self._portfolio.get_stats()
            if hasattr(stats, "realized_pnl") and stats.realized_pnl < 0:
                daily_loss_pct = abs(stats.realized_pnl) / self._capital
                if daily_loss_pct >= self._max_daily_loss_pct:
                    return RejectionResult(
                        rejected=True,
                        rule="DAILY_HALT",
                        reason=f"daily_loss={daily_loss_pct:.2%} >= {self._max_daily_loss_pct:.0%}",
                    )
        except Exception:
            pass

        # RULE-5: CORRELATION_GUARD
        if self._correlation_guard and signal_underlying in self.CORRELATED_SYMBOLS:
            for pos in self._portfolio.open_positions.values():
                pos_underlying = pos.symbol.split(" ")[0]
                if (
                    pos_underlying in self.CORRELATED_SYMBOLS
                    and pos_underlying != signal_underlying
                ):
                    pos_direction = "LONG" if pos.side == "BUY" else "SHORT"
                    sig_direction = signal.direction
                    if pos_direction == sig_direction:
                        return RejectionResult(
                            rejected=True,
                            rule="CORRELATION_GUARD",
                            reason=f"correlated position {pos_underlying} already {pos_direction}",
                        )

        return RejectionResult(rejected=False, rule="", reason="")

    def get_stats(self) -> dict:
        """Get coordinator statistics."""
        return {
            "running": self._running,
            "bus_stats": self._bus.get_stats(),
            "open_positions": len(self._portfolio.open_positions),
        }
