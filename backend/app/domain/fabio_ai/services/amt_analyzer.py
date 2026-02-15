"""AMT Analyzer — Auction Market Theory analysis domain service.

Pure domain logic: volume profile construction, LVN/HVN detection,
market state assessment, and aggression scoring.  Signal generation is
delegated to the SignalGenerator service to honour SRP.

Enhanced with Valentini AMT features: 2.5σ aggression filter,
CVD tracking, profile shape classification, and session context.
"""

from __future__ import annotations

import math

from app.domain.trading.models.enums import MarketState, SignalType, Source, SetupType
from app.domain.trading.models.value_objects import (
    OHLC, OrderBook, VolumeProfileLevel, AggressivePrint, AMTResult,
)
from app.domain.fabio_ai.models.observation import AMTObservation
from app.domain.trading.models.entities import Signal
from app.domain.fabio_ai.services.cvd_tracker import CVDTracker
from app.domain.fabio_ai.services.profile_classifier import (
    classify_shape, POCMigrationTracker,
)
from app.domain.fabio_ai.services.session_context import get_session_info


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class AMTConfig:
    LVN_SMOOTHING: int = 3
    LVN_PROMINENCE: float = 0.85
    OBI_THRESHOLD: float = 0.25
    DELTA_THRESHOLD: float = 0.3
    ABSORPTION_THRESHOLD: float = 0.3
    STOP_BUFFER: float = 0.001
    BUBBLE_VOL_MULTIPLIER: float = 1.5
    AGGRESSION_SIGMA_THRESHOLD: float = 2.5  # Valentini: require 2.5σ spike


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def smooth_array(data: list[float], window: int) -> list[float]:
    """Centered simple moving average smoothing."""
    smoothed: list[float] = []
    offset = window // 2
    for i in range(len(data)):
        total = 0.0
        count = 0
        for j in range(i - offset, i + offset + 1):
            if 0 <= j < len(data):
                total += data[j]
                count += 1
        smoothed.append(total / count if count else 0.0)
    return smoothed


def create_profile(data: list[OHLC], buckets: int = 100) -> list[VolumeProfileLevel]:
    """Build a volume profile from OHLCV data."""
    if not data:
        return []

    min_price = min(d.low for d in data)
    max_price = max(d.high for d in data)

    buffer = (max_price - min_price) * 0.01
    min_price -= buffer
    max_price += buffer
    price_range = max_price - min_price

    if price_range == 0:
        total_vol = sum(d.volume for d in data)
        return [
            VolumeProfileLevel(price=min_price, volume=total_vol / buckets)
            for _ in range(buckets)
        ]

    step = price_range / buckets
    profile = [
        VolumeProfileLevel(price=min_price + (i * step) + (step / 2))
        for i in range(buckets)
    ]

    for d in data:
        start_bucket = int((d.low - min_price) / step)
        end_bucket = int((d.high - min_price) / step)
        start_bucket = max(0, min(buckets - 1, start_bucket))
        end_bucket = max(0, min(buckets - 1, end_bucket))

        buckets_covered = max(1, end_bucket - start_bucket + 1)
        vol_per_bucket = d.volume / buckets_covered
        buy_ratio = d.taker_buy_volume / d.volume if d.volume > 0 else 0.5
        buy_vol = vol_per_bucket * buy_ratio
        sell_vol = vol_per_bucket * (1 - buy_ratio)

        for i in range(start_bucket, end_bucket + 1):
            profile[i].volume += vol_per_bucket
            profile[i].buy_volume += buy_vol
            profile[i].sell_volume += sell_vol

    return profile


def find_lvns(profile: list[VolumeProfileLevel], cfg: AMTConfig | None = None) -> list[float]:
    """Detect Low Volume Nodes."""
    cfg = cfg or AMTConfig()
    raw = [p.volume for p in profile]
    smoothed = smooth_array(raw, cfg.LVN_SMOOTHING)
    lvns: list[float] = []

    for i in range(3, len(smoothed) - 3):
        if smoothed[i] <= smoothed[i - 1] and smoothed[i] <= smoothed[i + 1]:
            left_peak, l = smoothed[i], i
            while l > 0 and smoothed[l - 1] >= smoothed[l]:
                l -= 1
                left_peak = smoothed[l]
            right_peak, r = smoothed[i], i
            while r < len(smoothed) - 1 and smoothed[r + 1] >= smoothed[r]:
                r += 1
                right_peak = smoothed[r]

            lower_peak = min(left_peak, right_peak)
            if profile[i].volume < lower_peak * cfg.LVN_PROMINENCE:
                lvns.append(profile[i].price)
    return lvns


