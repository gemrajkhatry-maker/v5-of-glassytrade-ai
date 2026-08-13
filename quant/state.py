"""StateProjector — folds the quant event stream into the frontend view-state.

Pure and deterministic: feeding the same event sequence always produces the
same per-symbol snapshot. The ``auction`` dict mirrors the camelCase keys the
backend serializer emits (``backend.app.application.services.quant_bridge``),
which is the WS contract the frontend already reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from quant.auction_state import AuctionState
from quant.contracts.timezones import IST
from quant.decision.decision_service import QuantDecision
from quant.events import (
    AmtUpdated,
    AuctionUpdated,
    BarClosed,
    DecisionProduced,
    DepthUpdated,
    Event,
    PositionClosed,
    PositionOpened,
    RiskUpdated,
)
from quant.execution.order import Fill, Position
from quant.execution.risk import RiskState


@dataclass(frozen=True)
class ViewState:
    symbol: str
    tick: dict | None = None
    ltp: float | None = None
    oi: float | None = None
    auction: dict | None = None
    quant_decision: dict | None = None
    risk_state: dict | None = None
    portfolio: dict | None = None
    depth: dict | None = None
    amt: dict | None = None


def _auction_to_view(state: AuctionState) -> dict:
    """Serialize an AuctionState to the camelCase WS ``auction`` DTO.

    Mirrors ``auction_state_to_dto`` in the backend serializer so the keys the
    frontend reads (tripleAPhase, volumeProfile, vwap, orderFlow, ...) match
    exactly.
    """
    vp = state.volume_profile
    vw = state.vwap
    of = state.order_flow
    loc = state.location
    ab = state.absorption
    return {
        "time": _epoch_to_iso(state.time),
        "close": round(float(state.close), 4),
        "volumeProfile": {
            "poc": round(vp.poc, 4),
            "vah": round(vp.vah, 4),
            "val": round(vp.val, 4),
            "step": round(vp.step, 4),
            "totalVolume": round(vp.total_volume, 2),
        },
        "vwap": {
            "value": round(vw.value, 4),
            "upper1": round(vw.upper_1, 4),
            "lower1": round(vw.lower_1, 4),
            "upper2": round(vw.upper_2, 4),
            "lower2": round(vw.lower_2, 4),
            "std": round(vw.std, 4),
            "deviationSigmas": round(vw.deviation_sigmas, 4),
        },
        "orderFlow": {
            "delta": round(of.delta, 2),
            "cvd": round(of.cvd, 2),
            "cvdSlope": round(of.cvd_slope, 4),
            "cvdDivergence": of.cvd_divergence,
        },
        "absorption": (
            {
                "side": ab.side,
                "price": round(ab.price, 4),
                "volume": round(ab.volume, 2),
                "strength": round(ab.strength, 4),
                "barAge": ab.bar_age,
            }
            if ab is not None
            else None
        ),
        "location": {
            "ibHigh": round(loc.ib_high, 4),
            "ibLow": round(loc.ib_low, 4),
            "ibComplete": loc.ib_complete,
            "zone": loc.zone,
            "nearestLevel": round(loc.nearest_level, 4),
            "distanceToLevel": round(loc.distance_to_level, 4),
        },
        "tripleAPhase": state.triple_a_phase,
        "tripleASignal": state.triple_a_signal,
    }


def _epoch_to_iso(time_str: str) -> str:
    """Normalize a quant tick/bar time to the WS ISO-8601 IST contract.

    The live gateway emits unix-epoch strings (e.g. ``"1786095001"``); the
    frontend parses every ``time`` with ``new Date()``, which returns NaN for
    bare epoch strings — silently dropping live ticks from the chart. The REST
    history endpoint (``ohlc_to_dto``) already emits ISO ``+05:30`` times, so
    ticks are normalized to the same format here at the serialization
    boundary. Values that are already ISO (or not epoch-parseable) pass
    through unchanged.
    """
    try:
        epoch = int(str(time_str).strip())
    except (TypeError, ValueError):
        return time_str
    return datetime.fromtimestamp(epoch, tz=IST).isoformat()


def _bar_to_tick(bar) -> dict:
    """Map a closed quant Bar to the frontend OHLCData tick shape.

    ``vwap`` is a required schema field — BarAggregator now accumulates a real
    per-bar VWAP (``bar.vwap``); older Bar constructions default to 0.0.
    ``time`` is normalized to the ISO-8601 IST string the WS contract
    guarantees (see ``_epoch_to_iso``) so the chart can merge it with REST
    history candles.
    """
    return {
        "time": _epoch_to_iso(bar.time),
        "open": float(bar.open),
        "high": float(bar.high),
        "low": float(bar.low),
        "close": float(bar.close),
        "volume": float(bar.volume),
        "vwap": float(getattr(bar, "vwap", 0.0) or 0.0),
        "takerBuyVolume": float(bar.buy_volume),
        "delta": float(bar.delta),
    }


def _decision_to_view(decision: QuantDecision) -> dict:
    sig = decision.signal
    return {
        "approved": bool(decision.approved),
        "reason": decision.reason,
        "phase": decision.phase,
        "blockReasons": list(decision.block_reasons),
        "gateResults": [
            {"gate": g.gate, "name": g.name, "passed": bool(g.passed), "reason": g.reason}
            for g in decision.gate_results
        ],
        "signal": (
            {
                "type": sig.type,
                "entry": round(float(sig.entry), 4),
                "sl": round(float(sig.sl), 4),
                "tp": round(float(sig.tp), 4),
                "rr": round(float(sig.rr), 4),
                "confidence": round(float(sig.confidence), 4),
            }
            if sig is not None
            else None
        ),
    }


def _risk_to_view(risk: RiskState) -> dict:
    return {
        "halted": risk.halted,
        "haltReason": risk.halt_reason,
        "consecutiveLosses": risk.consecutive_losses,
        "dailyPnl": risk.daily_pnl,
        # Contract parity with the legacy risk DTO — SessionRisk does not yet
        # track drift, so these default off until a drift source exists.
        "driftAlert": False,
        "driftMessage": "",
    }


def _position_to_view(position: Position, fill: Fill | None = None) -> dict:
    sig = position.order.signal
    dto = {
        "id": position.open_time,
        "symbol": sig.symbol,
        "side": sig.type,
        "source": "AMT",
        "entryPrice": float(position.open_price),
        "size": float(position.size),
        "stopLoss": float(sig.sl),
        "takeProfit": float(sig.tp),
        "pnl": float(fill.pnl if fill is not None else position.realized_pnl),
        # Times are normalized to the WS ISO contract — chart markers parse
        # entryTime/exitTime with new Date() and would NaN on epoch strings.
        "entryTime": _epoch_to_iso(position.open_time),
        "status": "CLOSED" if fill is not None else "OPEN",
    }
    if fill is not None:
        dto["exitPrice"] = float(fill.close_price)
        dto["exitTime"] = _epoch_to_iso(fill.close_time)
        dto["closeReason"] = fill.reason
    return dto


class StateProjector:
    """Fold events per symbol into the latest frontend view-state."""

    def __init__(self) -> None:
        self._state: dict[str, dict] = {}

    def on_quote(self, symbol: str, tick) -> None:
        """Per-tick LTP/OI/depth refresh (not an Event — bypasses bus/journal).

        Called by the engine on every raw tick so the WS snapshot carries a
        live ``ltp``/``oi``/``depth`` between bar closes (the gameloop polls
        snapshots every 0.5s, so the sidebar and order-flow cards stay live).
        """
        s = self._symbol_state(symbol)
        s["ltp"] = float(tick.price)
        s["oi"] = float(tick.oi)
        if tick.depth is not None:
            s["depth"] = tick.depth

    def on_event(self, event: Event) -> None:
        s = self._symbol_state(event.symbol)
        if isinstance(event, BarClosed):
            s["ltp"] = float(event.bar.close)
            s["oi"] = float(getattr(event.bar, "oi", 0.0) or 0.0)
            s["tick"] = _bar_to_tick(event.bar)
        elif isinstance(event, AuctionUpdated):
            s["auction"] = _auction_to_view(event.auction)
        elif isinstance(event, DecisionProduced):
            s["quant_decision"] = _decision_to_view(event.decision)
        elif isinstance(event, RiskUpdated):
            s["risk_state"] = _risk_to_view(event.risk)
        elif isinstance(event, PositionOpened):
            s["portfolio"] = self._portfolio(s["portfolio"])
            s["portfolio"]["positions"].append(_position_to_view(event.position))
        elif isinstance(event, PositionClosed):
            s["portfolio"] = self._portfolio(s["portfolio"])
            fill = event.fill
            self._remove_open(fill.position.open_time, s["portfolio"])
            s["portfolio"]["closedTrades"].append(_position_to_view(fill.position, fill))
        elif isinstance(event, DepthUpdated):
            s["depth"] = event.depth
        elif isinstance(event, AmtUpdated):
            s["amt"] = event.amt

    def snapshot(self, symbol: str) -> ViewState:
        s = self._symbol_state(symbol)
        return ViewState(
            symbol=symbol,
            tick=s["tick"],
            ltp=s["ltp"],
            oi=s["oi"],
            auction=s["auction"],
            quant_decision=s["quant_decision"],
            risk_state=s["risk_state"],
            portfolio=self._portfolio(s["portfolio"]),
            depth=s["depth"],
            amt=s["amt"],
        )

    def _symbol_state(self, symbol: str) -> dict:
        if symbol not in self._state:
            self._state[symbol] = {
                "tick": None,
                "ltp": None,
                "oi": None,
                "auction": None,
                "quant_decision": None,
                "risk_state": None,
                "portfolio": None,
                "depth": None,
                "amt": None,
            }
        return self._state[symbol]

    @staticmethod
    def _portfolio(current: dict | None) -> dict:
        """Portfolio DTO — ALWAYS the full frontend contract shape.

        The WS snapshot protocol the frontend was built against guarantees
        ``balance/equity/leverage`` plus ``positions``/``closedTrades`` arrays on
        every message (legacy ``portfolio_to_dto``). The greenfield projector
        only tracks positions; the monetary fields default to the paper-account
        values until a real portfolio source exists.
        """
        # Contract defaults — MUST mirror quant/ws_adapter.view_state_to_ws and
        # the frontend createInstrumentState (hooks/useServerTradingSystem.ts).
        # Paper account capital: ₹10 lakh (1M).
        base = {
            "balance": 1_000_000.0,
            "equity": 1_000_000.0,
            "leverage": 10,
            "positions": [],
            "closedTrades": [],
        }
        if current is None:
            return base
        return {
            **base,
            **current,
            "positions": current.get("positions", base["positions"]),
            "closedTrades": current.get("closedTrades", base["closedTrades"]),
        }

    @staticmethod
    def _remove_open(open_time: str, portfolio: dict) -> None:
        # entryTime is stored ISO-normalized (see _position_to_view) — normalize
        # the lookup key the same way so open positions match their closes.
        key = _epoch_to_iso(open_time)
        positions = portfolio["positions"]
        for i, p in enumerate(positions):
            if p["entryTime"] == key:
                del positions[i]
                break
