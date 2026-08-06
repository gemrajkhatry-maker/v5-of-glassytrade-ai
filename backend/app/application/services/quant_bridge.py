"""Bridge between the greenfield `quant/` engine and the live backend.

Owns one `AuctionCoordinator` per symbol, feeds it closed bars (mapped from
the backend's OHLC candles), and serializes the resulting `AuctionState`
into the WS snapshot as the ``auction`` field. Purely additive — the legacy
AMT path is untouched; this is the *decision engine of record* in parallel.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


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
        if getattr(self._last_bar_time, "get", None) is not None:
            last_t = self._last_bar_time.get(symbol)
            if last_t == ohlc.time:
                return {}
        self._last_bar_time[symbol] = ohlc.time
        coord = self._coordinator(symbol)
        state = coord.on_bar_close(ohlc_to_quant_bar(ohlc))
        return auction_state_to_dto(state)


bridge = QuantBridge()