def find_hvns(profile: list[VolumeProfileLevel], cfg: AMTConfig | None = None) -> list[float]:
    """Detect High Volume Nodes."""
    cfg = cfg or AMTConfig()
    raw = [p.volume for p in profile]
    smoothed = smooth_array(raw, cfg.LVN_SMOOTHING)
    hvns: list[float] = []

    for i in range(2, len(smoothed) - 2):
        if smoothed[i] >= smoothed[i - 1] and smoothed[i] >= smoothed[i + 1]:
            max_vol = max(smoothed)
            if smoothed[i] > max_vol * 0.4:
                hvns.append(profile[i].price)
    return hvns


def compute_aggression_sigma(candle: OHLC, data: list[OHLC]) -> float:
    """Compute how many standard deviations the candle's volume is above mean.

    Returns the z-score (sigma units). A value >= 2.5 is a Valentini
    'Big Trade Bubble' event.
    """
    if len(data) < 10 or candle.volume == 0:
        return 0.0
    volumes = [d.volume for d in data]
    n = len(volumes)
    mean = sum(volumes) / n
    variance = sum((v - mean) ** 2 for v in volumes) / n
    std = math.sqrt(variance) if variance > 0 else 1.0
    return (candle.volume - mean) / std if std > 0 else 0.0


