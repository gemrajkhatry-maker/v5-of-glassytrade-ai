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
from quant.amt.triple_a import TripleAMachine
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
        # Session VWAP accumulator (extracted from inline state — audit decomposition step 1)
        from quant.amt.profile.vwap import SessionVWAP
        self._vwap = SessionVWAP()
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
        from quant.amt.market.regime import RegimeDetector
        self._regime = RegimeDetector()  # ponytail: wire-up only; detector math already existed
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
        self._triple_a = TripleAMachine()
        self._session_market = "NSE"
        self._last_resolve_key = ""

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

    def _update_session_vwap(self, current, typical_price) -> float:
        """Update session VWAP with session boundary detection and accumulation.

        Delegates accumulation to SessionVWAP; handles session-boundary
        resets of non-VWAP trackers (IB, CVD, drives, etc.).

        Returns the current session VWAP value.
        """
        _reset_session = False
        if self._vwap._last_time:
            from quant.state import session_date_key
            prev_date = session_date_key(self._vwap._last_time)
            curr_date = session_date_key(current.time)
            if prev_date and curr_date and curr_date != prev_date:
                _reset_session = True
        if _reset_session:
            # Reset non-VWAP trackers (VWAP reset is handled by SessionVWAP.update)
            self._ib_tracker.reset()
            self._ib_break_direction = ""
            self._ar_engine.reset()
            self._persistent_agg_scorer.reset()
            self._lvn_tracker.reset()
            self._value_migration.reset()
            self._drive_tracker.reset()
            self._cvd_tracker.reset()
            self._triple_a.reset()
            self._vwap.reset()
        return self._vwap.update(current, typical_price)

    # ponytail: dead methods below deleted — all callers migrated to
    # quant.amt.orderflow.compute, quant.amt.session.structure,
    # quant.amt.profile.displacement, quant.amt.profile.vwap.

    def analyze(
        self,
        data: list[OHLC],
        order_book: OrderBook | None = None,
        incremental_profile: IncrementalVolumeProfile | None = None,
        prior_poc: float = 0.0,
        prior_vah: float = 0.0,
        prior_val: float = 0.0,
        prior_close: float = 0.0,
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
        gex: object | None = None,
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
        self._last_resolve_key = symbol or underlying or self._last_resolve_key
        try:
            from quant.contracts.instrument_registry import DEFAULT_REGISTRY
            spec = DEFAULT_REGISTRY.try_resolve(self._last_resolve_key)
            if spec is not None:
                self._session_market = spec.session_profile
        except Exception:
            pass

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
        vwap_ref = self._vwap.vwap(bar_close=current.close)
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

        # Acceptance/Rejection engine — FIRST pass (real bar-to-bar duration);
        # its price_velocity is what we emit. The re-check below rebinds
        # `ar_state` with dt=0 for the same bar and zero-velocity.
        ar_state_first = self._ar_engine.update(current, vah, val, baseline_vol)

        # 2. Market State (4-state model)
        from quant.amt.profile.displacement import detect_displacement_leg as _detect_disp_leg
        leg_data = _detect_disp_leg(recent_data, self.config)
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

        if ar_state_first["acceptance_above"] or ar_state_first["acceptance_below"]:
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
        _, _, _, _, _, vwap_deviation_sigmas = self._vwap.bands(session_vwap, current)

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
        from quant.amt.orderflow.compute import compute_order_flow_metrics as _compute_ofm
        flow = _compute_ofm(
            recent_data, order_book, current, agg_prints, market_state,
            lvns, vah, val, poc, tick_size,
            cvd_state=self._cvd_tracker.state(),
            big_trade_detector=self._big_trade_detector,
            absorption_detector=self._absorption_detector,
            ofi_calculator=self._ofi_calculator,
            bubble_detector=self._bubble_detector,
            persistent_agg_scorer=self._persistent_agg_scorer,
            session_bars=self._vwap.session_bars,
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
        from quant.amt.profile.vwap import SessionVWAP as _SVWAP
        recent_vwap, _ = _SVWAP.recent_stats(recent_window)
        vwap_upper_1, vwap_lower_1, vwap_upper_2, vwap_lower_2, vwap_std, vwap_deviation_sigmas = \
            self._vwap.bands(recent_vwap, current, recent_data=recent_window)

        # CVD
        cvd_state = self._cvd_tracker.update(current)
        cvd_div = ""
        if cvd_state.has_divergence:
            cvd_div = cvd_state.divergence_type or ""

        # Market structure classification
        from quant.amt.session.structure import classify_market_structure as _classify_ms
        structure = _classify_ms(
            data, session_vwap, market_state,
            self._structure_classifier or MarketStructureClassifier(),
            self._vwap_history, self._poc_tracker._poc_history,
        )
        if self._structure_classifier is None:
            self._structure_classifier = MarketStructureClassifier()

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
        from quant.amt.session.structure import detect_breaks as _detect_breaks_fn
        break_state, self._ib_break_direction = _detect_breaks_fn(
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
        from quant.amt.session.structure import _compute_developing_va
        dev_poc, dev_vah, dev_val = _compute_developing_va(developing_profile)
        from quant.amt.session.structure import (
            extract_session_open as _extract_open,
            classify_day_type as _classify_dt,
            compute_noc_targets as _compute_noc,
            compute_effective_market_state as _compute_eff,
            compute_per_symbol_delta as _compute_delta,
        )
        from quant.amt.orderflow.compute import track_drives as _track_dr

        session_open_price = _extract_open(data, current)
        day_type = _classify_dt(data, ib_complete, ib_high, ib_low)

        # NPOC targets
        npoc_above, npoc_below = _compute_noc(npoc_tracker, underlying, current, tick_size)

        # Signal Generation — DEPRECATED (backward compat)
        signal = None

        # Dead-volume override
        _effective_market_state = _compute_eff(market_state, recent_data, current, cvd_source=cvd_source)

        # Per-symbol delta
        delta_normalized_option = _compute_delta(option_tick, current)

        # Drive Tracking
        _live_price = float(current.close)
        _drive_number, _drive_entry_valid = _track_dr(
            _live_price, poc, lvns, hvns, vah, val, tick_size, current,
            drive_tracker=self._drive_tracker,
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

        _triple = self._triple_a.update(
            close=float(current.close),
            high=float(current.high),
            low=float(current.low),
            absorption_side=absorption_side,
            vwap=float(recent_vwap if recent_vwap > 0 else session_vwap),
            cvd_slope=float(cvd_state.slope),
        )

        result = self._build_result(
            current=current, data=data, symbol=symbol,
            profile=profile, poc=poc, vah=vah, val=val,
            lvns=lvns, hvns=hvns, aggression_score=aggression_score,
            signal=signal, _setup=_setup, agg_prints=agg_prints,
            effective_profile_shape=effective_profile_shape,
            cvd_state=cvd_state, cvd_div=cvd_div,
            recent_vwap=recent_vwap, session_vwap=session_vwap,
            vwap_upper_1=vwap_upper_1, vwap_lower_1=vwap_lower_1,
            vwap_upper_2=vwap_upper_2, vwap_lower_2=vwap_lower_2,
            vwap_deviation_sigmas=vwap_deviation_sigmas,
            balance_ratio=balance_ratio, leg_data=leg_data,
            ib_complete=ib_complete, ib_high=ib_high, ib_low=ib_low,
            ib_state=ib_state, prior_poc=prior_poc, prior_vah=prior_vah,
            prior_val=prior_val, prior_close=prior_close,
            session_open_price=session_open_price,
            price_velocity_first=ar_state_first["price_velocity"],
            ar_state=ar_state, poc_migration=poc_migration,
            lvn_play=lvn_play, break_state=break_state,
            ofi_result=ofi_result, obi=obi,
            dev_poc=dev_poc, dev_vah=dev_vah, dev_val=dev_val,
            cushion_tier=cushion_tier, session_pnl=session_pnl,
            bubble_retests=bubble_retests, npoc_above=npoc_above,
            npoc_below=npoc_below, opening_result=opening_result,
            mtf_result=mtf_result, structure=structure,
            day_type=day_type, absorption_side=absorption_side,
            absorption_range_ratio=absorption_range_ratio,
            absorption_vol_ratio=absorption_vol_ratio,
            delta_normalized_option=delta_normalized_option,
            _drive_number=_drive_number, _drive_entry_valid=_drive_entry_valid,
            cvd_source=cvd_source, _bimodal_active_pole=_bimodal_active_pole,
            state_result=state_result, value_migration=value_migration,
            _footprints=_footprints, _contested_zone=_contested_zone,
            _triple=_triple, _effective_market_state=_effective_market_state,
            gex=gex,
        )

        # Squeeze detection (Fabio Playbook #4): runs on the assembled result
        # because it needs the canonical session VA (val/vah) from above.
        # AMTResult is frozen, so we rebuild it with the squeeze fields set.
        from dataclasses import replace as _dc_replace
        sq = self._regime.detect_squeeze(recent_data, result)
        return _dc_replace(
            result,
            squeeze_direction=sq.direction if sq else "",
            squeeze_trapped_level=sq.trapped_level if sq else 0.0,
        )

    def _build_result(self, *, current, data, symbol, profile, poc, vah, val,
                  lvns, hvns, aggression_score, signal, _setup, agg_prints,
                      effective_profile_shape, cvd_state, cvd_div,
                      recent_vwap, session_vwap, vwap_upper_1, vwap_lower_1,
                      vwap_upper_2, vwap_lower_2, vwap_deviation_sigmas,
                      balance_ratio, leg_data, ib_complete, ib_high, ib_low,
                      ib_state, prior_poc, prior_vah, prior_val, prior_close,
                      session_open_price, ar_state, poc_migration, lvn_play,
                  price_velocity_first,
                      break_state, ofi_result, obi, dev_poc, dev_vah, dev_val,
                      cushion_tier, session_pnl, bubble_retests, npoc_above,
                      npoc_below, opening_result, mtf_result, structure,
                      day_type, absorption_side, absorption_range_ratio,
                      absorption_vol_ratio, delta_normalized_option,
                      _drive_number, _drive_entry_valid, cvd_source,
                      _bimodal_active_pole, state_result, value_migration,
                      _footprints, _contested_zone, _triple,
                      _effective_market_state, gex=None) -> AMTResult:
        """Assemble AMTResult from computed pipeline outputs.

        Pure data mapping — extracted from analyze() for readability.
        """
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
                    prior_close=(prior_close if prior_close > 0 else prior_poc),
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
            price_velocity=price_velocity_first,  # first pass carries the real duration
            poc_signal=poc_migration.signal,
            poc_vs_price=poc_migration.poc_vs_price,
            lvn_play=lvn_play,
            break_direction=break_state["break_direction"],
            break_type=break_state["break_type"],
            break_level=break_state["break_level"],
            ofi=ofi_result.ofi,
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
            triple_a_phase=_triple.phase,
            triple_a_signal=_triple.signal,
            absorption_cluster_high=_triple.cluster_high,
            absorption_cluster_low=_triple.cluster_low,
            gex=gex,
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
        try:
            from quant.contracts.instrument_registry import DEFAULT_REGISTRY
            spec = DEFAULT_REGISTRY.try_resolve(self._last_resolve_key)
            if spec is not None:
                self._session_market = spec.session_profile
        except Exception:
            pass

        session_info = get_session_info(
            timestamp=current.time,
            open_price=open_price,
            prior_vah=use_prior_vah,
            prior_val=use_prior_val,
            market=self._session_market,
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
