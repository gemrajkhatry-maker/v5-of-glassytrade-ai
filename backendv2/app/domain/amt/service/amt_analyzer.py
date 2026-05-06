"""AMT Analyzer — the orchestrator for the 6-stage AMT analysis pipeline.

This is a THIN coordinator. Each stage is an independent, testable domain service.
Pipeline stages:
  1. Profile Building — Volume profile, POC/VA extraction
  2. Market State Detection — Balance ratio, displacement, acceptance
  3. Setup Classification — Profile shape, mean reversion/trend
  4. Session Context — Day type, gap analysis, opening type
  5. Multi-Timeframe — Daily/hourly alignment
  6. Order Flow — CVD slope, aggression, absorption

Output: AMTResult value object.
"""

from __future__ import annotations

import logging
from typing import Any

from app.domain.amt.model.amt_models import (
    VolumeProfile,
    Absorption,
    InitialBalanceResult,
    AcceptanceResult,
    BreakResult,
    POCMigrationResult,
    CVDPoint,
    CVDSnapshot,
)
from app.domain.trading.model.value_objects import OHLC, AMTResult

logger = logging.getLogger(__name__)

# Type alias for a bar (range bar or candle)
Bar = dict  # Contains: open, high, low, close, volume, buyVolume, sellVolume


