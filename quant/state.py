"""State derivation — folds the quant event stream into the frontend view-state.

One position authority, one live cache:

1. ``project_state(EngineState)`` — canonical: derives the book (positions,
   risk, ltp from the last closed bar) from ``EventStore.fold()``. This is
   the sole source of truth for the trading state.
2. ``LiveQuoteCache`` — per-tick live cache (ltp/oi/depth/forming candle
   between bar closes). ``QuantCoordinator.snapshot()`` merges the
   fold-derived book with this cache's live fields — see quant/multi_engine.py.

The snapshot fields mirror the camelCase keys the WS adapter emits.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from quant.contracts.aggregates import INITIAL_CAPITAL
from quant.contracts.timezones import IST, epoch_to_iso
from quant.decision.decision_service import QuantDecision
from quant.execution.risk import RiskState
from quant.state_machine import EngineState


@dataclass(frozen=True)
class ViewState:
    symbol: str
    tick: dict | None = None
    ltp: float | None = None
    oi: float | None = None
    quant_decision: dict | None = None
    risk_state: dict | None = None
    portfolio: dict | None = None
    depth: dict | None = None
    amt: dict | None = None
    agent_decision: dict | None = None
    laya_decision: dict | None = None


def project_state(state: EngineState) -> ViewState:
    """Derive ViewState from a folded EngineState.

    This is the canonical path: ``EventStore.fold()`` → ``project_state()``
    → ``view_state_to_ws()``.
    """
    bar = state.last_bar
    tick = _bar_to_tick(bar) if bar is not None else None
    ltp = float(bar.close) if bar is not None else None
    oi = float(bar.oi) if bar is not None else None
    risk = _risk_to_view(state.risk) if state.risk else None
    portfolio = _engine_portfolio(state)
    return ViewState(
        symbol=state.symbol,
        tick=tick,
        ltp=ltp,
        oi=oi,
        risk_state=risk,
        portfolio=portfolio,
    )


def _engine_portfolio(state: EngineState) -> dict:
    """Build the frontend portfolio DTO from a folded EngineState.

    ``equity`` reflects the paper starting capital plus realized P&L
    accumulated by the fold (PositionClosed events) plus the floating P&L of
    any open position.
    """
    realized = float(getattr(state, "realized_pnl", 0.0) or 0.0)
    closed = list(getattr(state, "closed_trades", ()) or [])
    base = {
        "balance": float(INITIAL_CAPITAL),
        "equity": round(float(INITIAL_CAPITAL) + realized, 2),
        "leverage": 10,
        "positions": [],
        "closedTrades": closed,
    }
    if state.position is None:
        return base
    pos = state.position
    entry = float(pos.entry)
    size = float(pos.size)
    ltp = float(state.last_bar.close) if state.last_bar else None
    pnl = round((ltp - entry) * size, 2) if ltp else 0.0
    entry_time = str(getattr(pos, "entry_time", "") or "")
    if not entry_time and state.last_bar:
        entry_time = str(state.last_bar.time or "")
    if not entry_time:
        entry_time = datetime.now(tz=IST).isoformat()
    position_dto = {
        "id": pos.id,
        "symbol": state.symbol,
        "side": pos.side,
        "source": "AMT",
        "entryPrice": entry,
        "size": size,
        "stopLoss": float(pos.sl),
        "takeProfit": float(pos.tp),
        "pnl": pnl,
        "entryTime": _epoch_to_iso(entry_time),
        "status": "OPEN",
    }
    if ltp is not None:
        position_dto["currentPrice"] = ltp
    return {
        **base,
        "equity": round(float(INITIAL_CAPITAL) + realized + pnl, 2),
        "positions": [position_dto],
    }


_EPOCH_2000 = 946684800


def _epoch_to_iso(time_str: str | float | int | None) -> str:
    """Normalize a quant tick/bar time to the WS ISO-8601 IST contract."""
    return epoch_to_iso(time_str)


def session_date_key(time_str: str) -> str:
    """IST calendar date ``YYYY-MM-DD``, or ``''`` for synthetic ids.

    Unparseable stamps (``t300``) share one session so detectors can accumulate.
    Never use ``time[:10]`` — that is not a date for epoch strings.
    """
    iso = _epoch_to_iso(str(time_str or ""))
    if len(iso) >= 10 and iso[4] == "-" and iso[7] == "-":
        return iso[:10]
    return ""


def _bar_to_tick(bar, interval_sec: int = 60) -> dict:
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
        "takerBuyVolume": float(getattr(bar, "buy_volume", 0.0)),
        "delta": float(getattr(bar, "delta", 0.0)),
        "barIntervalSec": interval_sec,
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
                "modelLabel": sig.model_label,
            }
            if sig is not None
            else None
        ),
        "modelLabel": decision.model_label,
    }


def _risk_to_view(risk: RiskState) -> dict:
    return {
        "halted": risk.halted,
        "haltReason": risk.halt_reason,
        "consecutiveLosses": getattr(risk, "consecutive_losses", 0),
        "dailyPnl": risk.daily_pnl,
        "tradesToday": getattr(risk, "trades_today", 0),
        "equity": getattr(risk, "equity", float(INITIAL_CAPITAL)),
        # Contract parity with the legacy risk DTO — SessionRisk does not yet
        # track drift, so these default off until a drift source exists.
        "driftAlert": False,
        "driftMessage": "",
    }


def _position_to_view(position: Any, fill: Any | None = None) -> dict:
    pos_id = str(getattr(position, "_id", None) or getattr(position, "id", "") or uuid.uuid4())
    sig = getattr(position, "order", None) and getattr(position.order, "signal", None)
    sym = getattr(position, "symbol", "") or (sig.symbol if sig else "")
    side = getattr(position, "side", "") or (sig.type if sig else ("LONG" if getattr(position, "size", 0) > 0 else "SHORT"))
    entry_px = float(getattr(position, "open_price", 0.0) or getattr(position, "entry_price", 0.0))
    size_val = float(getattr(position, "size", 0.0))
    sl = float(getattr(position, "stop_loss", 0.0) or (sig.sl if sig else 0.0))
    tp = float(getattr(position, "take_profit", 0.0) or (sig.tp if sig else 0.0))
    pnl_val = float(fill.pnl if fill is not None else getattr(position, "realized_pnl", 0.0))
    open_t = getattr(position, "open_time", "") or getattr(position, "entry_time", "")

    dto = {
        "id": pos_id,
        "symbol": sym,
        "side": side,
        "source": "AMT",
        "entryPrice": entry_px,
        "size": size_val,
        "stopLoss": sl,
        "takeProfit": tp,
        "pnl": pnl_val,
        "entryTime": _epoch_to_iso(open_t),
        "status": "CLOSED" if fill is not None else "OPEN",
    }
    if fill is not None:
        dto["exitPrice"] = float(fill.close_price)
        dto["exitTime"] = _epoch_to_iso(fill.close_time)
        dto["closeReason"] = fill.reason
    return dto


class LiveQuoteCache:
    """Per-symbol per-tick live quote cache.

    Holds ONLY the fields the event-fold cannot provide without retaining
    closed-trade history or per-tick granularity: ltp, oi, depth, and the
    forming candle between bar closes.

    NOT a position authority — positions, risk, portfolio, amt, decisions
    all come from ``EventStore.fold() → project_state()`` or the engine's
    own ``latest_*`` attributes.
    """

    def __init__(self, interval_sec: int = 60) -> None:
        self._state: dict[str, dict] = {}
        self._lock = threading.RLock()
        self._interval_sec = interval_sec

    def on_quote(self, symbol: str, tick, current_bar=None) -> None:
        """Per-tick LTP/OI/depth and live forming candle refresh.

        Called by the engine on every raw tick so the WS snapshot carries a
        live ``ltp``/``oi``/``depth`` and real-time forming ``tick`` (candle)
        between bar closes, enabling the frontend chart to paint the live candle.
        """
        with self._lock:
            s = self._symbol_state(symbol)
            s["ltp"] = float(tick.price)
            s["oi"] = float(tick.oi)
            s["depth"] = getattr(tick, "depth", None)
            if current_bar is not None:
                s["tick"] = _bar_to_tick(current_bar, interval_sec=self._interval_sec)

    def snapshot(self, symbol: str) -> ViewState:
        """Return a ViewState with only the live-cache fields populated.

        The caller (QuantCoordinator.snapshot) merges this with the fold-derived
        ViewState for positions/risk/portfolio.
        """
        with self._lock:
            s = self._symbol_state(symbol)
            return ViewState(
                symbol=symbol,
                tick=s["tick"],
                ltp=s["ltp"],
                oi=s["oi"],
                depth=s["depth"],
            )

    def _symbol_state(self, symbol: str) -> dict:
        if symbol not in self._state:
            self._state[symbol] = {
                "tick": None,
                "ltp": None,
                "oi": None,
                "depth": None,
            }
        return self._state[symbol]
