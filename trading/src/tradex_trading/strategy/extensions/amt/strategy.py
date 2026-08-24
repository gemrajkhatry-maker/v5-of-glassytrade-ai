"""AMT Triple-A strategy extension for the v4 ReactiveStrategyEngine."""

from __future__ import annotations

from decimal import Decimal

from tradex_domain import OrderSide, Signal

from tradex_trading.analytics.candle import OrderflowCandleBuilder
from tradex_trading.analytics.orderbook import OrderbookTracker
from tradex_trading.strategy.extensions.amt.gates import AMTDecisionContext, evaluate
from tradex_trading.strategy.extensions.amt.kernel import AMTKernel
from tradex_trading.strategy.extensions.amt.model import (
    AMTSnapshot,
    AMTStrategyConfig,
    BookSnapshot,
)


class AMTStrategy:
    def __init__(
        self,
        strategy_id: str,
        instrument,
        config: AMTStrategyConfig | None = None,
    ) -> None:
        self._id = strategy_id
        self._instrument = instrument
        self.config = config or AMTStrategyConfig()
        self.kernel = AMTKernel(self.config)
        self._orderflow_builder = OrderflowCandleBuilder()
        self._orderflow_mode = False
        self._book_tracker = OrderbookTracker()
        self._bar_swept = {"bid": 0, "ask": 0}
        #: Fill-derived position state (fallback when the session does not
        #: populate ``StrategyContext.position``).
        self._open_side: str | None = None
        self._open_qty: Decimal = Decimal("0")
        self._open_price: Decimal | None = None
        self._consecutive_losses = 0
        self.snapshots: list[AMTSnapshot] = []
        self._signals: list[Signal] = []

    @property
    def strategy_id(self) -> str:
        return self._id

    @property
    def version(self) -> str:
        return "1.1.0"

    @property
    def signals(self) -> list[Signal]:
        return list(self._signals)

    @property
    def position_direction(self) -> str | None:
        return self._open_side

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses

    @property
    def risk_multiplier(self) -> Decimal:
        if self._consecutive_losses >= self.config.loss_streak_threshold:
            return self.config.risk_shrink_factor
        return Decimal("1")

    def on_start(self, context) -> None:
        pass

    def on_stop(self, context) -> None:
        pass

    def on_bar(self, context, candle):
        if candle.instrument != self._instrument or self._orderflow_mode:
            return None
        return self._evaluate_candle(context, candle)

    def on_orderflow_candle(self, context, candle):
        """Optional adapter for enriched closed candles from v4 analytics."""
        if candle.instrument != self._instrument:
            return None
        return self._evaluate_candle(context, candle)

    def _evaluate_candle(self, context, candle):
        snapshot = self.kernel.update(candle, self._book_snapshot())
        self.snapshots.append(snapshot)
        self._bar_swept = {"bid": 0, "ask": 0}
        position_open, position_direction = self._position_state(context)
        decision = evaluate(AMTDecisionContext(
            snapshot=snapshot,
            position_open=position_open,
            position_direction=position_direction,
            stop_cushion=self.config.tick_size * self.config.stop_cushion_ticks,
            pyramid_enabled=self.config.pyramid_enabled,
            pyramid_threshold=self.config.pyramid_aggression_score,
        ))
        if not decision.approved or decision.direction is None:
            return None
        signal = Signal(
            instrument=self._instrument,
            direction=OrderSide.BUY if decision.direction == "LONG" else OrderSide.SELL,
            strength=float(self.risk_multiplier),
            reason=decision.setup,
            metadata={
                "setup": decision.setup,
                "entry": str(decision.entry),
                "stop_loss": str(decision.stop_loss),
                "take_profit": str(decision.take_profit),
                "risk_reward": str(decision.risk_reward),
                "cushion": str(decision.cushion),
                "pyramid": str(decision.pyramid),
                "phase": snapshot.phase.value,
            },
            timestamp=candle.timestamp,
        )
        self._signals.append(signal)
        return signal

    def _position_state(self, context) -> tuple[bool, str | None]:
        """Prefer session-populated position; fall back to fill-derived state."""
        if context is not None:
            position = getattr(context, "position", None)
            if position is not None and position.quantity.value != 0:
                direction = "LONG" if position.is_long else "SHORT"
                return True, direction
        return self._open_side is not None, self._open_side

    def on_quote(self, context, quote):
        if quote.instrument != self._instrument:
            return None
        self._orderflow_mode = True
        closed = self._orderflow_builder.process(quote)
        if closed is None:
            return None
        return self.on_orderflow_candle(context, closed)

    def on_depth(self, context, depth):
        """Feed L2 snapshots into the orderbook tracker for absorption corroboration."""
        if depth.instrument != self._instrument:
            return None
        before_bid = self._book_tracker.count_swept_levels(side="bid")
        before_ask = self._book_tracker.count_swept_levels(side="ask")
        self._book_tracker.update(depth)
        self._bar_swept["bid"] += self._book_tracker.count_swept_levels(side="bid") - before_bid
        self._bar_swept["ask"] += self._book_tracker.count_swept_levels(side="ask") - before_ask
        return None

    def on_fill(self, context, fill):
        """Track position and consecutive-loss streak from fills."""
        if fill.instrument != self._instrument:
            return
        side = "LONG" if fill.side == OrderSide.BUY else "SHORT"
        qty = fill.quantity.value
        price = fill.price.value
        if self._open_side is None:
            self._open_side = side
            self._open_qty = qty
            self._open_price = price
            return
        if side == self._open_side:
            base_price = self._open_price if self._open_price is not None else price
            total = self._open_qty + qty
            self._open_price = (base_price * self._open_qty + price * qty) / total
            self._open_qty = total
            return
        # Closing fill — realize P&L on the closed portion.
        closed = min(qty, self._open_qty)
        base_price = self._open_price if self._open_price is not None else price
        if self._open_side == "LONG":
            profit = (price - base_price) * closed
        else:
            profit = (base_price - price) * closed
        self._update_streak(profit)
        self._open_qty -= closed
        if self._open_qty <= 0:
            self._open_side = None
            self._open_qty = Decimal("0")
            self._open_price = None

    def record_trade_outcome(self, profit: Decimal) -> None:
        """Explicit loss-cushion hook for session/exit integrations."""
        self._update_streak(profit)

    def _update_streak(self, profit: Decimal) -> None:
        if profit < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

    def on_event(self, event):
        return None

    def _book_snapshot(self) -> BookSnapshot:
        state = self._book_tracker.latest_state
        if state is None:
            return BookSnapshot()
        return BookSnapshot(
            imbalance_ratio=Decimal(str(state.imbalance_ratio)),
            path_of_least_resistance=state.path_of_least_resistance,
            swept_bids=self._bar_swept["bid"],
            swept_asks=self._bar_swept["ask"],
        )


__all__ = ["AMTStrategy"]
