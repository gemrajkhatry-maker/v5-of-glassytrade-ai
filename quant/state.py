"""StateProjector — folds the quant event stream into the frontend view-state.

Pure and deterministic: feeding the same event sequence always produces the
same per-symbol snapshot. The snapshot fields mirror the camelCase keys the
WS adapter (``quant.ws_adapter``) emits, which is the contract the frontend
reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from quant.contracts.aggregates import INITIAL_CAPITAL
from quant.contracts.timezones import IST
from quant.decision.decision_service import QuantDecision
from quant.events import (
    AgentDecisionProduced,
    AmtUpdated,
    BarClosed,
    DecisionProduced,
    DepthUpdated,
    Event,
    PositionClosed,
    PositionOpened,
    PositionReduced,
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
    quant_decision: dict | None = None
    risk_state: dict | None = None
    portfolio: dict | None = None
    depth: dict | None = None
    amt: dict | None = None
    agent_decision: dict | None = None






_EPOCH_2000 = 946684800


def _epoch_to_iso(time_str: str) -> str:
    """Normalize a quant tick/bar time to the WS ISO-8601 IST contract.

    Live ticks are unix-epoch strings (``"1786095001"`` or ``"1786095001.0"``).
    ``int()`` rejects the float form Dhan history still emits — that used to
    pass through unchanged, after which ``time[:10]`` was treated as a calendar
    date and VWAP/CVD/Triple-A reset every bar.
    """
    text = str(time_str or "").strip()
    if not text:
        return time_str
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST).isoformat()
    except (TypeError, ValueError):
        pass
    try:
        epoch = float(text)
    except (TypeError, ValueError):
        return time_str
    if epoch < _EPOCH_2000:
        return time_str
    return datetime.fromtimestamp(epoch, tz=IST).isoformat()


def session_date_key(time_str: str) -> str:
    """IST calendar date ``YYYY-MM-DD``, or ``''`` for synthetic ids.

    Unparseable stamps (``t300``) share one session so detectors can accumulate.
    Never use ``time[:10]`` — that is not a date for epoch strings.
    """
    iso = _epoch_to_iso(str(time_str or ""))
    if len(iso) >= 10 and iso[4] == "-" and iso[7] == "-":
        return iso[:10]
    return ""


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
        "consecutiveLosses": risk.consecutive_losses,
        "dailyPnl": risk.daily_pnl,
        "tradesToday": getattr(risk, "trades_today", 0),
        "equity": getattr(risk, "equity", float(INITIAL_CAPITAL)),
        # Contract parity with the legacy risk DTO — SessionRisk does not yet
        # track drift, so these default off until a drift source exists.
        "driftAlert": False,
        "driftMessage": "",
    }


def _position_to_view(position: Position, fill: Fill | None = None) -> dict:
    sig = position.order.signal
    dto = {
        "id": position._id,
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


import threading


class StateProjector:
    """Fold events per symbol into the latest frontend view-state."""

    def __init__(self) -> None:
        self._state: dict[str, dict] = {}
        self._lock = threading.RLock()

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
            if tick.depth is not None:
                s["depth"] = tick.depth
            if current_bar is not None:
                s["tick"] = _bar_to_tick(current_bar)

    def on_event(self, event: Event) -> None:
        with self._lock:
            s = self._symbol_state(event.symbol)
            if isinstance(event, BarClosed):
                s["ltp"] = float(event.bar.close)
                s["oi"] = float(getattr(event.bar, "oi", 0.0) or 0.0)
                s["tick"] = _bar_to_tick(event.bar)
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
                self._remove_open(fill.position._id, s["portfolio"])
                s["portfolio"]["closedTrades"].append(_position_to_view(fill.position, fill))
            elif isinstance(event, PositionReduced):
                s["portfolio"] = self._portfolio(s["portfolio"])
                reduced = event.remaining
                for p in s["portfolio"]["positions"]:
                    if p.get("id") == reduced._id:
                        p["size"] = float(reduced.size)
                        p["pnl"] = float(event.fill.pnl)
                        break
            elif isinstance(event, DepthUpdated):
                s["depth"] = event.depth
            elif isinstance(event, AmtUpdated):
                s["amt"] = event.amt
            elif isinstance(event, AgentDecisionProduced):
                s["agent_decision"] = event.decision

    def snapshot(self, symbol: str) -> ViewState:
        with self._lock:
            s = self._symbol_state(symbol)
            return ViewState(
                symbol=symbol,
                tick=s["tick"],
                ltp=s["ltp"],
                oi=s["oi"],
                quant_decision=s["quant_decision"],
                risk_state=s["risk_state"],
                portfolio=self._portfolio(s["portfolio"], ltp=s["ltp"]),
                depth=s["depth"],
                amt=s["amt"],
                agent_decision=s.get("agent_decision"),
            )

    def _symbol_state(self, symbol: str) -> dict:
        if symbol not in self._state:
            self._state[symbol] = {
                "tick": None,
                "ltp": None,
                "oi": None,
                "quant_decision": None,
                "risk_state": None,
                "portfolio": None,
                "depth": None,
                "amt": None,
                "agent_decision": None,
            }
        return self._state[symbol]

    @staticmethod
    def _portfolio(current: dict | None, ltp: float | None = None) -> dict:
        """Portfolio DTO — ALWAYS the full frontend contract shape.

        The WS snapshot protocol the frontend was built against guarantees
        ``balance/equity/leverage`` plus ``positions``/``closedTrades`` arrays on
        every message (legacy ``portfolio_to_dto``). The greenfield projector
        only tracks positions; the monetary fields default to the paper-account
        values until a real portfolio source exists.
        """
        # Contract defaults — MUST mirror quant/ws_adapter.view_state_to_ws and
        # the frontend createInstrumentState (hooks/useServerTradingSystem.ts).
        # Paper account capital: ₹1 crore (10M).
        base = {
            "balance": float(INITIAL_CAPITAL),
            "equity": float(INITIAL_CAPITAL),
            "leverage": 10,
            "positions": [],
            "closedTrades": [],
        }
        if current is None:
            return base

        raw_positions = current.get("positions", base["positions"])
        positions = [dict(p) for p in raw_positions]
        closed_trades = current.get("closedTrades", base["closedTrades"])

        # Compute live floating unrealized P&L for open positions using latest LTP
        if ltp is not None and ltp > 0:
            for p in positions:
                if p.get("status") == "OPEN":
                    entry = float(p.get("entryPrice", 0.0))
                    size = float(p.get("size", 0.0))
                    # size is positive for LONG, negative for SHORT
                    p["pnl"] = round((ltp - entry) * size, 2)
                    p["currentPrice"] = float(ltp)

        closed_pnl = sum(float(t.get("pnl", 0.0)) for t in closed_trades)
        open_pnl = sum(float(p.get("pnl", 0.0)) for p in positions)
        starting_capital = float(current.get("balance", base["balance"]))
        equity = round(starting_capital + closed_pnl + open_pnl, 2)

        return {
            **base,
            **current,
            "balance": starting_capital,
            "equity": equity,
            "positions": positions,
            "closedTrades": closed_trades,
        }

    @staticmethod
    def _remove_open(position_id: str, portfolio: dict) -> None:
        positions = portfolio["positions"]
        for i, p in enumerate(positions):
            if p.get("id") == position_id:
                del positions[i]
                break
