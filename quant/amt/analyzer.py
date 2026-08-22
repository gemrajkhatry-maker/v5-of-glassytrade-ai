"""AMT Analyzer — Auction Market Theory analysis domain service.

Pure domain logic: volume profile construction, LVN/HVN detection,
market state assessment, and aggression scoring.  Signal generation is
delegated to the SignalGenerator service to honour SRP.

Enhanced with Valentini AMT features: 2.5σ aggression filter,
CVD tracking, profile shape classification, and session context.
"""

from __future__ import annotations
from quant.contracts.enums import MarketState

import logging
import math
import re
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

from quant.amt import compute as mc

from quant.contracts.enums import MarketState, SignalType, Source, SetupType
from quant.contracts.value_objects import (
    OHLC,
    OrderBook,
    VolumeProfileLevel,
    AggressivePrint,
    AMTResult,
)
from quant.amt.models.observation import AMTObservation
from quant.contracts.entities import Signal
from quant.contracts.constants import (
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
from quant.amt.orderflow.cvd import CVDTracker
from quant.amt.orderflow.detectors import (
    BigTradeDetector,
    BubbleDetector,
    OFICalculator,
    AbsorptionDetector,
)
from quant.amt.profile.classifier import (
    classify_shape,
    POCMigrationTracker,
)
from quant.amt.market.structure import (
    MarketStructureClassifier,
)
from quant.amt.session.context import (
    classify_gap,
    get_session_info,
    opening_inventory_bias,
)
from quant.amt.market.state_engine import (
    detect_market_state,
    log_state_transition,
)
from quant.amt.orderflow.drive import DriveTracker
from quant.amt.orderflow.aggression import (
    AggressionScorer,
    PersistentAggressionScorer,
)
from quant.amt.orderflow.aggressive_prints import (
    AggressivePrintConfig,
    AggressivePrintRegistry,
    compute_aggression_sigma,
    find_aggressive_prints,
)
from quant.amt.market.acceptance_rejection import (
    AcceptanceRejectionEngine,
    ARResult,
)
from quant.amt.session.ib_engine import InitialBalanceEngine
from quant.amt.market.break_detector import (
    detect_break,
    check_ib_break_tick,
)
from quant.amt.market.lvn_play import detect_lvn_play
from quant.amt.profile.volume_profile import create_profile
from quant.amt.profile.volume_profile import compute_value_area
from quant.amt.market.displacement import (
    detect_displacement,
    detect_acceptance,
)
from quant.amt.market.opening import OpeningTypeClassifier

# NOTE: ISymbolConfig is defined canonically in quant.contracts.ports.config_port.
# The local definition is kept for backward compatibility.
from quant.contracts.ports.config_port import ISymbolConfig

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
# Volume Profile — imported from quant.amt.profile.volume_profile
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Volume Profile + LVN/HVN Detection — imported from extracted services
# ---------------------------------------------------------------------------
from quant.amt.profile.migration import ValueMigrationTracker
from quant.amt.profile.volume_profile import IncrementalVolumeProfile
from quant.amt.profile.lvn import (
    find_lvns as _find_lvns_extracted,
    find_hvns as _find_hvns_extracted,
    LVNPersistenceTracker,
)


def find_lvns(
    profile: list[VolumeProfileLevel],
    cfg: AMTConfig | None = None,
    smoothed: list[float] | None = None,
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
    smoothed: list[float] | None = None,
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
# Initial Balance Tracker — imported from quant.amt.session.ib_engine
# Acceptance / Rejection — imported from quant.amt.market.acceptance_rejection
# Aggressive Prints — imported from quant.amt.orderflow.aggressive_prints
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Acceptance / Rejection — imported from quant.amt.market.acceptance_rejection
# Aggressive Prints — imported from quant.amt.orderflow.aggressive_prints
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Break Detection — imported from quant.amt.market.break_detector
# LVN Play Detection — imported from quant.amt.market.lvn_play
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

    NOTE: This analyzer is NOT internally thread-safe (it mutates session data,
    VWAP accumulators, and the IB/aggression trackers across calls). Callers must
    serialize access per symbol — AMTHandler does this via its ``_analyze_lock``.
    """

    def __init__(
        self,
        config: AMTConfig | None = None,
        symbol_config: "SymbolConfigLike | None" = None,
    ) -> None:
        self.config = config or AMTConfig()
        self._cvd_tracker = CVDTracker()
        self._poc_tracker = POCMigrationTracker()
        self._value_migration = ValueMigrationTracker()
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
        # Session bar history (OHLC) for True Range ATR in absorption checks
        self._session_data: list[OHLC] = []
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
        # MTFAnalyzer removed - uses MultiTimeframeAMTAnalyzer in configure() instead
        # self._mtf_analyzer = MTFAnalyzer()  # This class doesn't exist, causes NameError
        # Initialize LVN tracker here to avoid AttributeError if configure() not called
        from quant.contracts.constants import LVN_MIN_PERSISTENCE_BARS, LVN_REMOVAL_THRESHOLD
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

    @staticmethod
    def _detect_option_type(symbol: str) -> str:
        """Detect whether symbol is CALL, PUT, or UNKNOWN.

        Anchored detection — a trailing CALL/PUT word or a digit-suffixed
        CE/PE token — so an underlying name containing "CE"/"PE"/"CALL"/
        "PUT" as a substring (e.g. PRINCE, SPICE, CALLAWAY) can never flip
        the label. Used for direction labeling in frontend.
        """
        if not symbol:
            return "UNKNOWN"
        sym = symbol.upper().rstrip()
        if sym.endswith("CALL") or re.search(r"\d+\s*CE$", sym):
            return "CALL"
        if sym.endswith("PUT") or re.search(r"\d+\s*PE$", sym):
            return "PUT"
        return "UNKNOWN"

    def detect_displacement_leg(self, data: list[OHLC]) -> dict:
        """Detect displacement and return leg profile data.

        Always builds a leg profile from the most recent directional move
        (consecutive same-direction candles from the end). The strict displacement
        flag is set when the move also meets range expansion criteria.
        """
        def _leg_result(*, has_displacement: bool, profile: list,
                        lvns: list, poc: float, vah: float, val: float,
                        swing_delta: float) -> dict:
            """Single constructor for the leg-result shape — the former
            inline literals had divergent key sets (audit SMELL-9)."""
            return {
                "has_displacement": has_displacement,
                "profile": profile,
                "lvns": lvns,
                "poc": poc,
                "vah": vah,
                "val": val,
                "swing_delta": swing_delta,
            }

        empty = _leg_result(has_displacement=False, profile=[], lvns=[],
                            poc=0.0, vah=0.0, val=0.0, swing_delta=0.0)
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
            return _leg_result(
                has_displacement=is_disp, profile=leg_profile, lvns=[],
                poc=0.0, vah=0.0, val=0.0,
                swing_delta=sum(c.delta for c in leg_candles),
            )
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
        return _leg_result(
            has_displacement=is_disp,
            profile=leg_profile,
            lvns=leg_lvns,
            poc=leg_poc,
            vah=leg_vah,
            val=leg_val,
            swing_delta=sum(c.delta for c in leg_candles),
        )

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
            self._session_data = []  # Reset bar history on new session
            self._ib_tracker.reset()
            self._ib_break_direction = ""
            self._ar_engine.reset()
            self._persistent_agg_scorer.reset()
            self._lvn_tracker.reset()
            self._value_migration.reset()
        _is_new_candle = current.time != self._vwap_last_time
        self._vwap_last_time = current.time
        
        # Accumulate volume and quote volume (typical_price * volume) ONLY for
        # a NEW candle. Sub-candle re-feeds pass the same candle as data[-1]
        # again; accumulating its volume unconditionally would double-count it
        # and inflate the session VWAP (audit B-20). The bar-history dedup
        # below already follows this rule — the accumulators must too.
        if _is_new_candle:
            self._vwap_cum_vol += float(current.volume)
            self._vwap_cum_quote_vol += float(quote_vol)
            
            # Shifted variance calculation for better numerical stability
            if self._vwap_shift == 0.0:
                self._vwap_shift = typical_price  # anchor to first tick
            
            shifted = typical_price - self._vwap_shift
            self._vwap_cum_sq_vol += float(shifted * shifted * current.volume)
        
        # Accumulate bar history for True Range ATR (dedup: analyze() re-feeds
        # the same candle on sub-candle ticks)
        if not self._session_data or self._session_data[-1].time != current.time:
            self._session_data.append(current)
            if len(self._session_data) > 500:
                self._session_data = self._session_data[-500:]
        
        return float(
            self._vwap_cum_quote_vol / self._vwap_cum_vol
            if self._vwap_cum_vol > 0
            else current.close
        )

    def _compute_atr(self, period: int = 14, data: list[OHLC] | None = None) -> float:
        """Average True Range over the last `period` bars.

        True Range per bar: TR = max(high - low, |high - prev_close|,
        |low - prev_close|).  Defaults to the accumulated session bar history;
        an explicit bar list can be supplied for callers holding recent data.
        """
        bars = data if data is not None else self._session_data
        if len(bars) < 2:
            return 0.0
        trs: list[float] = []
        for i in range(1, len(bars)):
            h = float(bars[i].high)
            l = float(bars[i].low)
            pc = float(bars[i - 1].close)
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        window = trs[-period:]
        return sum(window) / max(len(window), 1)

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
        atr = self._compute_atr(period=14, data=recent_data)
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

    def _recent_vwap_stats(self, recent_data) -> tuple[float, float]:
        """Volume-weighted VWAP + std over an explicit candle window.

        Same shifted-variance math and proportional clamps as the whole-session
        path, but over the given window. Used so the VWAP bands, the deviation
        sigma and the displayed session VWAP are computed on the SAME window as
        the VA clamp (RECENT_VA_LOOKBACK).  Otherwise a regime collapse (e.g.
        option premium 195 -> 102) leaves the whole-session accumulator far
        above the current auction — "LTP +2.4σ EXTREME DEVIATION" while the
        recent-clamped VA reads "Balance: 100% in VA".
        """
        tot_vol = 0.0
        tot_quote = 0.0
        tot_sq = 0.0
        shift = 0.0
        for d in recent_data:
            tp = (float(d.high) + float(d.low) + float(d.close)) / 3.0
            v = float(d.volume)
            if v <= 0:
                continue
            if shift == 0.0:
                shift = tp
            tot_vol += v
            tot_quote += tp * v
            s = tp - shift
            tot_sq += s * s * v
        if tot_vol <= 0:
            return 0.0, 0.0
        vwap = tot_quote / tot_vol
        variance = max(0.0, tot_sq / tot_vol - (vwap - shift) ** 2)
        vwap_std = math.sqrt(variance)
        # Proportional clamp bounds (0.1% floor, 3% cap) — same as session path
        min_std = max(1.0, vwap * 0.001)
        if vwap_std < min_std:
            vwap_std = min_std
        max_std = vwap * 0.03
        if vwap_std > max_std:
            vwap_std = max_std
        return vwap, vwap_std

    def _build_vwap_bands(self, session_vwap: float, current, recent_data=None) -> tuple[float, float, float, float, float, float | None]:
        """Compute VWAP standard deviation bands (±1σ, ±2σ).

        When `recent_data` is provided the VWAP and std are recomputed
        volume-weighted over that window (the same basis as the VA clamp) —
        this is what analyze() uses, so the deviation sigma and the displayed
        VWAP describe the current auction instead of a stale whole-session mix.
        Otherwise the whole-session accumulators are used (backward compatible
        for direct callers).
        """
        if recent_data:
            session_vwap, vwap_std = self._recent_vwap_stats(recent_data)
        else:
            vwap_std = 0.0
            if self._vwap_cum_vol > 0:
                # Volume-weighted std from the shifted-variance accumulator:
                # σ² = E[(TP - VWAP)²] = E[(TP - shift)²] - (VWAP - shift)²
                variance = (
                    self._vwap_cum_sq_vol / self._vwap_cum_vol
                    - (session_vwap - self._vwap_shift) ** 2
                )
                vwap_std = math.sqrt(max(0.0, variance))

                # Proportional clamp bounds (0.1% floor, 3% cap of session VWAP)
                MIN_VWAP_STD = max(1.0, session_vwap * 0.001)
                if vwap_std < MIN_VWAP_STD:
                    vwap_std = MIN_VWAP_STD

                # Enforce maximum std (4σ is extreme, anything higher is calculation error)
                MAX_VWAP_STD = session_vwap * 0.03  # Max 3% of VWAP
                if vwap_std > MAX_VWAP_STD:
                    logger.warning(
                        "VWAP std clamped from %.2f to %.2f (max 3%% of VWAP=%.2f)",
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

        # Cross-validation: skip if market_state is BALANCED or IMBALANCED (no PROBING in 2-state model)
        if market_state == MarketState.IMBALANCED and structure.state in ("BALANCE", "CHOP"):
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
                _effective_market_state = MarketState.DEAD.value
        return _effective_market_state

    def _compute_per_symbol_delta(self, option_tick, current_candle: OHLC | None = None) -> float:
        """Compute per-symbol normalized delta (-1.0 to +1.0) from option tick or current candle."""
        if option_tick is not None and getattr(option_tick, "volume", 0) > 0:
            return max(-1.0, min(1.0, float(option_tick.delta) / float(option_tick.volume)))
        if current_candle is not None and getattr(current_candle, "volume", 0) > 0:
            return max(-1.0, min(1.0, float(current_candle.delta) / float(current_candle.volume)))
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
        prior_avg_volume: float = 0.0,  # Average volume from prior sessions
        footprint_accumulator: "TickFootprintAccumulator | None" = None,
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
            footprint_accumulator: Optional footprint accumulator for tick-level footprints
        """
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

        # Value Area — CME two-row pairs method (shared impl, average-weighted)
        vah, val = compute_value_area(profile, poc_index, VALUE_AREA_PCT)

        # Clamp the value area to the recently-traded range. After an intraday
        # regime collapse (e.g. the option premium halving 195 -> 102), the
        # whole-session profile legitimately spans both regimes, so 70% of the
        # session's volume can extend VAH far beyond the current auction (~158
        # while price sits at ~102). The VA used for decisions must reflect the
        # CURRENT auction — clamp VAH/VAL to the high/low of the last
        # RECENT_VA_LOOKBACK candles so a stale tail can never dominate.
        from quant.contracts.constants import RECENT_VA_LOOKBACK

        recent_window = recent_data[-RECENT_VA_LOOKBACK:]
        if recent_window:
            recent_high = max(d.high for d in recent_window)
            recent_low = min(d.low for d in recent_window)
            if recent_high > 0:
                vah = min(vah, recent_high)
            if recent_low > 0:
                val = max(val, recent_low)
            # Keep the interval valid if the recent range sits entirely above
            # (or below) the whole-session VA.
            if vah < val:
                vah, val = recent_high, recent_low

        # LVN detection with persistence filter
        raw_lvns = find_lvns(profile, self.config)
        lvns = self._lvn_tracker.update(raw_lvns, profile)
        hvns = find_hvns(profile, self.config)

        # Exclude HVNs that coincide with the POC to avoid duplicate overlapping lines
        poc_price = float(poc)
        tick_approx = (profile[1].price - profile[0].price) if len(profile) > 1 else 0.05
        hvns = [h for h in hvns if abs(h - poc_price) > 3.0 * tick_approx]

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
        baseline_vol = (
            sum(d.volume for d in recent_data[-20:]) / min(20, len(recent_data))
            if recent_data
            else 0.0
        )

        # Acceptance/Rejection engine
        ar_state = self._ar_engine.update(current, vah, val, baseline_vol)

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

        prices = sorted(set(float(d.close) for d in recent_data[-50:]))
        tick_size = min(
            (
                prices[i + 1] - prices[i]
                for i in range(len(prices) - 1)
                if prices[i + 1] > prices[i]
            ),
            default=0.05,
        )

        # Update session VWAP and compute bands before market state detection
        typical_price = (current.high + current.low + current.close) / 3.0
        session_vwap = self._update_session_vwap(current, typical_price)
        _, _, _, _, _, vwap_deviation_sigmas = self._build_vwap_bands(session_vwap, current)

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

        # VWAP bands — same recent window as the VA clamp, so the deviation
        # sigma, the bands and the displayed session VWAP describe the CURRENT
        # auction (fixes the "LTP +2.4σ EXTREME DEVIATION" vs "Balance: 100%
        # in VA" contradiction after a regime collapse).
        recent_vwap, _ = self._recent_vwap_stats(recent_window)
        vwap_upper_1, vwap_lower_1, vwap_upper_2, vwap_lower_2, vwap_std, vwap_deviation_sigmas = \
            self._build_vwap_bands(recent_vwap, current, recent_data=recent_window)

        # CVD
        cvd_state = self._cvd_tracker.update(current)
        cvd_div = ""
        if cvd_state.has_divergence:
            cvd_div = cvd_state.divergence_type or ""

        # Market structure classification
        structure = self._classify_market_structure(data, session_vwap, market_state)

        # Initial Balance tracking — pinned to the session's first candle so
        # the 60-minute build window measures from the actual session open
        # (09:15 NSE / 09:00 MCX), not from the first analyzed bar (Fabio: IB
        # is the high/low of the first hour of the session).
        ib_state = self._ib_tracker.update(
            current, session_open=data[0].time if data else None
        )
        ib_high, ib_low, ib_complete = ib_state.ib_high, ib_state.ib_low, ib_state.is_complete

        # POC migration with price alignment
        poc_migration = self._poc_tracker.update(poc, current.close)

        # Value migration — session VA development over successive 15-min
        # windows (POC/VAH/VAL drift), so the value area's ongoing evolution is
        # an explicit feature instead of a frozen reference.
        value_migration = self._value_migration.update(
            current, poc, vah, val,
            session_open=data[0].time if data else None,
        )

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
        if daily_data and hourly_data and hasattr(self, "_mtf_analyzer"):
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
        delta_normalized_option = self._compute_per_symbol_delta(option_tick, current)

        # Drive Tracking
        _live_price = float(current.close)
        _drive_number, _drive_entry_valid = self._track_drives(
            _live_price, poc, lvns, hvns, vah, val, tick_size, current,
        )

        # ── SETUP IDENTIFICATION (3 PM Fix) ──────────────────────────
        _setup = SetupType.MEAN_REVERSION
        if state_result.is_extreme_deviation:
            _setup = SetupType.RESPONSIVE_FADE
        elif market_state == MarketState.IMBALANCED:
            _setup = SetupType.TREND_MODEL

        # Get footprints from accumulator if available + contested-zone flag
        # (both BUY and SELL stacked imbalances in the recent window = FLAT,
        # Fabio Gap #2: neither side has control).
        _contested_zone = False
        _footprints = {}
        if footprint_accumulator is not None:
            from quant.amt.orderflow.footprint import detect_contested_zone

            _footprints = footprint_accumulator.get_all()
            try:
                _contested_zone = detect_contested_zone(
                    list(_footprints.values())
                )
            except Exception:
                logger.debug("contested-zone detection failed", exc_info=True)

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
            session_vwap=recent_vwap if recent_vwap > 0 else session_vwap,
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
            ib_poc=ib_state.ib_poc,
            ib_vah=ib_state.ib_vah,
            ib_val=ib_state.ib_val,
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
            # Depth reaches the decision path: the live order-book imbalance
            # (bid-heavy +1 .. ask-heavy -1) from the depth snapshot. Gate 3
            # consumes it as the order-flow aggression (A3) confirmation.
            obi=obi,
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
            market_structure=structure.state,
            structure_confidence=structure.confidence_score,
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
            value_migration=value_migration,
            underlying_price=float(current.close) if data else 0.0,
            option_type=self._detect_option_type(symbol),
            footprints=_footprints,
            contested_zone=_contested_zone,
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
