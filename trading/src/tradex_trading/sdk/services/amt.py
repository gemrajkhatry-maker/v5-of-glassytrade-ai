"""AMTService — read-side AMT projection over the session bus.

One pure :class:`AMTKernel` per instrument, fed by the same bus the strategy
layer consumes (``Candle`` / ``Quote`` / ``Depth``). This service is a
*read model* for dashboards and the UI — it never places orders and shares no
state with the trading strategy (the write path). Deterministic: the same
events produce the same snapshot sequence.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from tradex_domain import Fill, OrderSide
from tradex_domain.market import Candle, Depth, Quote

from tradex_trading.analytics.candle import OrderflowCandleBuilder
from tradex_trading.analytics.orderbook import OrderbookTracker
from tradex_trading.strategy.extensions.amt.gates import AMTDecisionContext, evaluate
from tradex_trading.strategy.extensions.amt.kernel import AMTKernel
from tradex_trading.strategy.extensions.amt.model import (
    AMTDecision,
    AMTSnapshot,
    AMTStrategyConfig,
    BookSnapshot,
)
from tradex_trading.strategy.extensions.amt.scanner import AMTScanResult, score_snapshot

SnapshotListener = Callable[[AMTSnapshot], None]
DecisionListener = Callable[[datetime, AMTDecision], None]


@dataclass(slots=True)
class _PositionState:
    """Fill-derived open position (side + quantity) for the decision trace."""

    side: str
    qty: Decimal


def decision_to_dict(decision: AMTDecision, timestamp: datetime | None = None) -> dict[str, Any]:
    """JSON-safe DTO for an AMT decision record."""
    dec = lambda value: str(value) if value is not None else None  # noqa: E731
    return {
        "timestamp": timestamp.isoformat() if timestamp else None,
        "approved": decision.approved,
        "setup": decision.setup,
        "direction": decision.direction,
        "entry": dec(decision.entry),
        "stop_loss": dec(decision.stop_loss),
        "take_profit": dec(decision.take_profit),
        "risk_reward": str(decision.risk_reward),
        "reason": decision.reason,
        "failed_gates": list(decision.failed_gates),
        "cushion": str(decision.cushion),
        "pyramid": decision.pyramid,
    }


def snapshot_to_dict(snapshot: AMTSnapshot) -> dict[str, Any]:
    """JSON-safe DTO for an AMT snapshot (Decimals -> str, tuples -> lists)."""
    dec = lambda value: str(value) if value is not None else None  # noqa: E731
    return {
        "instrument": str(snapshot.instrument.instrument_id),
        "timestamp": snapshot.timestamp.isoformat() if snapshot.timestamp else None,
        "close": dec(snapshot.close),
        "poc": dec(snapshot.poc),
        "vah": dec(snapshot.vah),
        "val": dec(snapshot.val),
        "vwap": str(snapshot.vwap),
        "upper_1": str(snapshot.upper_1),
        "lower_1": str(snapshot.lower_1),
        "upper_2": str(snapshot.upper_2),
        "lower_2": str(snapshot.lower_2),
        "vwap_std": str(snapshot.vwap_std),
        "delta": str(snapshot.delta),
        "cvd": str(snapshot.cvd),
        "cvd_slope": str(snapshot.cvd_slope),
        "cvd_divergence": snapshot.cvd_divergence,
        "absorption_side": snapshot.absorption_side,
        "absorption_strength": str(snapshot.absorption_strength),
        "absorption_age": snapshot.absorption_age,
        "ib_high": dec(snapshot.ib_high),
        "ib_low": dec(snapshot.ib_low),
        "ib_complete": snapshot.ib_complete,
        "location": snapshot.location,
        "nearest_level": dec(snapshot.nearest_level),
        "profile_shape": snapshot.profile_shape,
        "lvn_levels": [str(level) for level in snapshot.lvn_levels],
        "hvn_levels": [str(level) for level in snapshot.hvn_levels],
        "phase": snapshot.phase.value,
        "direction": snapshot.direction,
        "book_imbalance": str(snapshot.book_imbalance),
        "book_polr": snapshot.book_polr,
        "book_swept_bids": snapshot.book_swept_bids,
        "book_swept_asks": snapshot.book_swept_asks,
        "absorption_confirmed": snapshot.absorption_confirmed,
        "aggression_score": str(snapshot.aggression_score),
    }


class AMTService:
    """Per-instrument AMT kernels driven by bus events (read side only)."""

    def __init__(
        self,
        config: AMTStrategyConfig | None = None,
        *,
        max_history: int = 500,
    ) -> None:
        self.config = config or AMTStrategyConfig()
        self._max_history = max_history
        self._kernels: dict[str, AMTKernel] = {}
        self._builders: dict[str, OrderflowCandleBuilder] = {}
        self._trackers: dict[str, OrderbookTracker] = {}
        self._swept: dict[str, dict[str, int]] = {}
        self._snapshots: dict[str, AMTSnapshot] = {}
        self._history: dict[str, list[AMTSnapshot]] = {}
        self._decisions: dict[str, list[tuple[datetime, AMTDecision]]] = {}
        #: Fill-derived position state per instrument, mirroring the strategy
        #: so the read-side decision trace sees the same gates.
        self._positions: dict[str, _PositionState] = {}
        self._listeners: list[SnapshotListener] = []
        self._decision_listeners: list[DecisionListener] = []
        self._subs: list[Any] = []
        self._bus: Any = None

    def attach(self, bus: Any) -> None:
        """Subscribe the service to a reactive bus (idempotency-guarded)."""
        if self._bus is not None:
            raise RuntimeError("AMTService already attached to a bus")
        self._bus = bus
        self._subs.extend([
            bus.of_type(Candle).subscribe(self.on_candle),
            bus.of_type(Quote).subscribe(self.on_quote),
            bus.of_type(Depth).subscribe(self.on_depth),
            bus.of_type(Fill).subscribe(self.on_fill),
        ])

    def dispose(self) -> None:
        for sub in self._subs:
            sub.dispose()
        self._subs.clear()
        self._bus = None

    # --- bus handlers -------------------------------------------------------

    def on_candle(self, candle: Candle) -> None:
        iid = str(candle.instrument.instrument_id)
        kernel = self._kernels.setdefault(iid, AMTKernel(self.config))
        snapshot = kernel.update(candle, self._book_snapshot(iid))
        self._swept[iid] = {"bid": 0, "ask": 0}
        self._record(iid, snapshot)

    def on_quote(self, quote: Quote) -> None:
        iid = str(quote.instrument.instrument_id)
        builder = self._builders.setdefault(iid, OrderflowCandleBuilder())
        closed = builder.process(quote)
        if closed is None:
            return
        kernel = self._kernels.setdefault(iid, AMTKernel(self.config))
        snapshot = kernel.update(closed, self._book_snapshot(iid))
        self._swept[iid] = {"bid": 0, "ask": 0}
        self._record(iid, snapshot)

    def on_depth(self, depth: Depth) -> None:
        iid = str(depth.instrument.instrument_id)
        tracker = self._trackers.setdefault(iid, OrderbookTracker())
        before_bid = tracker.count_swept_levels(side="bid")
        before_ask = tracker.count_swept_levels(side="ask")
        tracker.update(depth)
        swept = self._swept.setdefault(iid, {"bid": 0, "ask": 0})
        swept["bid"] += tracker.count_swept_levels(side="bid") - before_bid
        swept["ask"] += tracker.count_swept_levels(side="ask") - before_ask

    def on_fill(self, fill: Fill) -> None:
        """Track open-position state so the decision trace sees pyramid gates."""
        iid = str(fill.instrument.instrument_id)
        side = "LONG" if fill.side == OrderSide.BUY else "SHORT"
        qty = fill.quantity.value
        pos = self._positions.get(iid)
        if pos is None:
            self._positions[iid] = _PositionState(side=side, qty=qty)
            return
        if side == pos.side:
            pos.qty += qty
        else:
            pos.qty -= qty
            if pos.qty <= 0:
                del self._positions[iid]

    def _position_state(self, iid: str) -> tuple[bool, str | None]:
        pos = self._positions.get(iid)
        if pos is None:
            return False, None
        return True, pos.side

    # --- read API ------------------------------------------------------------

    def snapshot(self, instrument_id: str) -> AMTSnapshot | None:
        return self._snapshots.get(instrument_id)

    def snapshots_all(self) -> dict[str, AMTSnapshot]:
        return dict(self._snapshots)

    def history(self, instrument_id: str, limit: int = 100) -> list[AMTSnapshot]:
        return self._history.get(instrument_id, [])[-limit:]

    def decisions(
        self, instrument_id: str, limit: int = 100
    ) -> list[tuple[datetime, AMTDecision]]:
        """Recent AMT decisions (timestamp, decision) for an instrument."""
        return self._decisions.get(instrument_id, [])[-limit:]

    def instruments(self) -> list[str]:
        return sorted(self._snapshots)

    def scan(self, limit: int = 20) -> list[AMTScanResult]:
        """Rank tracked instruments by their latest setup strength."""
        results: list[AMTScanResult] = []
        for iid, snapshot in self._snapshots.items():
            score, setup = score_snapshot(snapshot)
            if score <= 0:
                continue
            results.append(AMTScanResult(
                instrument=snapshot.instrument,
                phase=snapshot.phase.value,
                direction=snapshot.direction,
                setup=setup,
                score=score,
                absorption_side=snapshot.absorption_side,
                absorption_strength=snapshot.absorption_strength,
                timestamp=snapshot.timestamp,
            ))
        results.sort(key=lambda r: (-r.score, r.instrument.symbol))
        return results[:limit] if limit else results

    def subscribe(self, listener: SnapshotListener) -> Callable[[], None]:
        """Subscribe to every new snapshot; returns a dispose callable."""
        self._listeners.append(listener)

        def dispose() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return dispose

    def subscribe_decisions(self, listener: DecisionListener) -> Callable[[], None]:
        """Subscribe to every new decision record; returns a dispose callable."""
        self._decision_listeners.append(listener)

        def dispose() -> None:
            if listener in self._decision_listeners:
                self._decision_listeners.remove(listener)

        return dispose

    # --- internals ------------------------------------------------------------

    def _book_snapshot(self, iid: str) -> BookSnapshot:
        tracker = self._trackers.get(iid)
        if tracker is None or tracker.latest_state is None:
            return BookSnapshot()
        state = tracker.latest_state
        swept = self._swept.get(iid, {"bid": 0, "ask": 0})
        return BookSnapshot(
            imbalance_ratio=Decimal(str(state.imbalance_ratio)),
            path_of_least_resistance=state.path_of_least_resistance,
            swept_bids=swept.get("bid", 0),
            swept_asks=swept.get("ask", 0),
        )

    def _record(self, iid: str, snapshot: AMTSnapshot) -> None:
        self._snapshots[iid] = snapshot
        hist = self._history.setdefault(iid, [])
        hist.append(snapshot)
        if len(hist) > self._max_history:
            del hist[:-self._max_history]

        position_open, position_direction = self._position_state(iid)
        decision = evaluate(AMTDecisionContext(
            snapshot=snapshot,
            position_open=position_open,
            position_direction=position_direction,
            stop_cushion=self.config.tick_size * self.config.stop_cushion_ticks,
            pyramid_enabled=self.config.pyramid_enabled,
            pyramid_threshold=self.config.pyramid_aggression_score,
        ))
        records = self._decisions.setdefault(iid, [])
        records.append((snapshot.timestamp, decision))
        if len(records) > self._max_history:
            del records[:-self._max_history]

        for listener in list(self._listeners):
            listener(snapshot)
        for decision_listener in list(self._decision_listeners):
            decision_listener(snapshot.timestamp, decision)


__all__ = ["AMTService", "decision_to_dict", "snapshot_to_dict"]
