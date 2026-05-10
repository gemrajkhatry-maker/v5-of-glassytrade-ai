"""Context builder for LLM prompts.

Extracted from LLMEntryHandler. Constructs the market data JSON sent to the LLM.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Callable

from app.domain.fabio_ai.model.llm_decision import LLMDecision
from app.domain.shared.port import IStorage
from app.domain.trading.model.value_objects import AMTResult, OHLC
from app.runtime.pipeline.events import Signal
from app.shared.timezones import IST

logger = logging.getLogger(__name__)

_MCX_COMMODITIES = (
    "GOLD",
    "GOLDM",
    "SILVER",
    "SILVERM",
    "CRUDEOIL",
    "CRUDEOILM",
    "NATURALGAS",
    "COPPER",
    "ZINC",
    "ALUMINIUM",
    "LEAD",
    "NICKEL",
)


def _is_mcx_symbol(symbol: str) -> bool:
    if not symbol:
        return False
    first_token = symbol.split(" ")[0].upper()
    return first_token in _MCX_COMMODITIES


def _to_ist_datetime(timestamp: float | int | str | datetime | None) -> datetime:
    if isinstance(timestamp, datetime):
        dt = timestamp
    elif timestamp is None:
        dt = datetime.now(tz=IST)
    else:
        if isinstance(timestamp, str):
            ts = float(timestamp)
        else:
            ts = float(timestamp)
        if ts > 1_000_000_000_000:
            dt = datetime.fromtimestamp(ts / 1_000_000_000, tz=IST)
        else:
            dt = datetime.fromtimestamp(ts, tz=IST)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


class LLMContextBuilder:
    """Builds the JSON context for LLM inference."""

    def __init__(self, storage: IStorage | None = None, exchange: str = "MCX") -> None:
        self._storage = storage
        self._exchange = exchange

    def build(
        self,
        signal: Signal,
        amt_result: AMTResult,
        candles: list[OHLC],
        session_phase,  # SessionPhaseInfo-like
    ) -> str:
        """Construct JSON prompt context."""
        last_candle = candles[-1] if candles else None
        market_data_ai = self._build_market_data_ai(
            signal=signal,
            amt_result=amt_result,
            tick=last_candle,
            session_phase=session_phase,
            candles=candles,
        )
        return json.dumps(market_data_ai, default=str)

    def _build_episodic_memory(self) -> str:
        if self._storage is None:
            return ""
        try:
            trades = self._storage.get_recent_trades(5)
            if not isinstance(trades, list):
                return ""
            parts: list[str] = []
            for i, trade in enumerate(trades, start=1):
                if not isinstance(trade, dict):
                    continue
                side = str(trade.get("side", ""))
                pnl = float(trade.get("pnl", 0.0))
                reason = str(trade.get("reason", ""))
                sign = "+" if pnl >= 0 else ""
                parts.append(f"{i}) {side} {sign}Rs{pnl:.0f} ({reason})")
            return "; ".join(parts)
        except Exception:
            logger.debug("Failed to load episodic memory for LLM context", exc_info=True)
            return ""

    def _build_market_data_ai(
        self,
        signal: Signal,
        amt_result: AMTResult,
        tick,
        session_phase,
        candles: list[OHLC] | None = None,
    ) -> dict[str, object]:
        now = _to_ist_datetime(signal.timestamp)
        market_open = now.replace(
            hour=9,
            minute=(0 if session_phase.session_market == "MCX" else 15),
            second=0,
            microsecond=0,
        )
        if session_phase.session_market == "MCX":
            market_open = market_open.replace(minute=0)
            if now < market_open:
                market_open = market_open.replace(day=market_open.day - 1)

        session_elapsed_min = max(0.0, (now - market_open).total_seconds() / 60.0)
        market_data_ai: dict[str, object] = {
            "symbol": signal.symbol,
            "timestamp": signal.timestamp,
            "session": session_phase.session_name,
            "phase": session_phase.phase_int,
            "ltp": float(getattr(tick, "close", signal.entry)),
            "delta": float(getattr(tick, "delta", 0.0)),
            "volume": float(getattr(tick, "volume", 0.0)),
            "vah": float(getattr(amt_result, "value_area_high", 0.0)),
            "val": float(getattr(amt_result, "value_area_low", 0.0)),
            "poc": float(getattr(amt_result, "poc", 0.0)),
            "market_state": str(getattr(amt_result, "market_state", "")),
            "aggression": float(getattr(amt_result, "aggression", 0.0)),
            "cvd_slope": float(getattr(amt_result, "cvd_slope", 0.0)),
            "strategy_hint": self._build_strategy_hint(
                amt_result=amt_result,
                session_info=session_phase,
                symbol=signal.symbol,
            ),
            "session_elapsed_minutes": round(float(session_elapsed_min), 2),
            "session_market": session_phase.session_market,
            "session_phase": session_phase.phase_int,
            "signal": {
                "type": signal.type,
                "entry": signal.entry,
                "sl": signal.sl,
                "tp": signal.tp,
                "rr": signal.rr,
                "confidence": signal.confidence,
                "reason": signal.reason,
                "source": getattr(signal, "source", ""),
            },
            "amt": {
                "market_state": str(getattr(amt_result, "market_state", "")),
                "value_area_high": float(getattr(amt_result, "value_area_high", 0.0)),
                "value_area_low": float(getattr(amt_result, "value_area_low", 0.0)),
                "poc": float(getattr(amt_result, "poc", 0.0)),
                "aggression": float(getattr(amt_result, "aggression", 0.0)),
                "cvd_slope": float(getattr(amt_result, "cvd_slope", 0.0)),
                "session_vwap": float(getattr(amt_result, "session_vwap", 0.0)),
                "vwap_upper_2": float(getattr(amt_result, "vwap_upper_2", 0.0)),
                "shape": str(getattr(amt_result, "profile_shape", "")),
                "profile_type": str(getattr(amt_result, "profile_type", "Session")),
                "market_structure": str(getattr(amt_result, "market_structure", "")),
                "opening_bias": str(getattr(amt_result, "opening_bias", "")),
                "gap_type": str(getattr(amt_result, "gap_type", "")),
                "option_type": self._detect_option_type(signal.symbol or ""),
            },
            "profile_description": self._build_profile_description(amt_result),
            "volume_bubble_summary": self._build_volume_bubble_summary(amt_result, tick),
            "imbalance_summary": self._build_imbalance_summary(type("S", (), {"_last_fp_domain": None})()),
            "gate_context": self._build_gate_context(
                amt_result=amt_result,
                tick=tick,
                session=None,
                session_info=session_phase,
                agg_levels=[],
                fp_domain=None,
            ),
            "session_elapsed_min": round(float(session_elapsed_min), 2),
            "session_market": session_phase.session_market,
            "session_state": "BASIC",
            "session_info": str(session_phase),
            "amt_time_window": self._get_amt_time_window(now),
            "episodic_memory": self._build_episodic_memory(),
            "candles": [
                {
                    "time": str(getattr(candle, "time", "")),
                    "open": float(getattr(candle, "open", 0.0)),
                    "high": float(getattr(candle, "high", 0.0)),
                    "low": float(getattr(candle, "low", 0.0)),
                    "close": float(getattr(candle, "close", 0.0)),
                    "volume": float(getattr(candle, "volume", 0.0)),
                    "delta": float(getattr(candle, "delta", 0.0)),
                }
                for candle in (candles or [])
            ],
        }
        self._enrich_market_context(market_data_ai, amt_result)
        return market_data_ai

    @staticmethod
    def _derive_strategy_hint(
        signal: Signal,
        session_phase,
        amt_result: AMTResult,
    ) -> str:
        hint = ""
        if session_phase.session_market == "NSE":
            if session_phase.allow_trend:
                hint = "Trend continuation mode is preferred."
            else:
                hint = "Mean-reversion mode only."
        else:
            if session_phase.allow_trend:
                hint = "MCX trend continuation mode is active."
            else:
                hint = "MCX mean-reversion mode only."

        if str(getattr(amt_result, "profile_shape", "")).upper() == "P":
            hint += " P-shape profile detected."
        elif str(getattr(amt_result, "profile_shape", "")).upper() == "B":
            hint += " B-shape profile detected."
        elif str(getattr(amt_result, "profile_shape", "")).upper() in {"", "D"}:
            hint += " Balanced profile."

        if signal.type == "LONG":
            hint += " Existing signal is LONG."
        elif signal.type == "SHORT":
            hint += " Existing signal is SHORT."
        else:
            hint += " Existing signal is NO_TRADE."

        return hint.strip()

    def _build_strategy_hint(self, amt_result, session_info, symbol: str | None = None, session=None) -> str:
        del session
        return self._derive_strategy_hint(
            signal=type("SignalLike", (), {"type": "NO_TRADE"})(),
            session_phase=session_info,
            amt_result=amt_result,
        ) + (f" Symbol={symbol}" if symbol else "")

    def _build_profile_description(self, amt_result) -> str:
        shape = str(getattr(amt_result, "profile_shape", "")).upper()
        return {
            "D": "D-shape (balanced, rotational)",
            "P": "P-shape (top-heavy, sellers may be trapped)",
            "B": "B-shape (bimodal / breakout-prone)",
            "b": "b-shape (bottom-heavy, buyer absorption)",
        }.get(shape, "")

    def _build_volume_bubble_summary(self, amt_result, tick) -> str:
        del tick
        bubbles = getattr(amt_result, "aggressive_prints", None)
        if not bubbles:
            return ""
        parts: list[str] = []
        try:
            for bubble in bubbles[-3:]:
                side = str(getattr(bubble, "side", "") or bubble.get("side", ""))
                price = float(getattr(bubble, "price", bubble.get("price", 0.0)))
                vol = float(getattr(bubble, "volume", bubble.get("volume", 0.0)))
                delta = float(getattr(bubble, "delta", bubble.get("delta", 0.0)))
                parts.append(f"{side} at {price:.0f} (vol {vol:.0f}, delta {delta:+.0f})")
        except Exception:
            logger.debug("Unable to build bubble summary", exc_info=True)
        return "; ".join(parts)

    def _build_imbalance_summary(self, session) -> str:
        return ""

    def _get_amt_time_window(self, ist_now):
        hour = int(getattr(ist_now, "hour", 0))
        minute = int(getattr(ist_now, "minute", 0))
        return {
            "hour": hour,
            "minute": minute,
            "window": f"{hour:02d}:{minute:02d}",
            "elapsed_minutes": (hour * 60 + minute),
        }

    def _build_gate_context(self, amt_result, tick, session, session_info, agg_levels, fp_domain) -> str:
        del session, agg_levels, fp_domain
        market_state = str(getattr(amt_result, "market_state", "UNKNOWN"))
        return (
            f"[GATE CHECK] market={market_state}, session={session_info.session_name}, "
            f"tick={getattr(tick, 'close', 'n/a')}, reason=basic checks pending"
            if session_info and not session_info.allow_entry
            else ""
        )

    @staticmethod
    def _detect_option_type(symbol: str) -> str:
        if not symbol:
            return "UNKNOWN"
        upper = symbol.upper()
        if "CALL" in upper or upper.endswith("CE"):
            return "CALL"
        if "PUT" in upper or upper.endswith("PE"):
            return "PUT"
        return "UNKNOWN"

    @staticmethod
    def _enrich_market_context(market_data_ai: dict[str, object], amt_result) -> None:
        if float(getattr(amt_result, "aggression", 0.0)) < 1.0:
            market_data_ai["aggression_warning"] = "Weak aggression"
        if str(getattr(amt_result, "market_state", "")).upper() == "IMBALANCED":
            market_data_ai["drive_warning"] = "Imbalanced session"
        if abs(float(getattr(amt_result, "cvd_slope", 0.0))) > 50:
            market_data_ai["cvd_warning"] = "Extreme CVD slope"
