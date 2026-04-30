"""AMT Analyzer — thin wrapper around AMTPipeline.

Refactored from 1521 lines to ~250 lines by delegating to AMTPipeline.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

from app.domain.fabio_ai.services.amt_pipeline import AMTPipeline
from app.domain.fabio_ai.services.amt_parameters import AMTAnalysisInput

from app.domain.trading.models.enums import MarketState, SignalType, Source, SetupType
from app.domain.trading.models.value_objects import (
    OHLC,
    OrderBook,
    VolumeProfileLevel,
    AggressivePrint,
    AMTResult,
)
from app.domain.fabio_ai.models.observation import AMTObservation

from app.domain.constants import (
    LVN_MIN_PERSISTENCE_BARS,
    LVN_REMOVAL_THRESHOLD,
    IB_MINUTES,
    LVN_THRESHOLD,
    HVN_THRESHOLD,
    LVN_PERCENTILE,
    LVN_MIN_SEPARATION,
    HVN_PERCENTILE,
    HVN_MIN_SEPARATION,
)
from app.domain.services.aggressive_prints import (
    AggressivePrintConfig,
    AggressivePrintRegistry,
    compute_aggression_sigma,
    find_aggressive_prints,
)
from app.domain.services.acceptance_rejection import (
    AcceptanceRejectionEngine,
    ARResult,
)
from app.domain.trading.models.value_objects import AggressivePrint
from app.domain.services.volume_profile import create_profile
from app.domain.fabio_ai.services.profile_classifier import (
    classify_shape,
)
from app.domain.fabio_ai.services.session_context import (
    classify_gap,
    get_session_info,
    opening_inventory_bias,
)
from app.domain.fabio_ai.strategy.fabio_detectors import (
    compute_per_symbol_delta,
    compute_tick_size,
    compute_value_area_bounds,
)
from app.domain.ports.config_port import ISymbolConfig

# Backward compatibility alias
SymbolConfigLike = ISymbolConfig


class AMTConfig:
    LVN_THRESHOLD: float = LVN_THRESHOLD
    LVN_SMOOTHING: int = 3
    OBI_THRESHOLD: float = 0.25
    DELTA_THRESHOLD: float = 0.3
    ABSORPTION_THRESHOLD: float = 0.3
    STOP_BUFFER: float = 0.001
    BUBBLE_VOL_MULTIPLIER: float = 1.5
    AGGRESSION_EMA_PERIOD: int = 20
    DELTA_DIRECTIONALITY_THRESHOLD: float = 0.40
    HVN_THRESHOLD: float = HVN_THRESHOLD
    AGGRESSION_SIGMA_THRESHOLD: float = 2.5
    AGGRESSION_EXPIRY_CANDLES: int = 30
    DISPLACEMENT_MULTIPLIER: float = 1.5
    BALANCE_RATIO_THRESHOLD: float = 0.70

    @classmethod
    def from_exchange_config(cls, exchange_config) -> AMTConfig:
        instance = cls()
        try:
            instance.AGGRESSION_SIGMA_THRESHOLD = float(
                exchange_config.aggression_sigma
            )
            instance.DISPLACEMENT_MULTIPLIER = float(
                exchange_config.displacement_multiplier
            )
            instance.BALANCE_RATIO_THRESHOLD = float(
                exchange_config.balance_ratio_threshold
            )
        except (TypeError, ValueError):
            pass
        return instance


from app.domain.services.volume_profile import IncrementalVolumeProfile
from app.domain.services.lvn_detector import (
    find_lvns as _find_lvns_extracted,
    find_hvns as _find_hvns_extracted,
    LVNPersistenceTracker,
)


def find_lvns(profile: list[VolumeProfileLevel], cfg: AMTConfig | None = None) -> list[float]:
    cfg = cfg or AMTConfig()
    levels = _find_lvns_extracted(
        profile,
        lvn_threshold=cfg.LVN_THRESHOLD,
        smoothing_window=cfg.LVN_SMOOTHING,
        lvn_percentile=LVN_PERCENTILE,
        min_separation=LVN_MIN_SEPARATION,
    )
    return [lvn.price for lvn in levels]


def find_hvns(profile: list[VolumeProfileLevel], cfg: AMTConfig | None = None) -> list[float]:
    cfg = cfg or AMTConfig()
    levels = _find_hvns_extracted(
        profile,
        hvn_threshold=cfg.HVN_THRESHOLD,
        smoothing_window=cfg.LVN_SMOOTHING,
        hvn_percentile=HVN_PERCENTILE,
        min_separation=HVN_MIN_SEPARATION,
    )
    return [hvn.price for hvn in levels]


class AMTAnalyzer:
    """AMT analysis service - thin wrapper around AMTPipeline."""

    USE_PIPELINE = True

    def __init__(
        self,
        config: AMTConfig | None = None,
        symbol_config: "SymbolConfigLike | None" = None,
        use_pipeline: bool = True,
    ) -> None:
        self.config = config or AMTConfig()
        self._pipeline: AMTPipeline | None = None
        # Backward compatibility - initialize legacy state trackers
        self._bubble_registry = AggressivePrintRegistry()
        self._vwap_cum_vol = 0.0
        self._vwap_cum_quote_vol = 0.0

    def _get_pipeline(self) -> AMTPipeline:
        if self._pipeline is None:
            self._pipeline = AMTPipeline(config=self.config)
        return self._pipeline

    def analyze(
        self,
        data: list[OHLC],
        order_book: OrderBook | None = None,
        incremental_profile: IncrementalVolumeProfile | None = None,
        prior_poc: float = 0.0,
        prior_vah: float = 0.0,
        prior_val: float = 0.0,
        developing_profile: IncrementalVolumeProfile | None = None,
        cushion_tier: str = "Conservative",
        session_pnl: float = 0.0,
        npoc_tracker: "NPOCTracker | None" = None,
        underlying: str = "NIFTY",
        daily_data: list[OHLC] | None = None,
        hourly_data: list[OHLC] | None = None,
        option_tick: OHLC | None = None,
        cvd_source: str = "",
        symbol: str = "",
        prior_avg_volume: float = 0.0,
    ) -> AMTResult:
        """Run the full AMT analysis pipeline via AMTPipeline."""
        input_data = AMTAnalysisInput(
            data=data,
            order_book=order_book,
            incremental_profile=incremental_profile,
            prior_poc=prior_poc,
            prior_vah=prior_vah,
            prior_val=prior_val,
            developing_profile=developing_profile,
            cushion_tier=cushion_tier,
            session_pnl=session_pnl,
            npoc_tracker=npoc_tracker,
            underlying=underlying,
            daily_data=daily_data,
            hourly_data=hourly_data,
            option_tick=option_tick,
            cvd_source=cvd_source,
            symbol=symbol,
            prior_avg_volume=prior_avg_volume,
        )
        result = self._get_pipeline().analyze(input_data)
        
        # Check for bubble retests - check if any registered aggressive prints are near current price
        bubble_retests = list(result.bubble_retests)
        if data and self._bubble_registry.prints:
            current_price = float(data[-1].close)
            for ap in self._bubble_registry.prints:
                if abs(ap.price - current_price) / max(current_price, 1e-9) < 0.01:
                    # Within 1% - add to retests if not already present
                    if ap not in bubble_retests:
                        bubble_retests.append(ap)
        
        # Compute opening bias and gap type if prior data provided
        opening_bias = ""
        gap_type = ""
        if data:
            if prior_vah > 0 and prior_val > 0:
                opening_bias = opening_inventory_bias(
                    float(data[0].open), prior_vah, prior_val
                )
            if prior_poc > 0:
                prior_range = prior_vah - prior_val if prior_vah > prior_val else 10.0
                gap_type = classify_gap(
                    float(data[0].open), prior_poc, prior_range
                )
        
        # Return updated result with mutable fields
        return result.__replace__(
            bubble_retests=bubble_retests,
            opening_bias=opening_bias,
            gap_type=gap_type,
        )

    def compute_observation(
        self,
        data: list[OHLC],
        order_book: OrderBook | None = None,
        prior_vah: float = 0.0,
        prior_val: float = 0.0,
    ) -> AMTObservation:
        """Build a full RL observation vector from current market state."""
        result = self.analyze(data, order_book)
        current = (
            data[-1]
            if data
            else OHLC(time="", open=0, high=0, low=0, close=0, volume=0)
        )

        pipeline = self._get_pipeline()
        cvd_state = pipeline._cvd_tracker.state()
        shape = classify_shape(list(result.profile))
        poc_mig = pipeline._poc_tracker.update(result.poc, current.close)

        open_price = data[0].open if data else 0.0
        use_prior_vah = prior_vah if prior_vah > 0 else result.value_area_high
        use_prior_val = prior_val if prior_val > 0 else result.value_area_low
        session_info = get_session_info(
            timestamp=current.time,
            open_price=open_price,
            prior_vah=use_prior_vah,
            prior_val=use_prior_val,
        )

        va_range = max(result.value_area_high - result.value_area_low, 1e-9)
        dist_to_poc = (current.close - result.poc) / va_range

        nearest_lvn = 0.0
        if result.lvns:
            nearest_lvn = min(result.lvns, key=lambda lvn: abs(current.close - lvn))

        agg_sigma = (
            compute_aggression_sigma(current, data[-50:]) if len(data) >= 20 else 0.0
        )

        obi = 0.0
        if order_book:
            bids_q = sum(b.quantity for b in order_book.bids)
            asks_q = sum(a.quantity for a in order_book.asks)
            total = bids_q + asks_q
            if total > 0:
                obi = (bids_q - asks_q) / total

        norm_delta = current.delta / current.volume if current.volume > 0 else 0.0

        return AMTObservation(
            dist_to_poc=dist_to_poc,
            is_in_balance=(result.market_state == MarketState.BALANCED.value),
            delta_divergence=cvd_state.z_score,
            nearest_lvn=nearest_lvn,
            cvd_slope=cvd_state.slope,
            profile_shape=shape.shape,
            poc_migration=poc_mig.direction,
            session=session_info.session,
            opening_relation=session_info.opening_relation,
            aggression_sigma=agg_sigma,
            obi=obi,
            norm_delta=norm_delta,
        )