"""AMT analysis orchestration compatibility layer.

This module keeps the legacy ``AMTPipeline`` API used by v1 while delegating
execution to the v2 ``AMTAnalyzer`` and existing domain stages.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from app.domain.amt.service.amt_analyzer import AMTAnalyzer
from app.domain.fabio_ai.services.amt_parameters import AMTAnalysisInput, AMTAnalysisResult
from app.domain.trading.model.value_objects import AMTResult, OHLC


@dataclass
class _ProfileStageResult:
    profile: list = field(default_factory=list)
    profile_type: str = "Session"
    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0


@dataclass
class _MarketStateStageResult:
    state: str = "BALANCED"
    market_state: str = "BALANCED"
    has_displacement: bool = False
    has_acceptance: bool = False
    balance_ratio: float = 0.0
    ib_high: float = 0.0
    ib_low: float = 0.0
    ib_complete: bool = False


@dataclass
class _SessionStageResult:
    session_open: float = 0.0
    day_type: str = "UNKNOWN"
    favor_strategy: str = "NEUTRAL"
    gap_type: str = ""
    opening_bias: str = ""


class AMTPipeline:
    """Backwards-compatible entrypoint for AMT analysis stage composition."""

    def __init__(self, config: Any | None = None) -> None:
        self.config = config
        self._analyzer = AMTAnalyzer()

    def analyze(
        self,
        data: AMTAnalysisInput | list[OHLC],
        **kwargs: Any,
    ) -> AMTResult | AMTAnalysisResult:
        start = perf_counter()
        if isinstance(data, AMTAnalysisInput):
            input_obj = data
            bars = list(_bars_from_input(input_obj.data))
            prior_profile = {
                "poc": float(input_obj.prior_poc),
                "vah": float(input_obj.prior_vah),
                "val": float(input_obj.prior_val),
            }
            symbol = input_obj.symbol
            daily_data = _bars_from_input(input_obj.daily_data)
            hourly_data = _bars_from_input(input_obj.hourly_data)
        else:
            bars = list(_bars_from_input(data))
            prior_profile = kwargs.get("prior_profile")
            if prior_profile is None:
                prior_profile = {
                    "poc": float(kwargs.get("prior_poc", 0.0)),
                    "vah": float(kwargs.get("prior_vah", 0.0)),
                    "val": float(kwargs.get("prior_val", 0.0)),
                }
            symbol = kwargs.get("symbol", "")
            daily_data = _bars_from_input(kwargs.get("daily_data"))
            hourly_data = _bars_from_input(kwargs.get("hourly_data"))

        result = self._analyzer.analyze(
            bars=bars,
            symbol=symbol,
            daily_bars=daily_data,
            hourly_bars=hourly_data,
            prior_profile=prior_profile,
        )

        # Lightweight compatibility telemetry can be logged by callers if needed.
        _ = perf_counter() - start
        return result

    def build_profile_stage(self, input_data: AMTAnalysisInput) -> _ProfileStageResult:
        analyzer_result = self.analyze(input_data)
        return _ProfileStageResult(
            profile=list(getattr(analyzer_result, "profile", ())),
            profile_type=getattr(analyzer_result, "profile_type", "Session"),
            poc=float(getattr(analyzer_result, "poc", 0.0)),
            vah=float(getattr(analyzer_result, "value_area_high", 0.0)),
            val=float(getattr(analyzer_result, "value_area_low", 0.0)),
        )

    def compute_market_state_stage(
        self,
        input_data: AMTAnalysisInput,
        _profile: _ProfileStageResult | None = None,
    ) -> _MarketStateStageResult:
        analyzer_result = self.analyze(input_data)
        return _MarketStateStageResult(
            state=str(getattr(analyzer_result, "market_state", "BALANCED")),
            market_state=str(getattr(analyzer_result, "market_state", "BALANCED")),
            has_displacement=bool(getattr(analyzer_result, "has_displacement", False)),
            has_acceptance=bool(getattr(analyzer_result, "has_acceptance", False)),
            balance_ratio=float(getattr(analyzer_result, "balance_ratio", 0.0)),
            ib_high=float(getattr(analyzer_result, "ib_high", 0.0)),
            ib_low=float(getattr(analyzer_result, "ib_low", 0.0)),
            ib_complete=bool(getattr(analyzer_result, "ib_complete", False)),
        )

    def analyze_session_context(self, input_data: AMTAnalysisInput) -> _SessionStageResult:
        analyzer_result = self.analyze(input_data)
        gap_type = str(getattr(analyzer_result, "gap_type", ""))
        opening_bias = str(getattr(analyzer_result, "opening_bias", ""))
        if opening_bias:
            favor = "TREND_CONTINUATION" if "LONG" in opening_bias.upper() else "MEAN_REVERSION"
        else:
            favor = "NEUTRAL"
        return _SessionStageResult(
            session_open=float(_session_open_from_input(input_data)),
            day_type=str(getattr(analyzer_result, "day_type", "UNKNOWN")),
            favor_strategy=favor,
            gap_type=gap_type,
            opening_bias=opening_bias,
        )


def _bars_from_input(data: Any) -> list[dict]:
    if not data:
        return []
    if isinstance(data, list):
        out: list[dict] = []
        for item in data:
            if isinstance(item, dict):
                out.append(item)
            else:
                out.append(
                    {
                        "time": getattr(item, "time", ""),
                        "open": float(item.open),
                        "high": float(item.high),
                        "low": float(item.low),
                        "close": float(item.close),
                        "volume": float(item.volume),
                        "buyVolume": float(item.taker_buy_volume),
                        "sellVolume": float(item.volume) - float(item.taker_buy_volume),
                        "vwap": float(getattr(item, "vwap", 0.0)),
                        "delta": float(getattr(item, "delta", 0.0)),
                    }
                )
        return out
    if hasattr(data, "dict"):
        return [data.dict()]  # type: ignore[attr-defined]
    return []


def _session_open_from_input(input_data: AMTAnalysisInput) -> float:
    data = input_data.data
    if not data:
        return 0.0
    first = data[0]
    if isinstance(first, dict):
        return float(first.get("open", 0.0))
    return float(getattr(first, "open", 0.0))
