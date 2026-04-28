"""AMT Analyzer — Auction Market Theory analysis domain service.

Pure domain logic: volume profile construction, LVN/HVN detection,
market state assessment, and aggression scoring.  Signal generation is
delegated to the SignalGenerator service to honour SRP.

Enhanced with Valentini AMT features: 2.5σ aggression filter,
CVD tracking, profile shape classification, and session context.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from app.domain.fabio_ai.services import mlx_compute as mc
from app.shared.symbol_utils import detect_option_type

from app.domain.trading.models.enums import MarketState, SignalType, Source, SetupType
from app.domain.trading.models.value_objects import (
    OHLC,
    OrderBook,
    VolumeProfileLevel,
    AggressivePrint,
    AMTResult,
)
from app.domain.fabio_ai.models.observation import AMTObservation
from app.domain.trading.models.entities import Signal
from app.domain.constants import (
    LVN_MIN_PERSISTENCE_BARS,
    LVN_REMOVAL_THRESHOLD,
    DELTA_PROFILE_BUCKETS,
    DISPLACEMENT_LOOKBACK,
    IB_MINUTES,
    VALUE_AREA_PCT,
    LVN_THRESHOLD,
    HVN_THRESHOLD,
    LVN_PERCENTILE,
    LVN_MIN_SEPARATION,
    HVN_PERCENTILE,
    HVN_MIN_SEPARATION,
)
from app.domain.fabio_ai.services.cvd_tracker import CVDTracker
from app.domain.fabio_ai.services.orderflow_detectors import (
    BigTradeDetector,
    BubbleDetector,
    OFICalculator,
    AbsorptionDetector,
)
from app.domain.fabio_ai.services.profile_classifier import (
    classify_shape,
    POCMigrationTracker,
)
from app.domain.fabio_ai.services.market_structure_classifier import (
    MarketStructureClassifier,
)
from app.domain.fabio_ai.services.session_context import (
    classify_gap,
    get_session_info,
    opening_inventory_bias,
)
from app.domain.fabio_ai.services.market_state_engine import (
    detect_market_state,
    log_state_transition,
)
from app.domain.fabio_ai.services.drive_tracker import DriveTracker
from app.domain.fabio_ai.services.aggression_scorer import (
    AggressionScorer,
    PersistentAggressionScorer,
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
from app.domain.services.initial_balance_engine import InitialBalanceEngine
from app.domain.services.break_detector import (
    detect_break,
    check_ib_break_tick,
)
from app.domain.services.lvn_play_detector import detect_lvn_play
from app.domain.services.volume_profile import create_profile
from app.domain.services.displacement_detector import (
    detect_displacement,
    detect_acceptance,
)
from app.domain.fabio_ai.services.opening_classifier import OpeningTypeClassifier
from app.domain.fabio_ai.services.mtf_analyzer import MultiTimeframeAMTAnalyzer

# NOTE: SymbolConfigLike is now defined canonically in app.domain.ports.config_port
# as SymbolIConfig. The local definition is kept for backward compatibility.
# New code should import from the ports module.
from app.domain.ports.config_port import ISymbolConfig

# Backward compatibility alias
SymbolConfigLike = ISymbolConfig


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class AMTConfig:
    # LVN/HVN thresholds from constants.py (Fabio spec-compliant)
    LVN_THRESHOLD: float = LVN_THRESHOLD  # < 15% of mean (Fabio spec)
    LVN_SMOOTHING: int = 3  # Smooth histogram before LVN/HVN detection
    OBI_THRESHOLD: float = 0.25
    DELTA_THRESHOLD: float = 0.3
    ABSORPTION_THRESHOLD: float = 0.3
    STOP_BUFFER: float = 0.001
    BUBBLE_VOL_MULTIPLIER: float = 1.5
    AGGRESSION_EMA_PERIOD: int = 20  # EMA period for dynamic volume threshold
    DELTA_DIRECTIONALITY_THRESHOLD: float = 0.40  # Professional: 40-50% delta ratio
    HVN_THRESHOLD: float = HVN_THRESHOLD  # > 200% of mean (Fabio spec)

    # FIX #9: Balance ratio threshold for Indian markets
    # Indian options have wider ranges due to gamma/theta
    # Adjusted from default 0.50 to 0.55 for more realistic balance detection

    # Configurable via env — tune for MCX with lower values
    # Default values from Fabio spec (overridable via env)
    AGGRESSION_SIGMA_THRESHOLD: float = 2.5
    AGGRESSION_EXPIRY_CANDLES: int = 30
    DISPLACEMENT_MULTIPLIER: float = 1.5
    BALANCE_RATIO_THRESHOLD: float = (
        0.70  # 70% of candles inside VA = BALANCED (Fabio's rule)
    )

    @classmethod
    def from_exchange_config(cls, exchange_config) -> AMTConfig:
        """Create config from an ExchangeConfig value object.

        DIP-compliant: no infrastructure imports.
        """
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
            pass  # Use defaults
        return instance


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
# Volume Profile — imported from app.domain.services.volume_profile
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Volume Profile + LVN/HVN Detection — imported from extracted services
# ---------------------------------------------------------------------------
from app.domain.services.volume_profile import IncrementalVolumeProfile
from app.domain.services.lvn_detector import (
    find_lvns as _find_lvns_extracted,
    find_hvns as _find_hvns_extracted,
    LVNPersistenceTracker,
)


def find_lvns(
    profile: list[VolumeProfileLevel],
    cfg: AMTConfig | None = None,
) -> list[float]:
    """Thin wrapper — extracts prices from LVNLevel objects."""
    cfg = cfg or AMTConfig()
    levels = _find_lvns_extracted(
        profile,
        lvn_threshold=cfg.LVN_THRESHOLD,
        smoothing_window=cfg.LVN_SMOOTHING,
        lvn_percentile=LVN_PERCENTILE,
        min_separation=LVN_MIN_SEPARATION,
    )
    return [lvn.price for lvn in levels]


def find_hvns(
    profile: list[VolumeProfileLevel],
    cfg: AMTConfig | None = None,
) -> list[float]:
    """Thin wrapper — extracts prices from HVNLevel objects."""
    cfg = cfg or AMTConfig()
    levels = _find_hvns_extracted(
        profile,
        hvn_threshold=cfg.HVN_THRESHOLD,
        smoothing_window=cfg.LVN_SMOOTHING,
        hvn_percentile=HVN_PERCENTILE,
        min_separation=HVN_MIN_SEPARATION,
    )
    return [hvn.price for hvn in levels]


# ---------------------------------------------------------------------------
# Initial Balance Tracker — imported from app.domain.services.initial_balance
# Acceptance / Rejection — imported from app.domain.services.acceptance_rejection
# Aggressive Prints — imported from app.domain.services.aggressive_prints
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Acceptance / Rejection — imported from app.domain.services.acceptance_rejection
# Aggressive Prints — imported from app.domain.services.aggressive_prints
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Break Detection — imported from app.domain.services.break_detector
# LVN Play Detection — imported from app.domain.services.lvn_play_detector
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# AMT Analyzer Service
# ---------------------------------------------------------------------------


class AMTAnalyzer:
    """Auction Market Theory analysis — pure domain service.

    Computes volume profile, value area, LVN/HVN nodes, aggression scoring,
    and generates trade signals based on market microstructure.

    Enhanced with Valentini AMT features: CVD tracking, profile shape
    classification, POC migration, session context, and 2.5σ aggression.
    """

    def __init__(
        self,
        config: AMTConfig | None = None,
        symbol_config: "SymbolConfigLike | None" = None,
    ) -> None:
        self.config = config or AMTConfig()
        self._cvd_tracker = CVDTracker()
        self._poc_tracker = POCMigrationTracker()
        self._structure_classifier: "MarketStructureClassifier | None" = None
        self._vwap_history: list[float] = []
        # Incremental aggressive prints state
        self._prev_agg_prints: list[AggressivePrint] = []
        self._prev_agg_data_len: int = 0
        self._bubble_registry = AggressivePrintRegistry()
        # Session VWAP accumulator
        self._vwap_cum_vol: float = 0.0
        self._vwap_cum_quote_vol: float = 0.0
        self._vwap_last_time: str = ""
        # VWAP variance accumulator for σ bands
        self._vwap_cum_sq_vol: float = 0.0  # Σ((TP - shift)² × volume)
        self._vwap_shift: float = 0.0  # Reference price for numerically stable variance
        # Price deviations for proper VWAP std calculation (Task 2.1)
        self._vwap_price_deviations: deque = deque(maxlen=500)
        # Initial Balance tracker
        self._ib_tracker = InitialBalanceEngine(ib_minutes=IB_MINUTES)
        # Sticky IB break state (survives price re-entry into IB)
        self._ib_break_direction: str = ""
        # Acceptance/Rejection engine
        self._ar_engine = AcceptanceRejectionEngine()
        # Previous CVD slope for delta-flip detection in LVN play
        self._prev_cvd_slope: float = 0.0
        # Previous market state for transition logging (FR-04-07)
        self._previous_state: MarketState | None = None
        # New modules (Phases 3-5)
        self._drive_tracker = DriveTracker()
        self._opening_classifier = OpeningTypeClassifier()
        # Initialize LVN tracker here to avoid AttributeError if configure() not called
        from app.domain.constants import LVN_MIN_PERSISTENCE_BARS, LVN_REMOVAL_THRESHOLD
        self._lvn_tracker = LVNPersistenceTracker(
            min_bars=LVN_MIN_PERSISTENCE_BARS,
            removal_threshold=LVN_REMOVAL_THRESHOLD,
        )
        # Initialize other trackers that configure() would create
        self._big_trade_detector = BigTradeDetector()
        self._bubble_detector = BubbleDetector()
        self._ofi_calculator = OFICalculator()
        self._absorption_detector = AbsorptionDetector()
        self._persistent_agg_scorer = PersistentAggressionScorer()

    def detect_displacement_leg(self, data: list[OHLC]) -> dict:
        """Detect displacement and return leg profile data.

        Always builds a leg profile from the most recent directional move
        (consecutive same-direction candles from the end). The strict displacement
        flag is set when the move also meets range expansion criteria.
        """
        empty = {
            "has_displacement": False,
            "profile": [],
            "lvns": [],
            "poc": 0.0,
            "vah": 0.0,
            "val": 0.0,
            "swing_delta": 0.0,
        }
        if len(data) < 5:
            return empty

        # Find the most recent directional leg: consecutive candles from end
        # that share the same direction (bull or bear)
        last = data[-1]
        is_bull = last.close >= last.open
        leg_candles = [last]
        opposite_tolerance = 1  # allow 1 reversal candle within leg
        opposite_count = 0
        for i in range(len(data) - 2, max(len(data) - DISPLACEMENT_LOOKBACK, -1), -1):
            c = data[i]
            if (c.close >= c.open) == is_bull:
                leg_candles.insert(0, c)
                opposite_count = 0
            else:
                opposite_count += 1
                if opposite_count > opposite_tolerance:
                    break
                leg_candles.insert(0, c)  # include the reversal candle

        if len(leg_candles) < 2:
            return empty

        is_disp = detect_displacement(data, self.config.DISPLACEMENT_MULTIPLIER)
        leg_profile = create_profile(leg_candles, buckets=DELTA_PROFILE_BUCKETS)
        if len(leg_profile) < 3:
            return {
                "has_displacement": is_disp,
                "profile": leg_profile,
                "lvns": [],
                "poc": 0.0,
                "vah": 0.0,
                "val": 0.0,
                "swing_delta": sum(c.delta for c in leg_candles),
            }
        leg_lvns = find_lvns(leg_profile, self.config)

        # POC — VWAP tie-break (matches session logic)
        max_vol = max(p.volume for p in leg_profile)
        poc_candidates = [i for i, p in enumerate(leg_profile) if p.volume == max_vol]

        # Local Leg VWAP for tie-break
        leg_vol = sum(c.volume for c in leg_candles)
        leg_vwap = (
            sum(c.close * c.volume for c in leg_candles) / leg_vol
            if leg_vol > 0
            else leg_candles[-1].close
        )

        poc_idx = min(
            poc_candidates, key=lambda i: abs(leg_profile[i].price - leg_vwap)
        )
        leg_poc = leg_profile[poc_idx].price

        # Value Area (70%) — CME two-row pairs method (matches session logic)
        total_volume = sum(p.volume for p in leg_profile)
        target_volume = total_volume * VALUE_AREA_PCT
        current_volume = max_vol
        up_idx, down_idx = poc_idx, poc_idx
        while current_volume < target_volume:
            up_pair = 0.0
            up_count = 0
            for k in range(1, 3):
                if up_idx + k < len(leg_profile):
                    up_pair += leg_profile[up_idx + k].volume
                    up_count += 1
            down_pair = 0.0
            down_count = 0
            for k in range(1, 3):
                if down_idx - k >= 0:
                    down_pair += leg_profile[down_idx - k].volume
                    down_count += 1
            if not up_count and not down_count:
                break
            if up_count and (not down_count or up_pair >= down_pair):
                for k in range(1, up_count + 1):
                    if up_idx + 1 < len(leg_profile):
                        up_idx += 1
                        current_volume += leg_profile[up_idx].volume
            elif down_count:
                for k in range(1, down_count + 1):
                    if down_idx - 1 >= 0:
                        down_idx -= 1
                        current_volume += leg_profile[down_idx].volume

        step = (
            leg_profile[1].price - leg_profile[0].price if len(leg_profile) > 1 else 0
        )
        half_step = step / 2
        leg_vah = leg_profile[up_idx].price + half_step
        leg_val = leg_profile[down_idx].price - half_step
        return {
            "has_displacement": is_disp,
            "profile": leg_profile,
            "lvns": leg_lvns,
            "poc": leg_poc,
            "vah": leg_vah,
            "val": leg_val,
            "swing_delta": sum(c.delta for c in leg_candles),
        }

    def _update_session_vwap(self, current, typical_price) -> float:
        """Update session VWAP with session boundary detection and accumulation.

        Returns the current session VWAP value.
        """
        quote_vol = typical_price * current.volume if current.volume > 0 else 0.0
        _reset_session = False
        if self._vwap_last_time:
            try:
                if current.time[:10] != self._vwap_last_time[:10]:
                    _reset_session = True
            except (TypeError, IndexError):
                pass
            if not _reset_session and current.time < self._vwap_last_time:
                _reset_session = True
        if _reset_session:
            self._vwap_cum_vol = 0.0
            self._vwap_cum_quote_vol = 0.0
            self._vwap_cum_sq_vol = 0.0
            self._vwap_shift = 0.0
            self._vwap_price_deviations = []  # Reset deviations on new session
            self._ib_tracker.reset()
            self._ib_break_direction = ""
            self._ar_engine.reset()
            self._persistent_agg_scorer.reset()
            self._lvn_tracker.reset()
        _is_new_candle = current.time != self._vwap_last_time
        self._vwap_last_time = current.time
        
        # Accumulate volume and quote volume (typical_price * volume)
        # MUST happen on every tick for accuracy, not just new candles
        self._vwap_cum_vol += float(current.volume)
        self._vwap_cum_quote_vol += float(quote_vol)
        
        # Shifted variance calculation for better numerical stability
        if self._vwap_shift == 0.0:
            self._vwap_shift = typical_price  # anchor to first tick
        
        shifted = typical_price - self._vwap_shift
        self._vwap_cum_sq_vol += float(shifted * shifted * current.volume)
        
        # Track price deviations for proper VWAP std calculation (Task 2.1)
        self._vwap_price_deviations.append(shifted)
        
        return float(
            self._vwap_cum_quote_vol / self._vwap_cum_vol
            if self._vwap_cum_vol > 0
            else current.close
        )

    def _compute_order_flow_metrics(
        self,
        recent_data,
        order_book,
        current,
        agg_prints,
        market_state,
        lvns,
        vah,
        val,
        poc,
        tick_size,
    ) -> dict:
        """Compute order flow detectors and aggression score. Extracted from analyze()."""
        result = {}

        # Average volume
        result["avg_candle_vol"] = (
            sum(float(d.volume) for d in recent_data) / len(recent_data)
            if recent_data
            else 0.0
        )

        # OBI from order book
        result["obi"] = 0.0
        result["toxicity"] = 0.0
        if order_book:
            bids_q = sum(b.quantity for b in order_book.bids)
            asks_q = sum(a.quantity for a in order_book.asks)
            total = bids_q + asks_q
            if total > 0:
                result["obi"] = (bids_q - asks_q) / total
            if len(order_book.bids) >= 3 and len(order_book.asks) >= 3:
                top_bids_q = sum(b.quantity for b in order_book.bids[:3])
                top_asks_q = sum(a.quantity for a in order_book.asks[:3])
                top_total = top_bids_q + top_asks_q
                if top_total > 0:
                    top_obi = (top_bids_q - top_asks_q) / top_total
                    if abs(top_obi) > 0.7:
                        result["toxicity"] = top_obi

        result["norm_delta"] = (
            current.delta / current.volume if current.volume > 0 else 0
        )

        # FR-06-01: Footprint imbalance
        has_agg_prints = len(agg_prints) >= 2
        has_strong_delta = abs(result["norm_delta"]) > 0.30
        result["footprint_confirmed"] = has_agg_prints and has_strong_delta

        # FR-06-02: CVD
        cvd_state = self._cvd_tracker.state()
        result["cvd_state"] = cvd_state
        result["cvd_confirmed"] = False
        if market_state == MarketState.IMBALANCED and cvd_state.slope > 0:
            result["cvd_confirmed"] = True
        elif market_state == MarketState.IMBALANCED and cvd_state.slope < 0:
            result["cvd_confirmed"] = True
        elif cvd_state.has_divergence:
            result["cvd_confirmed"] = True

        # FR-06-03: Big trade
        big_trade = self._big_trade_detector.detect(current, result["avg_candle_vol"])
        result["big_trade_confirmed"] = big_trade is not None

        # FR-06-04: Absorption
        atr = (
            max(d.high for d in recent_data[-14:])
            - min(d.low for d in recent_data[-14:])
        ) / max(len(recent_data[-14:]), 1)
        absorption = self._absorption_detector.detect(
            current, atr, result["avg_candle_vol"]
        )
        result["absorption_detected"] = absorption.detected
        result["absorption_side"] = absorption.side if absorption.detected else ""
        result["absorption_range_ratio"] = absorption.range_ratio
        result["absorption_vol_ratio"] = absorption.vol_ratio

        # FR-06-05: OFI
        ofi_result = self._ofi_calculator.update(current)
        result["ofi_result"] = ofi_result
        result["ofi_aligned"] = (ofi_result.ofi > 0.10) or (ofi_result.ofi < -0.10)

        # FR-06-06: Confluence
        result["confluence_bonus"] = False
        for lvn in lvns:
            for level in [vah, val, poc]:
                if level > 0 and abs(lvn - level) < tick_size * 3:
                    result["confluence_bonus"] = True
                    break

        # FR-06-07: Volume bubble
        bubble = self._bubble_detector.detect(current)
        result["volume_bubble_near"] = bubble.detected

        # Aggression scorer
        self._persistent_agg_scorer.set_persistence_for_state(market_state)
        agg_result = self._persistent_agg_scorer.score(
            footprint_confirmed=result["footprint_confirmed"],
            cvd_confirmed=result["cvd_confirmed"],
            big_trade_confirmed=result["big_trade_confirmed"],
            absorption_detected=result["absorption_detected"],
            ofi_aligned=result["ofi_aligned"],
            confluence_bonus=result["confluence_bonus"],
            volume_bubble_near=result["volume_bubble_near"],
        )
        result["agg_result"] = agg_result
        result["aggression_score"] = agg_result.score
        result["has_aggression"] = agg_result.confirmed

        return result

    @staticmethod
    def _detect_vah_probe(
        live_price: float,
        vah: float,
        ib_high: float,
        vwap_deviation_sigmas: float,
        delta_score: float,
    ) -> str | None:
        """Detect when price is probing above VAH near IB High — critical AMT state.

        Fabio AMT framework: when price is above VAH and testing IB High,
        this is a pivotal moment that requires special classification.
        """
        if live_price <= vah:
            return None  # Not above VAH

        is_near_ib = ib_high > 0 and abs(live_price - ib_high) / ib_high < 0.01  # Within 1%
        is_extreme = abs(vwap_deviation_sigmas) >= 2.0
        is_delta_flat = abs(delta_score) < 0.1

        if is_near_ib and is_extreme and is_delta_flat:
            return "VAH_PROBE_EXHAUSTION"
        elif is_near_ib and vwap_deviation_sigmas > 0:
            return "VAH_PROBE_TESTING"
        elif live_price > ib_high > 0:
            return "IB_BREAKOUT"

        return None

    @staticmethod
    def _check_exhaustion(
        delta_score: float,
        vwap_deviation_sigmas: float,
        aggression: float,
        volume_above_vah_pct: float,
    ) -> str | None:
        """Detect exhaustion at price extremes.

        Fabio AMT: when price is at extreme but delta is flat,
        the move lacks conviction and may reverse violently.
        """
        warnings: list[str] = []

        # Delta-flat at extreme (the critical signal)
        if abs(delta_score) < 0.1 and abs(vwap_deviation_sigmas) >= 2.0:
            warnings.append("EXHAUSTION: Delta neutral at VWAP extreme — move lacks conviction")

        # Low volume above VAH
        if volume_above_vah_pct < 10.0 and vwap_deviation_sigmas > 1.5:
            warnings.append("THIN_VOLUME: Only {:.1f}% volume above VAH — probe may reverse".format(volume_above_vah_pct))

        # Low aggression at extreme
        if aggression < 1.5 and abs(vwap_deviation_sigmas) >= 2.0:
            warnings.append("LOW_AGGRESSION: Weak participation at price extreme")

        if not warnings:
            return None

        severity = "HIGH" if len(warnings) >= 2 else "MEDIUM"
        return f"[{severity}] " + " | ".join(warnings)

    @staticmethod
    def _compute_volume_above_vah(
        profile: list,
        vah: float,
    ) -> float:
        """Compute percentage of volume above VAH."""
        if not profile or vah <= 0:
            return 0.0

        total_vol = sum(level.volume for level in profile)
        if total_vol <= 0:
            return 0.0

        vol_above = sum(level.volume for level in profile if level.price > vah)
        return (vol_above / total_vol) * 100

    @staticmethod
    def _compute_developing_va(developing_profile):
        """Compute developing Value Area from incremental profile."""
        dev_poc, dev_vah, dev_val = 0.0, 0.0, 0.0
        if developing_profile is not None:
            dev_profile_data = developing_profile.get_profile()
            if dev_profile_data and len(dev_profile_data) >= 3:
                dev_max_vol = max(p.volume for p in dev_profile_data)
                if dev_max_vol > 0:
                    dev_poc_idx = next(
                        i
                        for i, p in enumerate(dev_profile_data)
                        if p.volume == dev_max_vol
                    )
                    dev_poc = dev_profile_data[dev_poc_idx].price
                    dev_total = sum(p.volume for p in dev_profile_data)
                    dev_target = dev_total * 0.7
                    dev_acc = dev_max_vol
                    dev_up, dev_down = dev_poc_idx, dev_poc_idx
                    while dev_acc < dev_target:
                        can_up = dev_up + 1 < len(dev_profile_data)
                        can_down = dev_down - 1 >= 0
                        if not can_up and not can_down:
                            break
                        up_vol = dev_profile_data[dev_up + 1].volume if can_up else -1
                        dn_vol = (
                            dev_profile_data[dev_down - 1].volume if can_down else -1
                        )
                        if up_vol >= dn_vol:
                            dev_up += 1
                            dev_acc += dev_profile_data[dev_up].volume
                        else:
                            dev_down -= 1
                            dev_acc += dev_profile_data[dev_down].volume
                    dev_step = (
                        (dev_profile_data[1].price - dev_profile_data[0].price)
                        if len(dev_profile_data) > 1
                        else 0
                    )
                    dev_vah = dev_profile_data[dev_up].price + dev_step / 2
                    dev_val = dev_profile_data[dev_down].price - dev_step / 2
        return dev_poc, dev_vah, dev_val

    @staticmethod
    def _extract_session_open(data, current):
        """Extract session open price from first candle of current date."""
        current_date_prefix = current.time[:10] if len(current.time) >= 10 else ""
        if current_date_prefix:
            for d in data:
                if d.time.startswith(current_date_prefix):
                    return d.open
        return data[0].open if data else 0.0

    @staticmethod
    def _classify_day_type(data, ib_complete, ib_high, ib_low):
        """Classify day type: NORMAL, NEUTRAL, TREND, NORMAL_VARIATION."""
        if not ib_complete or ib_high <= 0 or ib_low <= 0:
            return "UNKNOWN"
        session_high = max(d.high for d in data)
        session_low = min(d.low for d in data)
        ib_range = ib_high - ib_low
        if ib_range <= 0:
            return "UNKNOWN"
        dist_above = max(0.0, session_high - ib_high)
        dist_below = max(0.0, ib_low - session_low)
        if dist_above == 0 and dist_below == 0:
            return "NORMAL"
        elif dist_above > 0 and dist_below > 0:
            return "NEUTRAL"
        elif dist_above > ib_range or dist_below > ib_range:
            return "TREND"
        return "NORMAL_VARIATION"

    def _build_vwap_bands(self, session_vwap: float, current) -> tuple[float, float, float, float, float, float | None]:
        """Compute VWAP standard deviation bands (±1σ, ±2σ)."""
        vwap_std = 0.0
        if self._vwap_cum_vol > 0 and len(self._vwap_price_deviations) > 1:
            # Calculate std from actual price deviations (Task 2.1 fix)
            mean_deviation = sum(self._vwap_price_deviations) / len(self._vwap_price_deviations)
            variance = sum((d - mean_deviation) ** 2 for d in self._vwap_price_deviations) / len(self._vwap_price_deviations)
            vwap_std = math.sqrt(max(0.0, variance))

            # Enforce minimum std to prevent extreme sigma values
            MIN_VWAP_STD = 1.0  # Increased from 0.5 for MCX options
            if vwap_std < MIN_VWAP_STD:
                vwap_std = MIN_VWAP_STD
            
            # Enforce maximum std (4σ is extreme, anything higher is calculation error)
            MAX_VWAP_STD = session_vwap * 0.10  # Max 10% of VWAP
            if vwap_std > MAX_VWAP_STD:
                logger.warning(
                    "VWAP std clamped from %.2f to %.2f (max 10%% of VWAP=%.2f)",
                    vwap_std, MAX_VWAP_STD, session_vwap
                )
                vwap_std = MAX_VWAP_STD

        vwap_upper_1 = session_vwap + vwap_std
        vwap_lower_1 = session_vwap - vwap_std
        vwap_upper_2 = session_vwap + 2 * vwap_std
        vwap_lower_2 = session_vwap - 2 * vwap_std

        live_price = float(current.close)
        vwap_deviation_sigmas: float | None = (
            (live_price - session_vwap) / vwap_std if vwap_std > 0 else None
        )
        
        # Sanity check: sigma should never exceed ±4 in normal markets (Task 2.1)
        if vwap_deviation_sigmas is not None and abs(vwap_deviation_sigmas) > 4.0:
            logger.warning(
                "VWAP deviation clamped: %.2fσ → ±4.0σ (vwap=%.2f, live=%.2f, std=%.2f)",
                vwap_deviation_sigmas, session_vwap, live_price, vwap_std
            )
            vwap_deviation_sigmas = 4.0 if vwap_deviation_sigmas > 0 else -4.0
        elif vwap_deviation_sigmas is not None and abs(vwap_deviation_sigmas) > 10:
            logger.warning(
                "VWAP deviation extreme: %.2fσ — possible data source mismatch "
                "(vwap=%.2f, live=%.2f, std=%.2f)",
                vwap_deviation_sigmas,
                session_vwap,
                live_price,
                vwap_std,
            )
        return vwap_upper_1, vwap_lower_1, vwap_upper_2, vwap_lower_2, vwap_std, vwap_deviation_sigmas

    def _classify_market_structure(self, data, session_vwap, market_state) -> tuple:
        """Classify market structure and cross-validate against market state."""
        if self._structure_classifier is None:
            self._structure_classifier = MarketStructureClassifier()
        if session_vwap > 0:
            self._vwap_history.append(session_vwap)
            if len(self._vwap_history) > 30:
                self._vwap_history = self._vwap_history[-30:]
        structure = self._structure_classifier.classify(
            data,
            self._poc_tracker._poc_history,
            self._vwap_history,
        )

        # Cross-validation: PROBING is incompatible with BALANCE or CHOP
        if market_state == MarketState.PROBING and structure.state in ("BALANCE", "CHOP"):
            structure = type(structure)(
                state="TRANSITION",
                confidence_score=max(structure.confidence_score, 60),
                features=structure.features,
            )
        return structure

    def _detect_breaks(self, recent_data, vah, val, ib_high, ib_low, baseline_vol,
                       live_price, ib_complete, current_break_direction) -> dict:
        """Detect initiative/responsive breaks and IB breaks."""
        break_state = detect_break(recent_data, vah, val, ib_high, ib_low, baseline_vol)
        if break_state is None:
            break_state = {
                "break_direction": "",
                "break_type": "",
                "break_level": 0.0,
                "volume_ratio": 0.0,
            }

        ib_tick_break = check_ib_break_tick(
            live_price=live_price,
            ib_high=ib_high,
            ib_low=ib_low,
            ib_complete=ib_complete,
            current_break_direction=current_break_direction,
        )
        if ib_tick_break["break_direction"]:
            self._ib_break_direction = ib_tick_break["break_direction"]
            break_state = {
                "break_direction": ib_tick_break["break_direction"],
                "break_type": ib_tick_break["break_type"],
                "break_level": ib_tick_break["break_level"],
                "volume_ratio": 1.0,
            }
        return break_state

    def _compute_noc_targets(self, npoc_tracker, underlying, current, tick_size) -> tuple[float, float]:
        """Check NPOC fills and return nearest targets above/below."""
        npoc_above = 0.0
        npoc_below = 0.0
        if npoc_tracker is not None:
            npoc_tracker.check_and_fill(
                underlying=underlying,
                current_price=float(current.close),
                tick_size=tick_size,
            )
            npoc_result = npoc_tracker.get_active_npocs(
                underlying=underlying,
                current_price=float(current.close),
            )
            if npoc_result.nearest_above:
                npoc_above = npoc_result.nearest_above.price
            if npoc_result.nearest_below:
                npoc_below = npoc_result.nearest_below.price
        return npoc_above, npoc_below

    def _compute_effective_market_state(
        self, market_state, recent_data, current, cvd_source: str = ""
    ) -> str:
        """Override market state to DEAD when volume is dead."""
        _effective_market_state: str = market_state.value
        # Option-premium candles are the wrong scale for futures volume EMA — never
        # force DEAD from this gate when AMT is still on option ticks only.
        if cvd_source == "option":
            return _effective_market_state
        if len(recent_data) >= 20:
            _alpha = 2.0 / 21
            _ema_vol = float(recent_data[-20].volume)
            for _d in recent_data[-19:]:
                _ema_vol = _alpha * float(_d.volume) + (1 - _alpha) * _ema_vol
            _latest_vol = float(recent_data[-1].volume)
            _vol_ratio = _latest_vol / _ema_vol if _ema_vol > 0 else 0.0
            if float(current.close) <= 0 or _vol_ratio < 0.01:
                _effective_market_state = "DEAD"
        return _effective_market_state

    def _compute_per_symbol_delta(self, option_tick) -> float:
        """Compute per-symbol delta from option tick (not underlying)."""
        if option_tick is not None and option_tick.volume > 0:
            return float(option_tick.delta) / float(option_tick.volume)
        return 0.0

    def _track_drives(self, live_price, poc, lvns, hvns, vah, val, tick_size, current) -> tuple[int, bool]:
        """Classify current price against nearest key level for drive tracking."""
        _drive_number: int = 0
        _drive_entry_valid: bool = False
        _all_levels: list[float] = [poc] + list(lvns) + ([vah, val] if vah > 0 and val > 0 else [])
        if _all_levels and live_price > 0:
            _nearest = min(_all_levels, key=lambda _l: abs(_l - live_price))
            _proximity_ticks = abs(live_price - _nearest) / max(tick_size, 0.001)
            if _proximity_ticks <= 5:
                _drive_dir = "LONG" if live_price >= _nearest else "SHORT"
                try:
                    _drive_result = self._drive_tracker.classify_touch(
                        price=live_price,
                        level=_nearest,
                        candle=current,
                        direction=_drive_dir,
                        tick_size=tick_size,
                    )
                    _drive_number = _drive_result.drive_number
                    _drive_entry_valid = _drive_result.entry_valid
                except Exception:
                    logger.debug("Drive detection failed — drive number will be unset", exc_info=True)
        return _drive_number, _drive_entry_valid

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
        symbol: str = "",  # Fix 1: Full symbol name for option type detection
        prior_avg_volume: float = 0.0,  # Prior session average volume for baseline
    ) -> AMTResult:
        """Run the full AMT analysis pipeline.

        Args:
            data: Candle data for analysis (may be underlying futures for options)
            order_book: Order book snapshot
            incremental_profile: Incremental volume profile state
            prior_poc: Previous session POC
            prior_vah: Previous session VAH
            prior_val: Previous session VAL
            developing_profile: Developing volume profile state
            cushion_tier: Risk cushion tier
            session_pnl: Session P&L
            npoc_tracker: Naked POC tracker
            underlying: Underlying symbol
            daily_data: Daily timeframe data
            hourly_data: Hourly timeframe data
            option_tick: Option contract tick (for per-symbol delta isolation)
            cvd_source: "underlying" if data comes from futures, "option" if from option premium
            prior_avg_volume: Prior session average volume for baseline comparison
        """
        # Store prior session avg volume for baseline calculation
        self._prior_session_avg_volume = prior_avg_volume
        
        empty = AMTResult(
            market_state=MarketState.BALANCED.value,
            poc=0,
            value_area_high=0,
            value_area_low=0,
        )

        if not data or len(data) < 5:
            logger.debug(
                "AMT: insufficient data — len(data)=%d", len(data) if data else 0
            )
            return empty

        lookback = len(data)
        recent_data = data[-lookback:]
        current = data[-1]

        # 1. Volume Profile — use incremental if available, else full rebuild
        if incremental_profile is not None:
            profile = incremental_profile.get_profile()
            logger.debug(
                "AMT: incremental profile — initialized=%s candles=%d profile_len=%d",
                incremental_profile._initialized,
                len(incremental_profile._candles),
                len(profile),
            )
        else:
            profile = create_profile(recent_data)
            logger.info("AMT: full rebuild profile — profile_len=%d", len(profile))
        if not profile:
            logger.info("AMT: empty profile — returning empty result")
            return empty

        # POC — tie-break: closest to VWAP when multiple bins share max volume
        max_vol = max(p.volume for p in profile)
        poc_candidates = [i for i, p in enumerate(profile) if p.volume == max_vol]
        vwap_ref = float(
            self._vwap_cum_quote_vol / self._vwap_cum_vol
            if self._vwap_cum_vol > 0
            else current.close
        )
        poc_index = min(poc_candidates, key=lambda i: abs(profile[i].price - vwap_ref))
        poc = profile[poc_index].price

        # Value Area (70%) — CME two-row pairs method
        total_volume = sum(p.volume for p in profile)
        target_volume = total_volume * VALUE_AREA_PCT
        current_volume = max_vol
        up_idx, down_idx = poc_index, poc_index

        while current_volume < target_volume:
            up_pair = 0.0
            up_count = 0
            for k in range(1, 3):
                if up_idx + k < len(profile):
                    up_pair += profile[up_idx + k].volume
                    up_count += 1
            down_pair = 0.0
            down_count = 0
            for k in range(1, 3):
                if down_idx - k >= 0:
                    down_pair += profile[down_idx - k].volume
                    down_count += 1

            can_go_up = up_count > 0
            can_go_down = down_count > 0

            if not can_go_up and not can_go_down:
                break

            if can_go_up and (not can_go_down or up_pair >= down_pair):
                for k in range(1, up_count + 1):
                    if up_idx + k < len(profile):
                        up_idx += 1
                        current_volume += profile[up_idx].volume
            elif can_go_down:
                for k in range(1, down_count + 1):
                    if down_idx - k >= 0:
                        down_idx -= 1
                        current_volume += profile[down_idx].volume

        step = profile[1].price - profile[0].price if len(profile) > 1 else 0
        half_step = step / 2
        vah = profile[up_idx].price + half_step
        val = profile[down_idx].price - half_step

        # LVN detection with persistence filter
        raw_lvns = find_lvns(profile, self.config)
        lvns = self._lvn_tracker.update(raw_lvns, profile)
        hvns = find_hvns(profile, self.config)

        # Incremental aggressive prints
        agg_prints = find_aggressive_prints(
            recent_data,
            AggressivePrintConfig(
                sigma_threshold=self.config.AGGRESSION_SIGMA_THRESHOLD,
                ema_period=self.config.AGGRESSION_EMA_PERIOD,
                delta_directionality_threshold=self.config.DELTA_DIRECTIONALITY_THRESHOLD,
                expiry_candles=getattr(self.config, "AGGRESSION_EXPIRY_CANDLES", 30),
            ),
            previous_prints=self._prev_agg_prints,
            previous_data_len=self._prev_agg_data_len,
        )
        self._prev_agg_prints = agg_prints
        self._prev_agg_data_len = len(recent_data)

        # Register prints in session registry and check for re-tests
        self._bubble_registry.register(agg_prints)
        bubble_retests = self._bubble_registry.get_retests(current.close)

        # Baseline volume for acceptance/rejection
        # Use prior session average volume when available (more meaningful baseline
        # than current session rolling average, especially in early session)
        prior_avg_vol = getattr(self, '_prior_session_avg_volume', 0.0)
        if prior_avg_vol > 0:
            baseline_vol = prior_avg_vol
        else:
            # Fallback to current session rolling average
            baseline_vol = (
                sum(d.volume for d in recent_data[-20:]) / min(20, len(recent_data))
                if recent_data
                else 0.0
            )

        # Acceptance/Rejection engine
        ar_state = self._ar_engine.update(current, vah, val, baseline_vol)

        # VWAP bands (moved up to provide sigma to market state detection)
        typical_price = (current.high + current.low + current.close) / 3
        session_vwap = self._update_session_vwap(current, typical_price)
        vwap_upper_1, vwap_lower_1, vwap_upper_2, vwap_lower_2, vwap_std, vwap_deviation_sigmas = \
            self._build_vwap_bands(session_vwap, current)

        # 2. Market State (4-state model)
        leg_data = self.detect_displacement_leg(recent_data)
        has_displacement = leg_data["has_displacement"]
        has_acceptance = detect_acceptance(recent_data, vah, val)

        # Task 2.3: Validate session VA encompasses leg VA bounds
        # Session profile uses all session data, leg profile uses only displacement leg
        # So session VA should be >= leg VA (session encompasses leg)
        leg_vah_temp = leg_data.get("vah", 0.0)
        leg_val_temp = leg_data.get("val", 0.0)
        if vah > 0 and leg_vah_temp > 0 and vah < leg_vah_temp:
            logger.warning(
                "Session VAH (%.2f) < Leg VAH (%.2f) — clamping to leg VAH (Task 2.3)",
                vah, leg_vah_temp
            )
            vah = leg_vah_temp
            
        if val > 0 and leg_val_temp > 0 and val > leg_val_temp:
            logger.warning(
                "Session VAL (%.2f) > Leg VAL (%.2f) — clamping to leg VAL (Task 2.3)",
                val, leg_val_temp
            )
            val = leg_val_temp

        if ar_state["acceptance_above"] or ar_state["acceptance_below"]:
            has_acceptance = True

        balance_window = min(len(recent_data), 20)
        inside_count = sum(
            1 for d in recent_data[-balance_window:] if val <= d.close <= vah
        )
        balance_ratio = inside_count / balance_window if balance_window > 0 else 0.0

        # IB state needed for market state detection (IB break → mode classification)
        ib_state = self._ib_tracker.update(current)
        ib_high, ib_low, ib_complete = ib_state.ib_high, ib_state.ib_low, ib_state.is_complete

        prices = sorted(set(float(d.close) for d in recent_data[-50:]))
        tick_size = min(
            (
                prices[i + 1] - prices[i]
                for i in range(len(prices) - 1)
                if prices[i + 1] > prices[i]
            ),
            default=0.05,
        )

        state_result = detect_market_state(
            price=float(current.close),
            poc=poc,
            vah=vah,
            val=val,
            tick_size=tick_size,
            has_displacement=has_displacement,
            has_acceptance=has_acceptance,
            balance_ratio=balance_ratio,
            leg_poc=leg_data.get("poc", 0.0),
            leg_vah=leg_data.get("vah", 0.0),
            leg_val=leg_data.get("val", 0.0),
            vwap_deviation_sigmas=vwap_deviation_sigmas,
            ib_break_direction=self._ib_break_direction,
            ib_complete=ib_complete,
            ib_high=ib_high,
            ib_low=ib_low,
        )
        market_state = state_result.state
        zone = state_result.zone

        log_state_transition(self._previous_state, market_state, state_result)
        self._previous_state = market_state

        # 3. Order Flow Detectors + Aggression Scoring
        flow = self._compute_order_flow_metrics(
            recent_data,
            order_book,
            current,
            agg_prints,
            market_state,
            lvns,
            vah,
            val,
            poc,
            tick_size,
        )
        avg_candle_vol = flow["avg_candle_vol"]
        obi = flow["obi"]
        toxicity = flow["toxicity"]
        norm_delta = flow["norm_delta"]
        footprint_confirmed = flow["footprint_confirmed"]
        cvd_confirmed = flow["cvd_confirmed"]
        cvd_state = flow["cvd_state"]
        big_trade_confirmed = flow["big_trade_confirmed"]
        absorption_detected = flow["absorption_detected"]
        absorption_side = flow["absorption_side"]
        absorption_range_ratio = flow["absorption_range_ratio"]
        absorption_vol_ratio = flow["absorption_vol_ratio"]
        ofi_result = flow["ofi_result"]
        ofi_aligned = flow["ofi_aligned"]
        confluence_bonus = flow["confluence_bonus"]
        volume_bubble_near = flow["volume_bubble_near"]
        agg_result = flow["agg_result"]
        aggression_score = flow["aggression_score"]
        has_aggression = flow["has_aggression"]

        # Profile shape and bimodal override
        shape = classify_shape(profile)
        effective_profile_shape = shape.shape
        _bimodal_active_pole = shape.active_pole

        if shape.shape == "B" and market_state == MarketState.IMBALANCED:
            market_state = MarketState.BALANCED
            effective_profile_shape = "D"

        # Session VWAP
        typical_price = (current.high + current.low + current.close) / 3
        session_vwap = self._update_session_vwap(current, typical_price)

        # VWAP bands
        vwap_upper_1, vwap_lower_1, vwap_upper_2, vwap_lower_2, vwap_std, vwap_deviation_sigmas = \
            self._build_vwap_bands(session_vwap, current)

        # CVD
        cvd_state = self._cvd_tracker.update(current)
        cvd_div = ""
        if cvd_state.has_divergence:
            cvd_div = cvd_state.divergence_type or ""

        # Market structure classification
        structure = self._classify_market_structure(data, session_vwap, market_state)

        # POC migration with price alignment
        poc_migration = self._poc_tracker.update(poc, current.close)

        # LVN velocity play detection
        lvn_play = detect_lvn_play(
            current,
            list(lvns),
            list(hvns),
            poc,
            baseline_vol,
            cvd_state.slope,
            self._prev_cvd_slope,
        )
        self._prev_cvd_slope = cvd_state.slope

        # Break detection
        break_state = self._detect_breaks(
            recent_data, vah, val, ib_high, ib_low, baseline_vol,
            float(current.close), ib_complete, self._ib_break_direction,
        )

        # Opening Type Classification
        opening_result = self._opening_classifier.classify(
            data=recent_data,
            prior_vah=prior_vah,
            prior_val=prior_val,
            prior_poc=prior_poc,
        )

        # Multi-Timeframe Alignment
        mtf_result = None
        if daily_data and hourly_data:
            mtf_result = self._mtf_analyzer.compute_alignment(
                current_price=float(current.close),
                daily_ohlc=daily_data,
                hourly_ohlc=hourly_data,
            )

        # Acceptance vs Rejection (re-check after all updates)
        ar_state = self._ar_engine.update(current, vah, val, baseline_vol)

        # Developing VA, session open, day type
        dev_poc, dev_vah, dev_val = self._compute_developing_va(developing_profile)
        session_open_price = self._extract_session_open(data, current)
        day_type = self._classify_day_type(data, ib_complete, ib_high, ib_low)

        # NPOC targets
        npoc_above, npoc_below = self._compute_noc_targets(
            npoc_tracker, underlying, current, tick_size,
        )

        # Signal Generation — DEPRECATED (backward compat)
        signal = None

        # Dead-volume override
        _effective_market_state = self._compute_effective_market_state(
            market_state, recent_data, current, cvd_source=cvd_source,
        )

        # Per-symbol delta
        delta_normalized_option = self._compute_per_symbol_delta(option_tick)

        # Drive Tracking
        _live_price = float(current.close)
        _drive_number, _drive_entry_valid = self._track_drives(
            _live_price, poc, lvns, hvns, vah, val, tick_size, current,
        )

        # ── Fabio AMT: VAH Probe / IB Test Detection ──────────────────
        vah_probe_state = self._detect_vah_probe(
            live_price=_live_price,
            vah=vah,
            ib_high=ib_high,
            vwap_deviation_sigmas=vwap_deviation_sigmas or 0.0,
            delta_score=delta_normalized_option,
        )

        # ── Fabio AMT: Volume Above VAH ───────────────────────────────
        volume_above_vah_pct = self._compute_volume_above_vah(profile, vah)

        # ── Fabio AMT: Exhaustion Detection at Extremes ───────────────
        exhaustion_warning = self._check_exhaustion(
            delta_score=delta_normalized_option,
            vwap_deviation_sigmas=vwap_deviation_sigmas or 0.0,
            aggression=aggression_score,
            volume_above_vah_pct=volume_above_vah_pct,
        )

        # ── Fabio AMT: Swing Delta Metadata ───────────────────────────
        _swing_delta_value = leg_data.get("swing_delta", 0.0)
        _swing_delta_timestamp = None
        _swing_delta_price = None
        # Swing delta occurred at the most recent aggressive print if available
        if agg_prints:
            _swing_delta_timestamp = agg_prints[-1].time
            _swing_delta_price = agg_prints[-1].price

        # ── SETUP IDENTIFICATION (3 PM Fix) ──────────────────────────
        _setup = SetupType.MEAN_REVERSION
        if state_result.is_extreme_deviation:
            _setup = SetupType.RESPONSIVE_FADE
        elif market_state == MarketState.IMBALANCED:
            _setup = SetupType.TREND_MODEL

        return AMTResult(
            market_state=_effective_market_state,
            poc=poc,
            value_area_high=vah,
            value_area_low=val,
            lvns=tuple(lvns),
            hvns=tuple(hvns),
            aggression=aggression_score,
            signal=signal,
            setup=_setup.value,
            profile=tuple(profile),
            aggressive_prints=tuple(agg_prints),
            profile_shape=effective_profile_shape,
            profile_type="Session",
            cvd_slope=cvd_state.slope,
            cvd_divergence=cvd_div,
            session_vwap=session_vwap,
            vwap_upper_1=vwap_upper_1,
            vwap_lower_1=vwap_lower_1,
            vwap_upper_2=vwap_upper_2,
            vwap_lower_2=vwap_lower_2,
            vwap_deviation_sigmas=vwap_deviation_sigmas,
            balance_ratio=balance_ratio,
            leg_profile=tuple(leg_data.get("profile", [])),
            leg_lvns=tuple(leg_data.get("lvns", [])),
            leg_poc=leg_data.get("poc", 0.0),
            leg_vah=leg_data.get("vah", 0.0),
            leg_val=leg_data.get("val", 0.0),
            swing_delta=leg_data.get("swing_delta", 0.0),
            has_displacement=leg_data.get("has_displacement", False)
            and (
                ib_complete
                and (float(current.close) > ib_high or float(current.close) < ib_low)
                if ib_high > 0 and ib_low > 0
                else leg_data.get("has_displacement", False)
            ),
            ib_high=ib_high,
            ib_low=ib_low if ib_low != float("inf") else 0.0,
            ib_complete=ib_complete,
            prior_poc=prior_poc,
            prior_vah=prior_vah,
            prior_val=prior_val,
            gap_type=(
                classify_gap(
                    open_price=session_open_price,
                    prior_close=prior_poc,
                    prior_range=(
                        prior_vah - prior_val
                        if prior_vah > 0 and prior_val > 0
                        else 0.0
                    ),
                )
                if prior_poc > 0
                else ""
            ),
            opening_bias=(
                opening_inventory_bias(
                    open_price=session_open_price,
                    prior_vah=prior_vah,
                    prior_val=prior_val,
                    current_price=_live_price,
                    session_vwap=session_vwap,
                    vwap_deviation_sigmas=vwap_deviation_sigmas,
                )
                if prior_vah > 0
                else ""
            ),
            acceptance_above=ar_state["acceptance_above"],
            acceptance_below=ar_state["acceptance_below"],
            rejection_at_high=ar_state["rejection_at_high"],
            rejection_at_low=ar_state["rejection_at_low"],
            liquidity_sweep=ar_state.get("liquidity_sweep", ""),
            price_velocity=ar_state["price_velocity"],
            poc_signal=poc_migration.signal,
            poc_vs_price=poc_migration.poc_vs_price,
            lvn_play=lvn_play,
            break_direction=break_state["break_direction"],
            break_type=break_state["break_type"],
            break_level=break_state["break_level"],
            ofi=ofi_result.ofi,
            dev_poc=dev_poc,
            dev_vah=dev_vah,
            dev_val=dev_val,
            cushion_tier=cushion_tier,
            session_pnl=session_pnl,
            bubble_retests=bubble_retests,
            npoc_above=npoc_above,
            npoc_below=npoc_below,
            opening_type=opening_result.type,
            mtf_alignment=mtf_result.alignment if mtf_result else "",
            daily_vah=mtf_result.daily.vah if mtf_result else 0.0,
            daily_val=mtf_result.daily.val if mtf_result else 0.0,
            daily_poc=mtf_result.daily.poc if mtf_result else 0.0,
            hourly_vah=mtf_result.hourly.vah if mtf_result else 0.0,
            hourly_val=mtf_result.hourly.val if mtf_result else 0.0,
            hourly_poc=mtf_result.hourly.poc if mtf_result else 0.0,
            day_type=day_type,
            absorption_side=absorption_side,
            absorption_range_ratio=absorption_range_ratio,
            absorption_vol_ratio=absorption_vol_ratio,
            delta_normalized_option=delta_normalized_option,
            drive_number=_drive_number,
            drive_entry_valid=_drive_entry_valid,
            cvd_source=cvd_source,
            bimodal_active_pole=_bimodal_active_pole,
            is_extreme_deviation=state_result.is_extreme_deviation,
            underlying_price=float(data[-1].close) if data else 0.0,
            # Fix 1: Option type for direction labeling
            option_type=detect_option_type(symbol),
            # Fabio AMT: VAH probe state overrides structure when at IB test
            market_structure=vah_probe_state if vah_probe_state else structure.state,
            structure_confidence=(
                structure.confidence_score * 0.7 if volume_above_vah_pct < 10.0 and vah_probe_state in ("VAH_PROBE_EXHAUSTION", "VAH_PROBE_TESTING")
                else structure.confidence_score
            ),
            vah_probe_state=vah_probe_state,
            exhaustion_warning=exhaustion_warning,
            swing_delta_timestamp=_swing_delta_timestamp,
            swing_delta_price=_swing_delta_price,
            volume_above_vah_pct=volume_above_vah_pct,
        )

    # -------------------------------------------------------------------
    # RL Observation Builder
    # -------------------------------------------------------------------

    def compute_observation(
        self,
        data: list[OHLC],
        order_book: OrderBook | None = None,
        prior_vah: float = 0.0,
        prior_val: float = 0.0,
    ) -> AMTObservation:
        """Build a full RL observation vector from current market state.

        This method runs the standard AMT analysis and enriches it with
        Valentini-specific features: CVD, profile shape, session context.
        """
        result = self.analyze(data, order_book)
        current = (
            data[-1]
            if data
            else OHLC(time="", open=0, high=0, low=0, close=0, volume=0)
        )

        # --- CVD --- (read state only; analyze() already called update())
        cvd_state = self._cvd_tracker.state()

        # --- Profile shape ---
        shape = classify_shape(list(result.profile))

        # --- POC migration ---
        poc_mig = self._poc_tracker.update(result.poc, current.close)

        # --- Session context ---
        open_price = data[0].open if data else 0.0
        use_prior_vah = prior_vah if prior_vah > 0 else result.value_area_high
        use_prior_val = prior_val if prior_val > 0 else result.value_area_low
        session_info = get_session_info(
            timestamp=current.time,
            open_price=open_price,
            prior_vah=use_prior_vah,
            prior_val=use_prior_val,
        )

        # --- Distance to POC (normalised by VA range) ---
        va_range = max(result.value_area_high - result.value_area_low, 1e-9)
        dist_to_poc = (current.close - result.poc) / va_range

        # --- Nearest LVN ---
        nearest_lvn = 0.0
        if result.lvns:
            nearest_lvn = min(result.lvns, key=lambda lvn: abs(current.close - lvn))

        # --- Aggression sigma ---
        agg_sigma = (
            compute_aggression_sigma(current, data[-50:]) if len(data) >= 20 else 0.0
        )

        # --- OBI ---
        obi = 0.0
        if order_book:
            bids_q = sum(b.quantity for b in order_book.bids)
            asks_q = sum(a.quantity for a in order_book.asks)
            total = bids_q + asks_q
            if total > 0:
                obi = (bids_q - asks_q) / total

        # --- Normalised delta ---
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
