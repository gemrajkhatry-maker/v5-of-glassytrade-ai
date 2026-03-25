"""AMT Analyzer — Auction Market Theory analysis domain service.

Pure domain logic: volume profile construction, LVN/HVN detection,
market state assessment, and aggression scoring.  Signal generation is
delegated to the SignalGenerator service to honour SRP.

Enhanced with Valentini AMT features: 2.5σ aggression filter,
CVD tracking, profile shape classification, and session context.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import TYPE_CHECKING

from app.domain.fabio_ai.services import mlx_compute as mc

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
from app.domain.constants import LVN_MIN_PERSISTENCE_BARS, LVN_REMOVAL_THRESHOLD
from app.domain.fabio_ai.services.cvd_tracker import CVDTracker
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
from app.domain.services.initial_balance import InitialBalanceTracker
from app.domain.services.break_detector import detect_break
from app.domain.services.lvn_play_detector import detect_lvn_play
from app.domain.services.volume_profile import create_profile

if TYPE_CHECKING:
    from app.config_models import SymbolConfig


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class AMTConfig:
    # LVN/HVN thresholds from constants.py (Fabio spec-compliant)
    from app.domain import constants

    LVN_THRESHOLD: float = constants.LVN_THRESHOLD  # < 15% of mean (Fabio spec)
    LVN_SMOOTHING: int = 3  # Smooth histogram before LVN/HVN detection
    OBI_THRESHOLD: float = 0.25
    DELTA_THRESHOLD: float = 0.3
    ABSORPTION_THRESHOLD: float = 0.3
    STOP_BUFFER: float = 0.001
    BUBBLE_VOL_MULTIPLIER: float = 1.5
    AGGRESSION_EMA_PERIOD: int = 20  # EMA period for dynamic volume threshold
    DELTA_DIRECTIONALITY_THRESHOLD: float = 0.40  # Professional: 40-50% delta ratio
    HVN_THRESHOLD: float = constants.HVN_THRESHOLD  # > 200% of mean (Fabio spec)

    # FIX #9: Balance ratio threshold for Indian markets
    # Indian options have wider ranges due to gamma/theta
    # Adjusted from default 0.50 to 0.55 for more realistic balance detection

    # Configurable via env — tune for MCX with lower values
    # Default values from Fabio spec (overridable via env)
    AGGRESSION_SIGMA_THRESHOLD: float = 2.5
    AGGRESSION_EXPIRY_CANDLES: int = 30
    DISPLACEMENT_MULTIPLIER: float = 1.5
    BALANCE_RATIO_THRESHOLD: float = 0.55

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


def smooth_array(data: list[float], window: int) -> list[float]:
    """Centered simple moving average smoothing (MLX-accelerated)."""
    return mc.smooth_array(data, window)


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
    smoothed: list[float] | None = None,
) -> list[float]:
    """Thin wrapper — extracts prices from LVNLevel objects."""
    cfg = cfg or AMTConfig()
    levels = _find_lvns_extracted(
        profile,
        lvn_threshold=cfg.LVN_THRESHOLD,
        smoothing_window=cfg.LVN_SMOOTHING,
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
        symbol_config: "SymbolConfig | None" = None,
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
        self._vwap_cum_sq_vol: float = 0.0  # Σ(price² × volume)
        # Initial Balance tracker
        self._ib_tracker = InitialBalanceTracker()
        # Acceptance/Rejection engine
        self._ar_engine = AcceptanceRejectionEngine()
        # Previous CVD slope for delta-flip detection in LVN play
        self._prev_cvd_slope: float = 0.0
        # Previous market state for transition logging (FR-04-07)
        self._previous_state: MarketState | None = None
        # New modules (Phases 3-5)
        self._drive_tracker = DriveTracker()
        from app.domain.fabio_ai.services.orderflow_detectors import (
            BigTradeDetector,
            BubbleDetector,
            OFICalculator,
            AbsorptionDetector,
        )

        self._big_trade_detector = BigTradeDetector()
        self._bubble_detector = BubbleDetector()
        self._ofi_calculator = OFICalculator()
        self._absorption_detector = AbsorptionDetector()
        # Persistent aggression scorer (per-symbol config when available)
        if symbol_config:
            self._persistent_agg_scorer = PersistentAggressionScorer(
                persistence_bars=symbol_config.aggression_persistence_bars,
                min_score=symbol_config.min_aggression_score,
                pyramid_score=symbol_config.pyramid_aggression_score,
            )
        else:
            self._persistent_agg_scorer = PersistentAggressionScorer()
        # LVN persistence tracker (prevents LVN appearing/disappearing)
        self._lvn_tracker = LVNPersistenceTracker()

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
        for i in range(len(data) - 2, max(len(data) - 15, -1), -1):
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

        is_disp = self.detect_displacement(data)
        leg_profile = create_profile(leg_candles, buckets=200)
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
        target_volume = total_volume * 0.7
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

    def detect_displacement(self, data: list[OHLC]) -> bool:
        """Check for impulsive move: 3+ candles with direction + range expansion.

        Formula: N>=3 consecutive candles, (N-1)/N directional,
        total leg range >= 1.5 × avg_range × N, closes near extremes for 2/3.
        """
        if len(data) < 23:
            return False

        N = 3
        recent = data[-N:]

        # Direction check: at least (N-1) of N must be directional
        bullish_count = sum(1 for c in recent if c.close > c.open)
        bearish_count = sum(1 for c in recent if c.close < c.open)

        is_bullish = bullish_count >= N - 1
        is_bearish = bearish_count >= N - 1

        if not (is_bullish or is_bearish):
            return False

        # Range expansion: leg range >= 1.5 × avg_range × N
        prev_data = data[-(20 + N) : -N]
        if len(prev_data) < 10:
            return False

        avg_range = sum(d.high - d.low for d in prev_data) / len(prev_data)
        leg_range = max(c.high for c in recent) - min(c.low for c in recent)

        if leg_range < avg_range * AMTConfig.DISPLACEMENT_MULTIPLIER:
            return False

        # Efficiency check: closes near extremes for at least 2/3 of candles
        efficient_count = 0
        for c in recent:
            rng = c.high - c.low
            if rng == 0:
                efficient_count += 1
                continue
            if is_bullish and c.close >= c.low + 0.75 * rng:
                efficient_count += 1
            elif is_bearish and c.close <= c.low + 0.25 * rng:
                efficient_count += 1

        if efficient_count < math.ceil(N * 2 / 3):
            return False

        return True

    def detect_acceptance(self, data: list[OHLC], vah: float, val: float) -> bool:
        """Check for acceptance: 2+ consecutive closes outside VA."""
        if len(data) < 2:
            return False

        recent = data[-2:]

        # Check acceptance above VAH
        if all(c.close > vah for c in recent):
            return True

        # Check acceptance below VAL
        if all(c.close < val for c in recent):
            return True

        return False

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
    ) -> AMTResult:
        """Run the full AMT analysis pipeline."""
        empty = AMTResult(
            market_state=MarketState.BALANCED.value,
            poc=0,
            value_area_high=0,
            value_area_low=0,
        )

        if not data or len(data) < 5:
            return empty

        lookback = len(data)
        recent_data = data[-lookback:]
        current = data[-1]

        # 1. Volume Profile — use incremental if available, else full rebuild
        if incremental_profile is not None:
            profile = incremental_profile.get_profile()
        else:
            profile = create_profile(recent_data)
        if not profile:
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
        target_volume = total_volume * 0.7
        current_volume = max_vol
        up_idx, down_idx = poc_index, poc_index

        while current_volume < target_volume:
            # Sum the next TWO rows above (CME standard)
            up_pair = 0.0
            up_count = 0
            for k in range(1, 3):
                if up_idx + k < len(profile):
                    up_pair += profile[up_idx + k].volume
                    up_count += 1
            # Sum the next TWO rows below
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
                # Expand upward by up to 2 rows (tie: upward first per convention)
                for k in range(1, up_count + 1):
                    if up_idx + k < len(profile):
                        up_idx += 1  # Move index up
                        current_volume += profile[up_idx].volume
            elif can_go_down:
                # Expand downward by up to 2 rows
                for k in range(1, down_count + 1):
                    if down_idx - k >= 0:
                        down_idx -= 1  # Move index down
                        current_volume += profile[down_idx].volume

        # VAH = upper edge of top VA bin, VAL = lower edge of bottom VA bin
        step = profile[1].price - profile[0].price if len(profile) > 1 else 0
        half_step = step / 2
        vah = profile[up_idx].price + half_step  # upper edge
        val = profile[down_idx].price - half_step  # lower edge

        # Note: we no longer artificially expand VA width. A very tight VA
        # is valid market information (low volatility). Synthetic expansion was
        # creating false "near level" triggers in the Three-Align Gate.

        # LVN detection with persistence filter — prevents appearing/disappearing
        raw_lvns = find_lvns(profile, self.config)
        lvns = self._lvn_tracker.update(raw_lvns, profile)
        hvns = find_hvns(profile, self.config)
        # LVN/HVN detection complete
        # Incremental aggressive prints — only compute last candle if data grew by 1
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

        # Baseline volume for acceptance/rejection (mean of last 20 candles)
        baseline_vol = (
            sum(d.volume for d in recent_data[-20:]) / min(20, len(recent_data))
            if recent_data
            else 0.0
        )

        # Acceptance/Rejection engine
        ar_state = self._ar_engine.update(current, vah, val, baseline_vol)

        # 2. Market State (4-state model: NO_TRADE / BALANCED / IMBALANCED / PROBING)
        # Uses standalone detect_market_state() per FR-04
        leg_data = self.detect_displacement_leg(recent_data)
        has_displacement = leg_data["has_displacement"]
        has_acceptance = self.detect_acceptance(recent_data, vah, val)

        # Merge with AR engine state
        if ar_state["acceptance_above"] or ar_state["acceptance_below"]:
            has_acceptance = True

        # Balance ratio: fraction of recent candles inside VA
        balance_window = min(len(recent_data), 20)
        inside_count = sum(
            1 for d in recent_data[-balance_window:] if val <= d.close <= vah
        )
        balance_ratio = inside_count / balance_window if balance_window > 0 else 0.0

        # Compute tick_size from data (minimum price increment)
        prices = sorted(set(float(d.close) for d in recent_data[-50:]))
        tick_size = min(
            (
                prices[i + 1] - prices[i]
                for i in range(len(prices) - 1)
                if prices[i + 1] > prices[i]
            ),
            default=0.05,
        )

        # Detect market state using 4-state model
        state_result = detect_market_state(
            price=float(current.close),
            poc=poc,
            vah=vah,
            val=val,
            tick_size=tick_size,
            has_displacement=has_displacement,
            has_acceptance=has_acceptance,
            balance_ratio=balance_ratio,
        )
        market_state = state_result.state
        zone = state_result.zone

        # Log state transitions for audit trail (FR-04-07)
        log_state_transition(self._previous_state, market_state, state_result)
        self._previous_state = market_state

        # 3. Order Flow Detectors + Aggression Scoring (FR-03/06)
        # Compute average volume for detectors
        avg_candle_vol = (
            sum(float(d.volume) for d in recent_data) / len(recent_data)
            if recent_data
            else 0.0
        )

        # OBI from order book (kept for backward compat)
        obi = 0.0
        toxicity = 0.0
        if order_book:
            bids_q = sum(b.quantity for b in order_book.bids)
            asks_q = sum(a.quantity for a in order_book.asks)
            total = bids_q + asks_q
            if total > 0:
                obi = (bids_q - asks_q) / total
            if len(order_book.bids) >= 3 and len(order_book.asks) >= 3:
                top_bids_q = sum(b.quantity for b in order_book.bids[:3])
                top_asks_q = sum(a.quantity for a in order_book.asks[:3])
                top_total = top_bids_q + top_asks_q
                if top_total > 0:
                    top_obi = (top_bids_q - top_asks_q) / top_total
                    if abs(top_obi) > 0.7:
                        toxicity = top_obi

        norm_delta = current.delta / current.volume if current.volume > 0 else 0

        # FR-06-01: Footprint imbalance confirmed (≥40% cells at ≥3:1)
        # Two conditions must agree:
        #   1. Aggressive volume prints detected (institutional activity)
        #   2. Current candle has strong directional delta (|norm_delta| > 0.3)
        # This aligns the aggression signal with the tick-level footprint delta
        has_agg_prints = len(agg_prints) >= 2
        has_strong_delta = abs(norm_delta) > 0.30
        footprint_confirmed = has_agg_prints and has_strong_delta

        # FR-06-02: CVD slope/divergence confirms
        cvd_confirmed = False
        cvd_state = self._cvd_tracker.state()
        if market_state == MarketState.IMBALANCED and cvd_state.slope > 0:
            cvd_confirmed = True  # Buying pressure confirms uptrend
        elif market_state == MarketState.IMBALANCED and cvd_state.slope < 0:
            cvd_confirmed = True  # Selling pressure confirms downtrend
        elif cvd_state.has_divergence:
            cvd_confirmed = True  # Divergence is a signal

        # FR-06-03: Big trade cluster
        big_trade = self._big_trade_detector.detect(current, avg_candle_vol)
        big_trade_confirmed = big_trade is not None

        # FR-06-04: Absorption
        atr = (
            max(d.high for d in recent_data[-14:])
            - min(d.low for d in recent_data[-14:])
        ) / max(len(recent_data[-14:]), 1)
        absorption = self._absorption_detector.detect(current, atr, avg_candle_vol)
        absorption_detected = absorption.detected

        # FR-06-05: OFI aligned
        ofi_result = self._ofi_calculator.update(current)
        ofi_aligned = (ofi_result.ofi > 0.10) or (ofi_result.ofi < -0.10)

        # FR-06-06: Confluence (LVN near session VAH/VAL/POC)
        confluence_bonus = False
        for lvn in lvns:
            for level in [vah, val, poc]:
                if level > 0 and abs(lvn - level) < tick_size * 3:
                    confluence_bonus = True
                    break

        # FR-06-07: Volume bubble near entry
        bubble = self._bubble_detector.detect(current)
        volume_bubble_near = bubble.detected

        # Aggression scorer (FR-06 additive, max 4.5) — with persistence filter
        agg_result = self._persistent_agg_scorer.score(
            footprint_confirmed=footprint_confirmed,
            cvd_confirmed=cvd_confirmed,
            big_trade_confirmed=big_trade_confirmed,
            absorption_detected=absorption_detected,
            ofi_aligned=ofi_aligned,
            confluence_bonus=confluence_bonus,
            volume_bubble_near=volume_bubble_near,
        )
        aggression_score = agg_result.score
        has_aggression = agg_result.confirmed

        # Compute profile shape once and attach to result
        shape = classify_shape(profile)

        # Bimodal override: two-peaked profile = auction market, not trend.
        # A bimodal distribution means price is visiting two distinct value areas
        # with high volume each — signature of Balance, not Trend.
        if shape.shape == "B" and market_state == MarketState.IMBALANCED:
            market_state = MarketState.BALANCED

        # Session VWAP — rolling accumulator (resets on session boundary)
        # Approximate quote volume from candle: typical_price * volume
        typical_price = (current.high + current.low + current.close) / 3
        quote_vol = typical_price * current.volume if current.volume > 0 else 0.0

        # Detect session boundary: different date = new session
        _reset_session = False
        if self._vwap_last_time:
            try:
                prev_date = self._vwap_last_time[:10]  # "YYYY-MM-DD"
                curr_date = current.time[:10]
                if curr_date != prev_date:
                    _reset_session = True
            except (TypeError, IndexError):
                pass
            # Fallback: time going backwards still triggers reset
            if not _reset_session and current.time < self._vwap_last_time:
                _reset_session = True
        if _reset_session:
            self._vwap_cum_vol = 0.0
            self._vwap_cum_quote_vol = 0.0
            self._vwap_cum_sq_vol = 0.0
            self._ib_tracker.reset()
            self._ar_engine.reset()
            self._persistent_agg_scorer.reset()
            self._lvn_tracker.reset()
        self._vwap_last_time = current.time

        self._vwap_cum_vol += float(current.volume)
        self._vwap_cum_quote_vol += float(quote_vol)
        self._vwap_cum_sq_vol += float(typical_price * typical_price * current.volume)
        session_vwap = float(
            self._vwap_cum_quote_vol / self._vwap_cum_vol
            if self._vwap_cum_vol > 0
            else current.close
        )

        # VWAP standard deviation bands (±1σ, ±2σ)
        vwap_std = 0.0
        if self._vwap_cum_vol > 0:
            variance = (self._vwap_cum_sq_vol / self._vwap_cum_vol) - (
                session_vwap * session_vwap
            )
            vwap_std = math.sqrt(max(0.0, variance))
        vwap_upper_1 = session_vwap + vwap_std
        vwap_lower_1 = session_vwap - vwap_std
        vwap_upper_2 = session_vwap + 2 * vwap_std
        vwap_lower_2 = session_vwap - 2 * vwap_std

        # CVD — wire to live path for entry/exit decisions
        cvd_state = self._cvd_tracker.update(current)
        cvd_div = ""
        if cvd_state.has_divergence:
            cvd_div = cvd_state.divergence_type or ""

        # Market structure classification (5-state with hysteresis)
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

        # Cross-validation: PROBING market state is logically incompatible with
        # BALANCE structure. PROBING = testing outside value, BALANCE = rotation
        # inside value. If both fire, override structure to TRANSITION.
        if market_state == MarketState.PROBING and structure.state == "BALANCE":
            structure = type(structure)(
                state="TRANSITION",
                confidence_score=max(structure.confidence_score, 60),
                features=structure.features,
            )

        # Initial Balance tracking
        ib_high, ib_low, ib_complete = self._ib_tracker.update(current)

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

        # Break detection — initiative vs responsive at key levels
        break_state = detect_break(recent_data, vah, val, ib_high, ib_low, baseline_vol)

        # Developing VA — short-lookback profile for fast adaptation
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
                    # Quick 70% VA
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

        # Extract the current session's open price.
        # Find the first candle of the current date (used for gap and bias).
        current_date_prefix = current.time[:10] if len(current.time) >= 10 else ""
        session_open_price = current.open
        if current_date_prefix:
            for d in data:
                if d.time.startswith(current_date_prefix):
                    session_open_price = d.open
                    break
        else:
            session_open_price = data[0].open if data else 0.0

        # Day-Type Classification (Fabio Phase 3)
        day_type = "UNKNOWN"
        if ib_complete and ib_high > 0 and ib_low > 0:
            session_high = max(d.high for d in data)
            session_low = min(d.low for d in data)
            ib_range = ib_high - ib_low

            if ib_range > 0:
                dist_above = max(0.0, session_high - ib_high)
                dist_below = max(0.0, ib_low - session_low)

                if dist_above == 0 and dist_below == 0:
                    day_type = "NORMAL"
                elif dist_above > 0 and dist_below > 0:
                    day_type = "NEUTRAL"
                elif dist_above > ib_range or dist_below > ib_range:
                    day_type = "TREND"
                else:
                    day_type = "NORMAL_VARIATION"

        # NPOC (Naked POC) — check fills and get nearest targets
        npoc_above = 0.0
        npoc_below = 0.0
        if npoc_tracker is not None:
            # Check and fill NPOCs within 2 ticks of current price
            npoc_tracker.check_and_fill(
                underlying=underlying,
                current_price=float(current.close),
                tick_size=tick_size,
            )
            # Get nearest active NPOCs for secondary target calculation
            npoc_result = npoc_tracker.get_active_npocs(
                underlying=underlying,
                current_price=float(current.close),
            )
            if npoc_result.nearest_above:
                npoc_above = npoc_result.nearest_above.price
            if npoc_result.nearest_below:
                npoc_below = npoc_result.nearest_below.price

        # 4. Signal Generation — AFTER VWAP, CVD, structure, cross-validation
        signal = self._generate_signal(
            data,
            current,
            market_state,
            has_aggression,
            aggression_score,
            lvns,
            vah,
            val,
            poc,
            agg_result.direction_sign,
            agg_result.pyramid_eligible,
            session_vwap,
        )

        return AMTResult(
            market_state=market_state.value,
            poc=poc,
            value_area_high=vah,
            value_area_low=val,
            lvns=tuple(lvns),
            hvns=tuple(hvns),
            aggression=aggression_score,
            signal=signal,
            setup=signal.setup.value if signal else None,
            profile=tuple(profile),
            aggressive_prints=tuple(agg_prints),
            profile_shape=shape.shape,
            cvd_slope=cvd_state.slope,
            cvd_divergence=cvd_div,
            session_vwap=session_vwap,
            vwap_upper_1=vwap_upper_1,
            vwap_lower_1=vwap_lower_1,
            vwap_upper_2=vwap_upper_2,
            vwap_lower_2=vwap_lower_2,
            balance_ratio=balance_ratio,
            leg_profile=tuple(leg_data.get("profile", [])),
            leg_lvns=tuple(leg_data.get("lvns", [])),
            leg_poc=leg_data.get("poc", 0.0),
            leg_vah=leg_data.get("vah", 0.0),
            leg_val=leg_data.get("val", 0.0),
            swing_delta=leg_data.get("swing_delta", 0.0),
            has_displacement=leg_data.get("has_displacement", False),
            market_structure=structure.state,
            structure_confidence=structure.confidence_score,
            day_type=day_type,
            ib_high=ib_high,
            ib_low=ib_low if ib_low != float("inf") else 0.0,
            ib_complete=ib_complete,
            prior_poc=prior_poc,
            prior_vah=prior_vah,
            prior_val=prior_val,
            gap_type=(
                classify_gap(
                    open_price=session_open_price,
                    prior_close=prior_poc,  # Use POC as proxy for prior close
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
            ofi=obi,
            dev_poc=dev_poc,
            dev_vah=dev_vah,
            dev_val=dev_val,
            cushion_tier=cushion_tier,
            session_pnl=session_pnl,
            bubble_retests=bubble_retests,
            npoc_above=npoc_above,
            npoc_below=npoc_below,
        )

    def _generate_signal(
        self,
        data: list[OHLC],
        current: OHLC,
        market_state: MarketState,
        has_aggression: bool,
        aggression_score: float,
        lvns: list[float],
        vah: float,
        val: float,
        poc: float,
        aggression_direction: int = 0,
        has_high_aggression: bool = False,
        session_vwap: float = 0.0,
    ) -> Signal | None:
        """Generate direction signal from market microstructure.

        NOTE: SL/TP in this signal are PLACEHOLDERS (VA-based). The real SL/TP
        is computed by build_entry_signal() in entry_gate.py using the full
        Fabio playbook (aggressive print, VWAP, ATR floor, cushion override).
        This signal's only purpose: direction for fallback in LLM handler
        and serialization for UI display.
        """
        now_iso = current.time  # use tick timestamp, not wall clock

        # GATE 3: NO_TRADE state never generates signals
        if market_state == MarketState.NO_TRADE:
            return None

        # C. PROBING Playbook — unconfirmed break with high aggression
        # PROBING = price outside VA without displacement. Two scenarios:
        #   A. Acceptance: aggression confirms the break → continuation
        #   B. Rejection: opposing aggression → fade back into value
        # Requires pyramid_eligible (score ≥ 3.0 for 3 consecutive bars)
        # per requirement: "DeltaScore ≥ 3 for N consecutive bars"
        if market_state == MarketState.PROBING and has_high_aggression:
            above_vah = float(current.close) > vah
            below_val = float(current.close) < val
            above_vwap = (
                float(current.close) > session_vwap if session_vwap > 0 else True
            )
            below_vwap = (
                float(current.close) < session_vwap if session_vwap > 0 else True
            )

            if above_vah:
                # Scenario A: Acceptance above VAH — bullish continuation
                # VWAP context: price above VWAP confirms bullish institutional positioning
                if aggression_direction > 0 and above_vwap:
                    return Signal(
                        type=SignalType.BUY,
                        price=current.close,
                        reason="PROBING Acceptance: aggression confirms break above VAH (above VWAP)",
                        setup=SetupType.TREND_MODEL,
                        source=Source.AMT,
                        stop_loss=val,
                        take_profit=vah + (vah - val),
                        timestamp=now_iso,
                    )
                # Scenario B: Rejection above VAH — fade short
                # VWAP context: opposing aggression above VWAP = institutional absorption
                if aggression_direction < 0:
                    return Signal(
                        type=SignalType.SELL,
                        price=current.close,
                        reason="PROBING Rejection: opposing aggression at VAH (fade into value)",
                        setup=SetupType.MEAN_REVERSION,
                        source=Source.AMT,
                        stop_loss=vah + (vah - val) * 0.25,
                        take_profit=poc,
                        timestamp=now_iso,
                    )

            elif below_val:
                # Scenario A: Acceptance below VAL — bearish continuation
                # VWAP context: price below VWAP confirms bearish institutional positioning
                if aggression_direction < 0 and below_vwap:
                    return Signal(
                        type=SignalType.SELL,
                        price=current.close,
                        reason="PROBING Acceptance: aggression confirms break below VAL (below VWAP)",
                        setup=SetupType.TREND_MODEL,
                        source=Source.AMT,
                        stop_loss=vah,
                        take_profit=val - (vah - val),
                        timestamp=now_iso,
                    )
                # Scenario B: Rejection below VAL — fade long
                # VWAP context: opposing aggression below VWAP = institutional absorption
                if aggression_direction > 0:
                    return Signal(
                        type=SignalType.BUY,
                        price=current.close,
                        reason="PROBING Rejection: opposing aggression at VAL (fade into value)",
                        setup=SetupType.MEAN_REVERSION,
                        source=Source.AMT,
                        stop_loss=val - (vah - val) * 0.25,
                        take_profit=poc,
                        timestamp=now_iso,
                    )

        # A. Trend Continuation (Imbalanced + Pullback + LVN + Aggression)
        if market_state == MarketState.IMBALANCED and has_aggression:
            # Find nearest LVN
            nearby_lvn = next(
                (lvn for lvn in lvns if abs(current.close - lvn) / lvn < 0.003),
                None,
            )

            if nearby_lvn:
                # LONG: Trend is Up (VAH migration or simple price > POC), pullback to LVN
                # Logic: Price > POC generally, but we are testing an LVN.
                # Aggression must be BUYING.
                if current.close > poc and aggression_score > 0:
                    # Check if this is a pullback? (High > Current)
                    # For now, aggression at LVN in trend direction is the key.
                    return Signal(
                        type=SignalType.BUY,
                        price=current.close,
                        reason="Trend Continuation: Aggression at LVN",
                        setup=SetupType.TREND_MODEL,
                        source=Source.AMT,
                        stop_loss=val,  # Will be refined by TradingSession
                        take_profit=poc,  # Placeholder (TradingSession handles dynamic TP)
                        timestamp=now_iso,
                    )
                # SHORT: Trend is Down, pullback to LVN
                if current.close < poc and aggression_score < 0:
                    return Signal(
                        type=SignalType.SELL,
                        price=current.close,
                        reason="Trend Continuation: Aggression at LVN",
                        setup=SetupType.TREND_MODEL,
                        source=Source.AMT,
                        stop_loss=vah,
                        take_profit=poc,
                        timestamp=now_iso,
                    )

        # B. Mean Reversion (Balanced + Failed Breakout + Reclaim + Aggression)
        if market_state == MarketState.BALANCED and has_aggression and len(data) >= 5:
            # Check for failed breakout
            recent = data[-10:]  # Look further back for the breakout
            had_above = any(d.high > vah for d in recent[:-1])
            had_below = any(d.low < val for d in recent[:-1])

            # Current state: Inside VA
            is_inside = val <= current.close <= vah

            # Reclaim logic: We were OUT, now we are IN
            # (Simplified: if we had excursion and now aggressive inside)

            if is_inside:
                # Failed Low -> Buy Reclaim
                if had_below and aggression_score > 0 and current.close > val:
                    return Signal(
                        type=SignalType.BUY,
                        price=current.close,
                        reason="Mean Reversion: Confirmed Reclaim",
                        setup=SetupType.MEAN_REVERSION,
                        source=Source.AMT,
                        stop_loss=val * 0.999,
                        take_profit=poc,
                        timestamp=now_iso,
                    )
                # Failed High -> Sell Reclaim
                if had_above and aggression_score < 0 and current.close < vah:
                    return Signal(
                        type=SignalType.SELL,
                        price=current.close,
                        reason="Mean Reversion: Confirmed Reclaim",
                        setup=SetupType.MEAN_REVERSION,
                        source=Source.AMT,
                        stop_loss=vah * 1.001,
                        take_profit=poc,
                        timestamp=now_iso,
                    )

        return None

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