def find_aggressive_prints(
    data: list[OHLC], cfg: AMTConfig | None = None
) -> list[AggressivePrint]:
    """Detect aggressive buying/selling 'volume bubbles' using 2.5σ filter.

    A print is aggressive when:
    1. Volume exceeds 2.5 standard deviations above the rolling mean, AND
    2. Delta directionality is at least 15% of total volume.
    """
    cfg = cfg or AMTConfig()
    if len(data) < 20:
        return []

    prints: list[AggressivePrint] = []
    for i, d in enumerate(data):
        lookback = data[max(0, i - 50):i] if i > 10 else data[:i]
        if len(lookback) < 10:
            continue
        sigma = compute_aggression_sigma(d, lookback)
        if sigma >= cfg.AGGRESSION_SIGMA_THRESHOLD:
            delta_ratio = abs(d.delta) / d.volume if d.volume > 0 else 0
            if delta_ratio > 0.15:
                prints.append(AggressivePrint(
                    price=d.close, time=d.time, volume=d.volume,
                    delta=d.delta, side="BUY" if d.delta > 0 else "SELL",
                ))
    return prints


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

    def __init__(self, config: AMTConfig | None = None) -> None:
        self.config = config or AMTConfig()
        self._cvd_tracker = CVDTracker()
        self._poc_tracker = POCMigrationTracker()

    def detect_displacement(self, data: list[OHLC]) -> bool:
        """Check for impulsive move: 3+ directional candles + range expansion."""
        if len(data) < 20:
            return False

        # Look at last 3 candles
        recent = data[-3:]
        if len(recent) < 3:
            return False

        # Direction check
        is_bullish = all(c.close > c.open for c in recent)
        is_bearish = all(c.close < c.open for c in recent)

        if not (is_bullish or is_bearish):
            return False

        # Range expansion check
        # Calculate avg range of previous 20 candles (excluding current leg)
        prev_data = data[-23:-3]
        if not prev_data:
            return False
        
        avg_range = sum(d.high - d.low for d in prev_data) / len(prev_data)
        current_leg_range = max(c.high for c in recent) - min(c.low for c in recent)

        if current_leg_range < (avg_range * 1.5):
            return False

        # Efficiency check (closes near extremes)
        # For bullish: close near high; For bearish: close near low
        for c in recent:
            rng = c.high - c.low
            if rng == 0: continue
            if is_bullish and (c.high - c.close) / rng > 0.25: # Close in top 25%
                return False
            if is_bearish and (c.close - c.low) / rng > 0.25: # Close in bottom 25%
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
        self, data: list[OHLC], order_book: OrderBook | None = None
    ) -> AMTResult:
        """Run the full AMT analysis pipeline."""
        empty = AMTResult(
            market_state=MarketState.BALANCED.value,
            poc=0, value_area_high=0, value_area_low=0,
        )

        if not data or len(data) < 5:
            return empty

        lookback = min(len(data), 500)
        recent_data = data[-lookback:]
        current = data[-1]

        # 1. Volume Profile
        profile = create_profile(recent_data)
        if not profile:
            return empty

        # POC
        max_vol, poc_index = 0.0, 0
        for i, level in enumerate(profile):
            if level.volume > max_vol:
                max_vol = level.volume
                poc_index = i
        poc = profile[poc_index].price

        # Value Area (70%)
        total_volume = sum(p.volume for p in profile)
        target_volume = total_volume * 0.7
        current_volume = max_vol
        up_idx, down_idx = poc_index, poc_index

        while current_volume < target_volume:
            up_vol = profile[up_idx + 1].volume if up_idx < len(profile) - 1 else 0
            down_vol = profile[down_idx - 1].volume if down_idx > 0 else 0
            if up_vol >= down_vol and up_idx < len(profile) - 1:
                up_idx += 1
                current_volume += profile[up_idx].volume
            elif down_idx > 0:
                down_idx -= 1
                current_volume += profile[down_idx].volume
            else:
                break

        vah = profile[up_idx].price
        val = profile[down_idx].price

        # Enforce minimum VA width (0.3% of POC) to prevent
        # collapsed VA ranges from very tight intraday sessions
        min_va_width = poc * 0.003
        if (vah - val) < min_va_width:
            half_expand = (min_va_width - (vah - val)) / 2
            vah += half_expand
            val -= half_expand

        lvns = find_lvns(profile, self.config)
        hvns = find_hvns(profile, self.config)
        agg_prints = find_aggressive_prints(recent_data, self.config)

        # 2. Market State (Fabio Playbook Rule: Displacement + Acceptance)
        # Default to Balanced
        market_state = MarketState.BALANCED
        
        has_displacement = self.detect_displacement(recent_data)
        has_acceptance = self.detect_acceptance(recent_data, vah, val)
        
        if has_displacement and has_acceptance:
            market_state = MarketState.IMBALANCED
        
        # If price is strictly inside VA, force Balanced (override previous logic if needed, 
        # but displacement+acceptance usually implies being outside)
        is_inside_va = val <= current.close <= vah
        if is_inside_va:
            market_state = MarketState.BALANCED

        # 3. Aggression
        obi = 0.0
        if order_book:
            bids_q = sum(b.quantity for b in order_book.bids)
            asks_q = sum(a.quantity for a in order_book.asks)
            total = bids_q + asks_q
            if total > 0:
                obi = (bids_q - asks_q) / total

        norm_delta = current.delta / current.volume if current.volume > 0 else 0
        obi_agg = abs(obi) > self.config.OBI_THRESHOLD
        delta_agg = abs(norm_delta) > self.config.DELTA_THRESHOLD

        candle_range = max(current.high - current.low, current.close * 0.0001)
        body_size = abs(current.close - current.open)
        price_flat = (body_size / candle_range) < 0.3

        bullish_abs = norm_delta > self.config.ABSORPTION_THRESHOLD and price_flat
        bearish_abs = norm_delta < -self.config.ABSORPTION_THRESHOLD and price_flat
        is_absorption = bullish_abs or bearish_abs
        has_aggression = obi_agg or delta_agg or is_absorption

        aggression_score = 0.0
        if has_aggression:
            direction = 1 if (obi > 0 or norm_delta > 0) else -1
            aggression_score = direction * max(
                abs(obi), abs(norm_delta), 0.5 if is_absorption else 0,
            )

        # 4. Signal Generation
        signal = self._generate_signal(
            data, current, market_state, has_aggression, aggression_score,
            lvns, vah, val, poc,
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
    ) -> Signal | None:
        """Generate a trade signal from current market microstructure."""
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat()

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
                        type=SignalType.BUY, price=current.close,
                        reason="Trend Continuation: Aggression at LVN",
                        setup=SetupType.TREND_MODEL, source=Source.AMT,
                        stop_loss=val, # Will be refined by TradingSession
                        take_profit=poc, # Placeholder (TradingSession handles dynamic TP)
                        timestamp=now_iso,
                    )
                # SHORT: Trend is Down, pullback to LVN
                if current.close < poc and aggression_score < 0:
                     return Signal(
                        type=SignalType.SELL, price=current.close,
                        reason="Trend Continuation: Aggression at LVN",
                        setup=SetupType.TREND_MODEL, source=Source.AMT,
                        stop_loss=vah,
                        take_profit=poc,
                        timestamp=now_iso,
                    )

        # B. Mean Reversion (Balanced + Failed Breakout + Reclaim + Aggression)
        if market_state == MarketState.BALANCED and has_aggression and len(data) >= 5:
            # Check for failed breakout
            recent = data[-10:] # Look further back for the breakout
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
                        type=SignalType.BUY, price=current.close,
                        reason="Mean Reversion: Confirmed Reclaim",
                        setup=SetupType.MEAN_REVERSION, source=Source.AMT,
                        stop_loss=val * 0.999,
                        take_profit=poc,
                        timestamp=now_iso,
                    )
                # Failed High -> Sell Reclaim
                if had_above and aggression_score < 0 and current.close < vah:
                    return Signal(
                        type=SignalType.SELL, price=current.close,
                        reason="Mean Reversion: Confirmed Reclaim",
                        setup=SetupType.MEAN_REVERSION, source=Source.AMT,
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
        current = data[-1] if data else OHLC(time="", open=0, high=0, low=0, close=0, volume=0)

        # --- CVD ---
        cvd_state = self._cvd_tracker.update(current)

        # --- Profile shape ---
        shape = classify_shape(list(result.profile))

        # --- POC migration ---
        poc_mig = self._poc_tracker.update(result.poc)

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
        agg_sigma = compute_aggression_sigma(current, data[-50:]) if len(data) >= 20 else 0.0

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