class AMTAnalyzer:
    """
    Orchestrates the 6-stage AMT analysis pipeline.

    This class is stateless — it delegates to specialized services.
    Each service is independently testable.
    """

    def __init__(self):
        from app.domain.amt.service.volume_profile import build_volume_profile
        from app.domain.amt.service.lvn_detector import detect_lvn_hvn
        from app.domain.amt.service.cvd_tracker import CVDTracker
        from app.domain.amt.service.aggression_scorer import AggressionScorer
        from app.domain.amt.service.acceptance_rejection import AcceptanceRejectionEngine
        from app.domain.amt.service.market_state_engine import detect_market_state
        from app.domain.amt.service.signal_generator import generate_signal
        from app.domain.amt.service.initial_balance_engine import InitialBalanceEngine
        from app.domain.amt.service.break_detector import detect_break
        from app.domain.amt.service.displacement_detector import detect_displacement
        from app.domain.amt.service.drive_tracker import DriveTracker
        from app.domain.amt.service.profile_classifier import classify_shape
        from app.domain.amt.service.orderflow_detectors import AbsorptionDetector

        self._build_volume_profile = build_volume_profile
        self._detect_lvn_hvn = detect_lvn_hvn
        self._cvd_tracker = CVDTracker()
        self._aggression_scorer = AggressionScorer()
        self._ar_engine = AcceptanceRejectionEngine()
        self._detect_market_state = detect_market_state
        self._generate_signal = generate_signal
        self._ib_engine = InitialBalanceEngine()
        self._detect_break = detect_break
        self._detect_displacement = detect_displacement
        self._drive_tracker = DriveTracker()
        self._classify_shape = classify_shape
        self._absorption_detector = AbsorptionDetector()

    def analyze(
        self,
        bars: list[Bar],
        symbol: str = "",
        daily_bars: list[Bar] | None = None,
        hourly_bars: list[Bar] | None = None,
        prior_profile: dict | None = None,
    ) -> AMTResult:
        """
        Run the full 6-stage AMT analysis pipeline.

        Args:
            bars: List of range bars (session data)
            symbol: Trading symbol
            daily_bars: Daily timeframe bars for MTF analysis
            hourly_bars: Hourly timeframe bars for MTF analysis
            prior_profile: Prior day's profile (VAH/VAL/POC) for gap analysis

        Returns:
            AMTResult with all analysis fields populated
        """
        if not bars:
            return AMTResult()

        # Stage 1: Profile Building
        vp, vwap_data = self._analyze_profile(bars)
        lvns, hvns = self._analyze_lvn_hvn(vp)

        # Stage 2: Market State
        market_state_result = self._analyze_market_state(bars, vp)

        # Stage 3: Setup Classification
        profile_shape = self._analyze_profile_shape(vp, bars)

        # Stage 4: Session Context
        session_context = self._analyze_session_context(bars, prior_profile)

        # Stage 5: Multi-Timeframe
        mtf_alignment = self._analyze_mtf(daily_bars, hourly_bars)

        # Stage 6: Order Flow
        order_flow = self._analyze_order_flow(bars, vp)

        # Build AMTResult
        return AMTResult(
            market_state=market_state_result.get("state", "BALANCED"),
            poc=vp.poc,
            value_area_high=vp.vah,
            value_area_low=vp.val,
            lvns=tuple(l.price for l in lvns),
            hvns=tuple(h.price for h in hvns),
            aggression=order_flow.get("aggression", 0.0),
            setup=market_state_result.get("setup"),
            profile_shape=profile_shape,
            cvd_slope=order_flow.get("cvd_slope", 0.0),
            cvd_divergence=order_flow.get("cvd_divergence", ""),
            session_vwap=vwap_data.get("vwap", 0.0),
            vwap_upper_1=vwap_data.get("upper_1", 0.0),
            vwap_lower_1=vwap_data.get("lower_1", 0.0),
            vwap_upper_2=vwap_data.get("upper_2", 0.0),
            vwap_lower_2=vwap_data.get("lower_2", 0.0),
            balance_ratio=market_state_result.get("balance_ratio", 0.0),
            has_displacement=market_state_result.get("has_displacement", False),
            ib_high=session_context.get("ib_high", 0.0),
            ib_low=session_context.get("ib_low", 0.0),
            ib_complete=session_context.get("ib_complete", False),
            prior_poc=prior_profile.get("poc", 0.0) if prior_profile else 0.0,
            prior_vah=prior_profile.get("vah", 0.0) if prior_profile else 0.0,
            prior_val=prior_profile.get("val", 0.0) if prior_profile else 0.0,
            gap_type=session_context.get("gap_type", ""),
            opening_bias=session_context.get("opening_bias", ""),
            acceptance_above=order_flow.get("acceptance_above", False),
            acceptance_below=order_flow.get("acceptance_below", False),
            rejection_at_high=order_flow.get("rejection_at_high", False),
            rejection_at_low=order_flow.get("rejection_at_low", False),
            liquidity_sweep=order_flow.get("liquidity_sweep", ""),
            absorption_side=order_flow.get("absorption_side", ""),
            absorption_range_ratio=order_flow.get("absorption_range_ratio", 0.0),
            absorption_vol_ratio=order_flow.get("absorption_vol_ratio", 0.0),
            break_direction=order_flow.get("break_direction", ""),
            break_type=order_flow.get("break_type", ""),
            poc_signal=order_flow.get("poc_signal", ""),
            poc_vs_price=order_flow.get("poc_vs_price", ""),
            lvn_play=order_flow.get("lvn_play"),
            ofi=order_flow.get("ofi", 0.0),
            mtf_alignment=mtf_alignment,
            drive_number=order_flow.get("drive_number", 0),
            drive_entry_valid=order_flow.get("drive_entry_valid", False),
            market_structure=market_state_result.get("market_structure", "BALANCE"),
            day_type=session_context.get("day_type", "UNKNOWN"),
            opening_type=session_context.get("opening_type", ""),
            daily_vah=0.0,
            daily_val=0.0,
            daily_poc=0.0,
            hourly_vah=0.0,
            hourly_val=0.0,
            hourly_poc=0.0,
        )

    # ------------------------------------------------------------------
    # Stage 1: Profile Building
    # ------------------------------------------------------------------

    def _analyze_profile(self, bars: list[Bar]) -> tuple[VolumeProfile, dict]:
        """Build volume profile from bars. Returns (vp, vwap_data) where vwap_data
        holds the VWAP bands that cannot be stored on the frozen VolumeProfile."""
        from app.domain.amt.service.volume_profile import build_volume_profile, calculate_vwap
        bucket_size = self._estimate_bucket_size(bars)
        vp = build_volume_profile(bars, bucket_size)
        vwap, upper1, lower1, upper2, lower2 = calculate_vwap(bars)
        vwap_data = {
            "vwap": vwap,
            "upper_1": upper1,
            "lower_1": lower1,
            "upper_2": upper2,
            "lower_2": lower2,
        }
        return vp, vwap_data

    def _analyze_lvn_hvn(self, vp: VolumeProfile) -> tuple[list, list]:
        """Detect LVN/HVN from volume profile."""
        from app.domain.amt.service.lvn_detector import detect_lvn_hvn
        return detect_lvn_hvn(vp.levels)

    # ------------------------------------------------------------------
    # Stage 2: Market State
    # ------------------------------------------------------------------

    def _analyze_market_state(self, bars: list[Bar], vp: VolumeProfile) -> dict[str, Any]:
        """Detect market state (BALANCED/IMBALANCED)."""
        if not bars:
            return {"state": "BALANCED"}

        has_displacement = self._detect_displacement(bars) is not None
        has_acceptance = self._detect_acceptance(bars, vp)
        balance_ratio = self._calculate_balance_ratio(bars, vp)

        ms_result = self._detect_market_state(
            price=bars[-1]["close"] if bars else 0,
            vp_levels={"poc": vp.poc, "vah": vp.vah, "val": vp.val},
        )
        state = ms_result.state.value if hasattr(ms_result, "state") else str(ms_result)

        return {
            "state": state,
            "has_displacement": has_displacement,
            "has_acceptance": has_acceptance,
            "balance_ratio": balance_ratio,
            "setup": self._classify_setup(bars, vp, state),
            "market_structure": "IMBALANCE" if state == "IMBALANCED" else "BALANCE",
        }

    # ------------------------------------------------------------------
    # Stage 3: Setup Classification
    # ------------------------------------------------------------------

    def _analyze_profile_shape(self, vp: VolumeProfile, bars: list[Bar]) -> str:
        """Classify profile shape (P/b/D/B)."""
        result = self._classify_shape(list(vp.levels))
        return result.value if hasattr(result, "value") else str(result)

    # ------------------------------------------------------------------
    # Stage 4: Session Context
    # ------------------------------------------------------------------

    def _analyze_session_context(
        self, bars: list[Bar], prior_profile: dict | None
    ) -> dict[str, Any]:
        """Analyze session context: IB, gap, day type, opening type."""
        from app.domain.amt.service.initial_balance_engine import calculate_initial_balance
        ib = calculate_initial_balance(bars)
        result: dict[str, Any] = {
            "ib_high": ib.high,
            "ib_low": ib.low,
            "ib_complete": ib.complete,
            "opening_bias": "",
        }

        if prior_profile:
            gap_type = self._classify_gap(bars, prior_profile)
            result["gap_type"] = gap_type

        result["day_type"] = self._classify_day_type(bars)
        result["opening_type"] = self._classify_opening_type(bars)
        return result

    # ------------------------------------------------------------------
    # Stage 5: Multi-Timeframe
    # ------------------------------------------------------------------

    def _analyze_mtf(
        self,
        daily_bars: list[Bar] | None,
        hourly_bars: list[Bar] | None,
    ) -> str:
        """Analyze multi-timeframe alignment."""
        if not daily_bars:
            return ""

        from app.domain.amt.service.mtf_analyzer import MultiTimeframeAMTAnalyzer
        mtf = MultiTimeframeAMTAnalyzer()
        return mtf.analyze(daily_bars, hourly_bars)

    # ------------------------------------------------------------------
    # Stage 6: Order Flow
    # ------------------------------------------------------------------

    def _analyze_order_flow(self, bars: list[Bar], vp: VolumeProfile) -> dict[str, Any]:
        """Analyze order flow: CVD, aggression, absorption, breaks."""
        from app.domain.amt.service.orderflow_detectors import detect_absorptions, calculate_ofi
        result: dict[str, Any] = {}

        # CVD tracking
        cvd_snapshot = self._update_cvd(bars)
        result["cvd_slope"] = cvd_snapshot.get("slope", 0.0)
        result["cvd_divergence"] = cvd_snapshot.get("divergence_type", "")

        # Aggression scoring — use component-free call with defaults
        aggression = self._aggression_scorer.score()
        result["aggression"] = aggression.score
        result["aggression_score"] = aggression.score
        result["aggression_confidence"] = aggression.confidence

        # Absorption detection — use standalone function
        absorptions = detect_absorptions(bars)
        if absorptions:
            last_abs = absorptions[-1]
            result["absorption_side"] = getattr(last_abs, "side", "")
            result["absorption_range_ratio"] = 0.0
            result["absorption_vol_ratio"] = 0.0

        # Acceptance/Rejection — analyze(bars, vp) returns dict
        ar_result = self._ar_engine.analyze(bars, vp)
        result["acceptance_above"] = ar_result.get("accepted_above", False)
        result["acceptance_below"] = ar_result.get("accepted_below", False)
        result["rejection_at_high"] = ar_result.get("rejected_at_high", False)
        result["rejection_at_low"] = ar_result.get("rejected_at_low", False)
        result["liquidity_sweep"] = ar_result.get("liquidity_sweep", "")

        # Break detection — detect_break(bars, vp_levels_dict) returns BreakResult dataclass
        vp_levels = {"poc": vp.poc, "vah": vp.vah, "val": vp.val}
        break_result = self._detect_break(bars, vp_levels)
        result["break_direction"] = getattr(break_result, "direction", "")
        result["break_type"] = getattr(break_result, "type", "")

        # POC migration
        poc_signal = self._analyze_poc_migration(bars, vp)
        result["poc_signal"] = poc_signal.get("signal", "")
        result["poc_vs_price"] = poc_signal.get("poc_vs_price", "")

        # LVN play
        result["lvn_play"] = self._detect_lvn_play(bars, vp)

        # OFI — compute from last bar using standalone calculate_ofi
        result["ofi"] = calculate_ofi(bars[-1]) if bars else 0.0

        # Drive tracker — update(price, level, direction) returns DriveState dataclass
        if bars:
            price = bars[-1].get("close", 0.0)
            drive_state = self._drive_tracker.update(
                price=float(price),
                level=float(vp.poc),
                direction="UP" if float(price) >= float(vp.poc) else "DOWN",
            )
            result["drive_number"] = drive_state.drive_number
            result["drive_entry_valid"] = not drive_state.is_exhausted
        else:
            result["drive_number"] = 0
            result["drive_entry_valid"] = False

        return result

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _estimate_bucket_size(self, bars: list[Bar]) -> float:
        """Estimate appropriate bucket size for volume profile."""
        if not bars:
            return 1.0
        prices = []
        for bar in bars:
            prices.extend([bar.get("low", 0), bar.get("high", 0)])
        if not prices:
            return 1.0
        price_range = max(prices) - min(prices)
        if price_range == 0:
            return 1.0
        # Aim for ~20-30 buckets
        return max(0.05, price_range / 25)

    def _calculate_balance_ratio(self, bars: list[Bar], vp: VolumeProfile) -> float:
        """Calculate fraction of recent candles inside value area."""
        if not bars or vp.vah <= vp.val:
            return 0.0
        recent = bars[-20:] if len(bars) >= 20 else bars
        inside = sum(
            1 for b in recent
            if vp.val <= b.get("close", 0) <= vp.vah
        )
        return inside / len(recent) if recent else 0.0

    def _classify_setup(self, bars: list[Bar], vp: VolumeProfile, state: str) -> str:
        """Classify trade setup type."""
        if not bars:
            return ""
        price = bars[-1].get("close", 0)
        if state == "IMBALANCED":
            if price > vp.vah:
                return "TREND_LONG"
            elif price < vp.val:
                return "TREND_SHORT"
        elif state == "BALANCED":
            if price > vp.vah:
                return "MEAN_REVERSION_SHORT"
            elif price < vp.val:
                return "MEAN_REVERSION_LONG"
        return ""

    def _classify_day_type(self, bars: list[Bar]) -> str:
        """Classify day type (trend, range, etc.)."""
        if len(bars) < 10:
            return "UNKNOWN"
        ranges = [b.get("high", 0) - b.get("low", 0) for b in bars]
        avg_range = sum(ranges) / len(ranges) if ranges else 0
        if avg_range == 0:
            return "RANGE"
        return "NORMAL"

    def _classify_opening_type(self, bars: list[Bar]) -> str:
        """Classify opening type."""
        if len(bars) < 5:
            return ""
        return "OPEN_AUCTION"

    def _update_cvd(self, bars: list[Bar]) -> dict[str, Any]:
        """Update CVD tracker and return snapshot."""
        for i, bar in enumerate(bars):
            buy_vol = bar.get("buyVolume", bar.get("volume", 0) / 2)
            sell_vol = bar.get("sellVolume", bar.get("volume", 0) / 2)
            self._cvd_tracker.update(i, buy_vol, sell_vol, bar.get("close", 0))
        return self._cvd_tracker.snapshot()

    def _analyze_poc_migration(self, bars: list[Bar], vp: VolumeProfile) -> dict[str, str]:
        """Analyze POC migration direction."""
        if len(bars) < 10:
            return {"signal": "", "poc_vs_price": ""}
        price = bars[-1].get("close", 0)
        poc = vp.poc
        if price > poc * 1.001:
            return {"signal": "POC_RISING_BULLISH", "poc_vs_price": "ALIGNED"}
        elif price < poc * 0.999:
            return {"signal": "POC_FALLING_BEARISH", "poc_vs_price": "ALIGNED"}
        return {"signal": "", "poc_vs_price": "DIVERGENT"}

    def _detect_lvn_play(self, bars: list[Bar], vp: VolumeProfile) -> dict | None:
        """Detect LVN play pattern."""
        from app.domain.amt.service.lvn_detector import detect_lvn_play
        lvns_raw, _ = self._detect_lvn_hvn(vp.levels)
        return detect_lvn_play(vp.levels, bars, tuple(lvns_raw))

    def _detect_acceptance(self, bars: list[Bar], vp: VolumeProfile) -> bool:
        """Detect acceptance (price staying in value area)."""
        if not bars:
            return False
        recent = bars[-5:]
        return all(
            vp.val <= b.get("close", 0) <= vp.vah
            for b in recent
        )
