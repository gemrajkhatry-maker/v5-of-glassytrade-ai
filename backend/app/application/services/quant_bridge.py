"""Bridge between the greenfield `quant/` engine and the live backend.

Owns one `AuctionCoordinator` per symbol, feeds it closed bars (mapped from
the backend's OHLC candles), and serializes the resulting `AuctionState`
into the WS snapshot as the ``auction`` field. Purely additive — the legacy
AMT path is untouched; this is the *decision engine of record* in parallel.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# WS-REPLAY live-capture directory (guarded by QUANT_RECORD_REPLAY=1).
_REPLAY_LOG_DIR = Path(__file__).resolve().parents[3] / "live_trading_logs"
_replay_lock = threading.Lock()


def _replay_date(time_str: str) -> str:
    """Extract the YYYY-MM-DD date from an ISO-ish bar time, ``na`` otherwise."""
    head = str(time_str or "")[:10]
    if len(head) == 10 and head[4] == "-" and head[7] == "-":
        return head
    return "na"


def ohlc_to_quant_bar(ohlc: Any) -> "Bar":
    """Map a backend OHLC candle to a greenfield quant Bar."""
    from quant.bars import Bar

    vol = float(ohlc.volume)
    buy = float(getattr(ohlc, "taker_buy_volume", 0.0))
    delta = float(getattr(ohlc, "delta", 0.0))
    return Bar(
        time=ohlc.time,
        open=float(ohlc.open),
        high=float(ohlc.high),
        low=float(ohlc.low),
        close=float(ohlc.close),
        volume=vol,
        buy_volume=buy,
        sell_volume=max(0.0, vol - buy),
        delta=delta,
    )


def auction_state_to_dto(state: Any) -> dict:
    """Serialize a quant AuctionState to the camelCase WS ``auction`` DTO."""
    if state is None:
        return {}
    vp = state.volume_profile
    vw = state.vwap
    of = state.order_flow
    loc = state.location
    ab = state.absorption
    return {
        "time": state.time,
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


def quant_decision_to_dto(decision: Any) -> dict:
    """Serialize a ``QuantDecision`` to the stored/WS quant-decision DTO."""
    sig = decision.signal
    return {
        "approved": bool(decision.approved),
        "reason": decision.reason,
        "phase": decision.phase,
        "timestamp": sig.timestamp if sig is not None else None,
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


class QuantBridge:
    """Holds one AuctionCoordinator per symbol; safe for concurrent symbols."""

    def __init__(self) -> None:
        self._coordinators: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._last_bar_time: dict[str, str] = {}

    def _coordinator(self, symbol: str) -> Any:
        from quant.coordinator import AuctionCoordinator

        with self._lock:
            if symbol not in self._coordinators:
                self._coordinators[symbol] = AuctionCoordinator()
            return self._coordinators[symbol]

    def reset(self, symbol: str) -> None:
        with self._lock:
            self._coordinators.pop(symbol, None)
            self._last_bar_time.pop(symbol, None)

    def on_bar_close(self, symbol: str, ohlc: Any) -> dict:
        """Feed one closed bar; returns the serialized AuctionState DTO.

        Dedup: a bar is only fed once per (symbol, bar-time). Returns {} on a
        duplicate bar time so callers can skip rebroadcast cheaply.
        """
        state, bar, dto = self._feed_bar(symbol, ohlc)
        if state is not None and os.environ.get("QUANT_RECORD_REPLAY") == "1":
            self._record_replay(symbol, ohlc, bar, dto)
        return dto

    def _record_replay(self, symbol: str, ohlc: Any, bar: Any, dto: dict) -> None:
        """Append one (bar, AuctionState) record to the replay capture file.

        Guarded by the caller (env ``QUANT_RECORD_REPLAY=1``); the main path is
        byte-identical when the env is unset. Writes one JSONL line to
        ``backend/live_trading_logs/replay_<symbol>_<date>.jsonl``.
        """
        with _replay_lock:
            _REPLAY_LOG_DIR.mkdir(parents=True, exist_ok=True)
            path = _REPLAY_LOG_DIR / f"replay_{symbol}_{_replay_date(ohlc.time)}.jsonl"
            record = {
                "symbol": symbol,
                "time": bar.time,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "buy_volume": bar.buy_volume,
                "delta": bar.delta,
                "oi": float(getattr(ohlc, "oi", 0.0)),
                "auction": dto,
            }
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True))
                fh.write("\n")

    def _feed_bar(self, symbol: str, ohlc: Any) -> tuple[Any | None, Any | None, dict]:
        """Feed one closed bar; returns ``(AuctionState, quant Bar, DTO)``.

        Returns ``(None, None, {})`` for a duplicate bar time so callers can
        skip rebroadcast cheaply. Shared by the legacy ``on_bar_close`` and the
        decision path so both always see the exact same dedup semantics.
        """
        if self._last_bar_time.get(symbol) == ohlc.time:
            return None, None, {}
        self._last_bar_time[symbol] = ohlc.time
        bar = ohlc_to_quant_bar(ohlc)
        coord = self._coordinator(symbol)
        state = coord.on_bar_close(bar)
        return state, bar, auction_state_to_dto(state)

    def on_bar_close_with_decision(
        self,
        symbol: str,
        ohlc: Any,
        session: Any,
        ctx_facts: dict | None = None,
    ) -> dict:
        """Feed one closed bar, run the quant decision, and store it on the session.

        The auction DTO is identical to ``on_bar_close``. When
        ``QUANT_EXECUTION_MODE`` is not ``off`` (shadow/paper/live), the
        ``DecisionService`` is evaluated against the resulting ``AuctionState``
        and ``session.last_quant_decision`` (a DTO: {approved, reason, phase,
        timestamp, signal:{type,entry,sl,tp,rr,confidence}|None}) is stored so
        ``session_event_router`` can route execution from the quant signal. When
        the mode is ``off``, nothing is stored and the legacy path is
        byte-identical to today's ``QUANT_DECISION_ENABLED=false``.
        """
        from app.config import settings

        state, bar, dto = self._feed_bar(symbol, ohlc)
        if state is None:
            return dto  # duplicate bar time — nothing new to decide

        if settings.QUANT_EXECUTION_MODE == "off":
            return dto

        from quant.decision.decision_service import DecisionService

        ctx = self._build_decision_context(symbol, state, bar, session, ctx_facts or {})
        decision = DecisionService().evaluate(ctx)
        with session._lock:
            session.last_quant_decision = quant_decision_to_dto(decision)
        return dto

    def _build_decision_context(
        self,
        symbol: str,
        state: Any,
        bar: Any,
        session: Any,
        facts: dict,
    ) -> Any:
        """Assemble a ``DecisionContext`` from the session + caller facts."""
        from quant.decision.context import DecisionContext

        agent_direction = facts.get("agent_direction")
        if agent_direction is None:
            agent_direction = getattr(
                getattr(session, "_agent_decision", None), "direction", None
            )

        position_open = facts.get("position_open")
        if position_open is None:
            try:
                position_open = bool(
                    session.portfolio
                    and any(p.is_open for p in session.portfolio.positions)
                )
            except Exception:
                position_open = False

        return DecisionContext(
            state=state,
            bar=bar,
            symbol=symbol,
            session_open=facts.get("session_open", True),
            warmup_complete=facts.get("warmup_complete", True),
            position_open=bool(position_open),
            cooldown_remaining_sec=int(facts.get("cooldown_remaining_sec", 0)),
            risk_halted=bool(facts.get("risk_halted", False)),
            agent_direction=agent_direction,
            agent_probability=float(facts.get("agent_probability", 0.0)),
            equity=float(facts.get("equity", 100000.0)),
            risk_per_trade_pct=float(facts.get("risk_per_trade_pct", 0.01)),
            tick_size=float(facts.get("tick_size", 0.05)),
        )


bridge = QuantBridge()
