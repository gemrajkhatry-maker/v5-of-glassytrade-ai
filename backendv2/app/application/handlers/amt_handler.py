"""AMT analysis handler for backendv2."""

from __future__ import annotations

import logging
from datetime import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.domain.amt.service.amt_analyzer import AMTAnalyzer
from app.domain.amt.service.footprint_analyzer import FootprintAnalyzer
from app.infrastructure.serialization.schemas import amt_result_to_dto, footprint_to_dto
from app.shared.timezones import IST

if TYPE_CHECKING:
    from app.domain.trading.model.value_objects import AMTResult, OHLC, OrderBook

logger = logging.getLogger(__name__)


@dataclass
class FloatOHLC:
    """Float-friendly candle snapshot to keep AMT analyzers deterministic."""

    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float
    taker_buy_volume: float
    delta: float


def _filter_today_session(data: list[FloatOHLC]) -> list[FloatOHLC]:
    """Prefer today's data for session-scoped profile; fallback to recent history."""
    if not data:
        return data

    today = datetime.now(IST).strftime("%Y-%m-%d")
    today_data = [c for c in data if str(c.time)[:10] == today]

    if len(today_data) > 20:
        return today_data

    logger.info("Only %d today candles — using last 100 candles for VP", len(today_data))
    return data[-100:] if len(data) > 100 else data


class AMTHandler:
    """Run AMT analysis and footprint generation each tick."""

    _LOOKBACK: int = 1000
    _DEV_LOOKBACK: int = 20

    def __init__(self, session_only_vp: bool = True) -> None:
        self._amt_analyzer = AMTAnalyzer()
        self._footprint_analyzer = FootprintAnalyzer()
        self._session_only_vp = session_only_vp
        self._prev_data_len: int = 0
        self._trading_date: str = datetime.now(IST).strftime("%Y-%m-%d")
        self._cached_profile: dict | None = None
        self._cached_leg_profile: dict | None = None

    @staticmethod
    def _to_float_ohlc(data: list["OHLC"]) -> list[FloatOHLC]:
        return [
            FloatOHLC(
                time=str(c.time),
                open=float(c.open),
                high=float(c.high),
                low=float(c.low),
                close=float(c.close),
                volume=float(c.volume),
                vwap=float(c.vwap),
                taker_buy_volume=float(c.taker_buy_volume),
                delta=float(c.delta),
            )
            for c in data
        ]

    @staticmethod
    def _to_bars(data: list[FloatOHLC]) -> list[dict]:
        bars: list[dict] = []
        for c in data:
            buy_vol = float(c.taker_buy_volume or 0.0)
            total_vol = float(c.volume or 0.0)
            bars.append(
                {
                    "time": c.time,
                    "open": float(c.open),
                    "high": float(c.high),
                    "low": float(c.low),
                    "close": float(c.close),
                    "volume": total_vol,
                    "buyVolume": buy_vol,
                    "sellVolume": max(total_vol - buy_vol, 0.0),
                    "vwap": float(c.vwap),
                    "takerBuyVolume": buy_vol,
                    "delta": float(c.delta),
                }
            )
        return bars

    def analyze(
        self,
        data: list["OHLC"],
        order_book: "OrderBook | None" = None,
        prior_poc: float = 0.0,
        prior_vah: float = 0.0,
        prior_val: float = 0.0,
        cushion_tier: str = "Conservative",
        session_pnl: float = 0.0,
        option_tick: "OHLC | None" = None,
        cvd_source: str = "",
        prior_avg_volume: float = 0.0,
    ) -> tuple["AMTResult", dict, dict]:
        """Run AMT analysis and return DTOs for API/runtime consumption."""
        float_data = self._to_float_ohlc(data)
        now = datetime.now(IST).strftime("%Y-%m-%d")

        if now != self._trading_date:
            logger.info(
                "Trading day changed %s -> %s, rebuilding AMT state",
                self._trading_date,
                now,
            )
            self._prev_data_len = 0
            self._trading_date = now
            self._cached_profile = None
            self._cached_leg_profile = None

        vp_data = _filter_today_session(float_data) if self._session_only_vp else float_data
        data_len = len(vp_data)
        if data_len != 0:
            data_grew_by = data_len - self._prev_data_len
        else:
            data_grew_by = 0

        is_new_candle = data_grew_by != 0
        if self._prev_data_len == 0 and data_len:
            data_grew_by = 1
            is_new_candle = True

        recent_data = vp_data[-min(len(vp_data), self._LOOKBACK) :] if vp_data else []
        bars = self._to_bars(recent_data)

        prior_profile = {
            "poc": float(prior_poc or 0.0),
            "vah": float(prior_vah or 0.0),
            "val": float(prior_val or 0.0),
        }

        amt_result = self._amt_analyzer.analyze(
            bars=bars,
            symbol=str(getattr(option_tick, "time", "")),
            prior_profile=prior_profile,
        )

        # Enforce optional analytics inputs that are explicit in the legacy contract.
        if getattr(amt_result, "cushion_tier", None) is not None:
            amt_result = amt_result.__replace__(cushion_tier=cushion_tier)
        else:
            # AMTResult has immutable dataclass semantics; still support direct field set for compatibility.
            try:
                amt_result = amt_result.__replace__(cushion_tier=cushion_tier)
            except Exception:
                pass
        amt_result = amt_result.__replace__(session_pnl=session_pnl, cvd_source=cvd_source)

        amt_dto = amt_result_to_dto(amt_result)
        if is_new_candle:
            self._cached_profile = amt_dto.get("profile")
            self._cached_leg_profile = amt_dto.get("legProfile")
        elif self._cached_profile is not None:
            amt_dto["profile"] = self._cached_profile
            amt_dto["legProfile"] = self._cached_leg_profile

        fp_data = vp_data[-50:] if len(vp_data) >= 50 else vp_data
        fp_candles = self._footprint_analyzer.generate(self._to_bars(fp_data))
        fp_dto = {k: footprint_to_dto(v) for k, v in fp_candles.items()}
        self._prev_data_len = data_len
        return amt_result, amt_dto, fp_dto
