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

from app.domain.fabio_ai.services import mlx_compute as mc

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
from app.domain.fabio_ai.services.market_structure_classifier import MarketStructureClassifier
from app.domain.fabio_ai.services.session_context import (
    classify_gap, get_session_info, opening_inventory_bias,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class AMTConfig:
    LVN_THRESHOLD: float = 0.40   # LVN: bins < 40% of mean volume (formula: 0.3–0.5)
    LVN_SMOOTHING: int = 3        # Smooth histogram before LVN/HVN detection
    OBI_THRESHOLD: float = 0.25
    DELTA_THRESHOLD: float = 0.3
    ABSORPTION_THRESHOLD: float = 0.3
    STOP_BUFFER: float = 0.001
    BUBBLE_VOL_MULTIPLIER: float = 1.5
    AGGRESSION_SIGMA_THRESHOLD: float = 2.5  # Valentini: require 2.5σ spike
    AGGRESSION_EMA_PERIOD: int = 20  # EMA period for dynamic volume threshold
    DELTA_DIRECTIONALITY_THRESHOLD: float = 0.40  # Professional: 40-50% delta ratio
    HVN_THRESHOLD: float = 0.40   # HVN: bins > 40% of max volume (formula: 0.3–0.5)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def smooth_array(data: list[float], window: int) -> list[float]:
    """Centered simple moving average smoothing (MLX-accelerated)."""
    return mc.smooth_array(data, window)


def create_profile(data: list[OHLC], buckets: int = 100) -> list[VolumeProfileLevel]:
    """Build a volume profile from OHLCV data using Gaussian-weighted distribution.

    Volume is distributed with a Gaussian centered on each candle's VWAP (or
    close if VWAP unavailable).  This concentrates volume where actual trading
    occurred rather than smearing it uniformly across the high-low range.
    """
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
        avg_price = data[0].close
        return [
            VolumeProfileLevel(price=avg_price, volume=total_vol)
        ]

    step = price_range / buckets
    profile = [
        VolumeProfileLevel(price=min_price + (i * step) + (step / 2))
        for i in range(buckets)
    ]

    for d in data:
        if d.volume <= 0:
            continue

        start_bucket = int((d.low - min_price) / step)
        end_bucket = int((d.high - min_price) / step)
        start_bucket = max(0, min(buckets - 1, start_bucket))
        end_bucket = max(0, min(buckets - 1, end_bucket))

        buy_ratio = d.taker_buy_volume / d.volume if d.volume > 0 else 0.5

        # Center of distribution: VWAP if available, else close
        center = d.vwap if d.vwap > 0 else d.close
        # Sigma = ~25% of candle range (concentrates ~95% within the range)
        candle_range = d.high - d.low
        sigma = max(candle_range * 0.25, step * 0.5)  # floor at half a bucket

        # Compute Gaussian weights (MLX-accelerated)
        bucket_centers = [profile[i].price for i in range(start_bucket, end_bucket + 1)]
        weights = mc.gaussian_weights(bucket_centers, center, sigma)

        for idx, i in enumerate(range(start_bucket, end_bucket + 1)):
            vol = d.volume * weights[idx]
            profile[i].volume += vol
            profile[i].buy_volume += vol * buy_ratio
            profile[i].sell_volume += vol * (1 - buy_ratio)

    return profile


# ---------------------------------------------------------------------------
# Incremental Volume Profile
# ---------------------------------------------------------------------------

class IncrementalVolumeProfile:
    """Maintains volume profile bucket state between ticks.

    Instead of rebuilding the full profile from all candles each tick,
    this class incrementally adds new candles and removes expired ones,
    then recomputes POC/VA from the bucket totals in O(buckets) time.
    """

    def __init__(self, buckets: int = 100) -> None:
        self._buckets = buckets
        # Per-bucket accumulators: [volume, buy_volume, sell_volume]
        self._volumes: list[list[float]] = [[0.0, 0.0, 0.0] for _ in range(buckets)]
        # Track price range so we know bucket boundaries
        self._min_price: float = 0.0
        self._max_price: float = 0.0
        self._step: float = 0.0
        self._initialized: bool = False
        # Window of candles currently in the profile (for range recalculation)
        self._candles: list[OHLC] = []

    def _needs_rebuild(self, new_candle: OHLC) -> bool:
        """Check if the new candle would fall outside the current price range."""
        if not self._initialized:
            return True
        # If candle exceeds current range, we need a full rebuild
        return new_candle.low < self._min_price or new_candle.high > self._max_price

    def _full_rebuild(self) -> None:
        """Rebuild all buckets from self._candles."""
        if not self._candles:
            self._initialized = False
            return

        min_price = min(d.low for d in self._candles)
        max_price = max(d.high for d in self._candles)
        buffer = (max_price - min_price) * 0.01
        self._min_price = min_price - buffer
        self._max_price = max_price + buffer
        price_range = self._max_price - self._min_price

        if price_range == 0:
            total_vol = sum(d.volume for d in self._candles)
            vol_per = total_vol / self._buckets
            self._volumes = [[vol_per, vol_per * 0.5, vol_per * 0.5] for _ in range(self._buckets)]
            self._step = 1.0
            self._initialized = True
            return

        self._step = price_range / self._buckets
        self._volumes = [[0.0, 0.0, 0.0] for _ in range(self._buckets)]
        for d in self._candles:
            self._add_candle_to_buckets(d)
        self._initialized = True

    def _gaussian_weights(self, candle: OHLC, start_bucket: int, end_bucket: int) -> list[float]:
        """Compute Gaussian volume distribution weights (MLX-accelerated)."""
        center = candle.vwap if candle.vwap > 0 else candle.close
        candle_range = candle.high - candle.low
        sigma = max(candle_range * 0.25, self._step * 0.5)
        bucket_centers = [
            self._min_price + (i * self._step) + (self._step / 2)
            for i in range(start_bucket, end_bucket + 1)
        ]
        return mc.gaussian_weights(bucket_centers, center, sigma)

    def _add_candle_to_buckets(self, candle: OHLC) -> None:
        """Distribute a candle's volume across buckets using Gaussian weighting."""
        if candle.volume <= 0:
            return
        start_bucket = int((candle.low - self._min_price) / self._step)
        end_bucket = int((candle.high - self._min_price) / self._step)
        start_bucket = max(0, min(self._buckets - 1, start_bucket))
        end_bucket = max(0, min(self._buckets - 1, end_bucket))

        buy_ratio = candle.taker_buy_volume / candle.volume if candle.volume > 0 else 0.5
        weights = self._gaussian_weights(candle, start_bucket, end_bucket)

        for idx, i in enumerate(range(start_bucket, end_bucket + 1)):
            vol = candle.volume * weights[idx]
            self._volumes[i][0] += vol
            self._volumes[i][1] += vol * buy_ratio
            self._volumes[i][2] += vol * (1 - buy_ratio)

    def _remove_candle_from_buckets(self, candle: OHLC) -> None:
        """Remove a candle's Gaussian-weighted volume contribution from buckets."""
        if candle.volume <= 0:
            return
        start_bucket = int((candle.low - self._min_price) / self._step)
        end_bucket = int((candle.high - self._min_price) / self._step)
        start_bucket = max(0, min(self._buckets - 1, start_bucket))
        end_bucket = max(0, min(self._buckets - 1, end_bucket))

        buy_ratio = candle.taker_buy_volume / candle.volume if candle.volume > 0 else 0.5
        weights = self._gaussian_weights(candle, start_bucket, end_bucket)

        for idx, i in enumerate(range(start_bucket, end_bucket + 1)):
            vol = candle.volume * weights[idx]
            self._volumes[i][0] = max(0.0, self._volumes[i][0] - vol)
            self._volumes[i][1] = max(0.0, self._volumes[i][1] - vol * buy_ratio)
            self._volumes[i][2] = max(0.0, self._volumes[i][2] - vol * (1 - buy_ratio))

    def update(self, new_candle: OHLC, oldest_candle_to_remove: OHLC | None = None) -> None:
        """Incrementally update the profile with a new candle.

        Args:
            new_candle: The latest candle to add.
            oldest_candle_to_remove: If the lookback window is exceeded,
                pass the candle that just fell out so its volume is subtracted.
        """
        # Remove expired candle from window
        needs_remove = False
        if oldest_candle_to_remove is not None and self._candles:
            # Match by value (time) rather than identity to avoid silent skips
            if self._candles[0].time == oldest_candle_to_remove.time:
                self._candles.pop(0)
                needs_remove = True

        self._candles.append(new_candle)

        if self._needs_rebuild(new_candle):
            self._full_rebuild()
            return

        # Fast path: remove old, add new within existing range
        if needs_remove:
            # Check if removed candle was near the original (pre-buffer) range boundary.
            # Compute the pre-buffer range from current min_price/max_price:
            # original_min = min_price + buffer, original_max = max_price - buffer
            # where buffer = (original_max - original_min) * 0.01
            # Simplified: candle is boundary if its low/high is close to the range edge
            range_size = self._max_price - self._min_price
            edge_tolerance = range_size * 0.015  # slightly wider than the 1% buffer
            was_boundary = (
                oldest_candle_to_remove.low <= self._min_price + edge_tolerance
                or oldest_candle_to_remove.high >= self._max_price - edge_tolerance
            )
            if was_boundary:
                self._full_rebuild()
                return
            self._remove_candle_from_buckets(oldest_candle_to_remove)

        self._add_candle_to_buckets(new_candle)

    def get_profile(self) -> list[VolumeProfileLevel]:
        """Return the current profile in the same format as create_profile().

        POC and value area are computed by the caller (AMTAnalyzer.analyze).
        """
        if not self._initialized or not self._candles:
            return []

        step = self._step
        return [
            VolumeProfileLevel(
                price=self._min_price + (i * step) + (step / 2),
                volume=self._volumes[i][0],
                buy_volume=self._volumes[i][1],
                sell_volume=self._volumes[i][2],
            )
            for i in range(self._buckets)
        ]


def find_lvns(
    profile: list[VolumeProfileLevel],
    cfg: AMTConfig | None = None,
    smoothed: list[float] | None = None,
) -> list[float]:
    """Detect Low Volume Nodes using smoothing + mean-threshold method.

    Formula: smooth histogram, then find local minima where
    smoothed_volume(i) <= LVN_THRESHOLD × mean(smoothed_volume).
    """
    cfg = cfg or AMTConfig()
    if len(profile) < 3:
        return []

    raw = [p.volume for p in profile]
    sm = smoothed if smoothed else smooth_array(raw, cfg.LVN_SMOOTHING)
    mean_vol = sum(sm) / len(sm) if sm else 0.0
    if mean_vol <= 0:
        return []

    threshold = mean_vol * cfg.LVN_THRESHOLD
    step = profile[1].price - profile[0].price if len(profile) > 1 else 1.0
    lvns: list[float] = []

    for i in range(1, len(sm) - 1):
        if sm[i] < sm[i - 1] and sm[i] < sm[i + 1] and sm[i] <= threshold:
            if not lvns or abs(profile[i].price - lvns[-1]) > step * 2:
                lvns.append(profile[i].price)
    return lvns


def find_hvns(
    profile: list[VolumeProfileLevel],
    cfg: AMTConfig | None = None,
    smoothed: list[float] | None = None,
) -> list[float]:
    """Detect High Volume Nodes using smoothing + max-threshold method.

    Formula: smooth histogram, then find local maxima where
    smoothed_volume(i) >= HVN_THRESHOLD × max(smoothed_volume).
    """
    cfg = cfg or AMTConfig()
    if len(profile) < 3:
        return []

    raw = [p.volume for p in profile]
    sm = smoothed if smoothed else smooth_array(raw, cfg.LVN_SMOOTHING)
    max_vol = max(sm) if sm else 0.0
    if max_vol <= 0:
        return []

    threshold = max_vol * cfg.HVN_THRESHOLD
    step = profile[1].price - profile[0].price if len(profile) > 1 else 1.0
    hvns: list[float] = []

    for i in range(1, len(sm) - 1):
        if sm[i] > sm[i - 1] and sm[i] > sm[i + 1] and sm[i] >= threshold:
            if not hvns or abs(profile[i].price - hvns[-1]) > step * 2:
                hvns.append(profile[i].price)
    return hvns


def compute_aggression_sigma(
    candle: OHLC,
    data: list[OHLC],
    ema_period: int = 20,
) -> float:
    """Z-score of candle volume vs EMA-based dynamic threshold (MLX-accelerated)."""
    if len(data) < 10 or candle.volume == 0:
        return 0.0
    return mc.aggression_sigma(candle.volume, [d.volume for d in data], ema_period)


def find_aggressive_prints(
    data: list[OHLC],
    cfg: AMTConfig | None = None,
    previous_prints: list[AggressivePrint] | None = None,
    previous_data_len: int = 0,
) -> list[AggressivePrint]:
    """Detect aggressive buying/selling 'volume bubbles' using 2.5σ filter.

    Incremental: if data grew by 1 and previous_prints is provided, only
    check the last candle and append to previous results.

    A print is aggressive when:
    1. Volume exceeds 2.5 standard deviations above the rolling mean, AND
    2. Delta directionality is at least 15% of total volume.
    """
    cfg = cfg or AMTConfig()
    if len(data) < 20:
        return list(previous_prints) if previous_prints else []

    # Incremental path: only check the last candle
    if (previous_prints is not None
            and previous_data_len > 0
            and len(data) == previous_data_len + 1):
        prints = list(previous_prints)
        # Expire prints older than 30 candles
        if len(data) > 30:
            cutoff_time = data[-30].time
            prints = [p for p in prints if p.time >= cutoff_time]
        i = len(data) - 1
        d = data[i]
        lookback = data[max(0, i - 50):i]
        if len(lookback) >= 10:
            sigma = compute_aggression_sigma(d, lookback, cfg.AGGRESSION_EMA_PERIOD)
            if sigma >= cfg.AGGRESSION_SIGMA_THRESHOLD:
                delta_ratio = abs(d.delta) / d.volume if d.volume > 0 else 0
                if delta_ratio >= cfg.DELTA_DIRECTIONALITY_THRESHOLD:
                    prints.append(AggressivePrint(
                        price=d.close, time=d.time, volume=d.volume,
                        delta=d.delta, side="BUY" if d.delta > 0 else "SELL",
                    ))
        return prints

    # Full rebuild with 30-candle expiry
    cutoff_idx = max(0, len(data) - 30)
    prints: list[AggressivePrint] = []
    for i, d in enumerate(data):
        if i < cutoff_idx:
            continue  # skip candles older than 30 from end
        lookback = data[max(0, i - 50):i] if i > 10 else data[:i]
        if len(lookback) < 10:
            continue
        sigma = compute_aggression_sigma(d, lookback, cfg.AGGRESSION_EMA_PERIOD)
        if sigma >= cfg.AGGRESSION_SIGMA_THRESHOLD:
            delta_ratio = abs(d.delta) / d.volume if d.volume > 0 else 0
            if delta_ratio >= cfg.DELTA_DIRECTIONALITY_THRESHOLD:
                prints.append(AggressivePrint(
                    price=d.close, time=d.time, volume=d.volume,
                    delta=d.delta, side="BUY" if d.delta > 0 else "SELL",
                ))
    return prints


# ---------------------------------------------------------------------------
# Initial Balance Tracker
# ---------------------------------------------------------------------------

class InitialBalanceTracker:
    """Tracks Initial Balance (IB) — high/low of the first N minutes of session."""

    def __init__(self, ib_minutes: int = 30) -> None:
        self._ib_minutes = ib_minutes
        self._ib_high: float = 0.0
        self._ib_low: float = float("inf")
        self._session_open_time: str = ""
        self._complete: bool = False

    def reset(self) -> None:
        self._ib_high = 0.0
        self._ib_low = float("inf")
        self._session_open_time = ""
        self._complete = False

    def update(self, candle: OHLC) -> tuple[float, float, bool]:
        """Update IB tracking. Returns (ib_high, ib_low, is_complete)."""
        if self._complete:
            return self._ib_high, self._ib_low, True

        if not self._session_open_time:
            self._session_open_time = candle.time

        # Check if IB window has elapsed
        try:
            open_dt = datetime.fromisoformat(self._session_open_time)
            curr_dt = datetime.fromisoformat(candle.time)
            elapsed_minutes = (curr_dt - open_dt).total_seconds() / 60
            if elapsed_minutes >= self._ib_minutes:
                self._complete = True
                return self._ib_high, self._ib_low, True
        except (ValueError, TypeError):
            pass

        self._ib_high = max(self._ib_high, candle.high)
        self._ib_low = min(self._ib_low, candle.low)
        return self._ib_high, self._ib_low, False


# ---------------------------------------------------------------------------
# Acceptance / Rejection Engine
# ---------------------------------------------------------------------------

class AcceptanceRejectionEngine:
    """Tracks acceptance/rejection at VA boundaries using time, volume, and price action."""

    def __init__(self) -> None:
        self._time_above_vah: float = 0.0  # cumulative seconds outside VAH
        self._time_below_val: float = 0.0  # cumulative seconds outside VAL
        self._last_time: str = ""
        self._acceptance_time_threshold: float = 120.0  # seconds
        self._acceptance_vol_ratio: float = 1.2  # volume must be > 1.2x baseline

    def reset(self) -> None:
        self._time_above_vah = 0.0
        self._time_below_val = 0.0
        self._last_time = ""

    def update(
        self, candle: OHLC, vah: float, val: float, baseline_vol: float,
    ) -> dict:
        """Update acceptance/rejection state.

        Returns dict with keys: acceptance_above, acceptance_below,
        rejection_at_high, rejection_at_low, price_velocity.
        """
        result = {
            "acceptance_above": False,
            "acceptance_below": False,
            "rejection_at_high": False,
            "rejection_at_low": False,
            "price_velocity": 0.0,
        }

        # Estimate candle duration from timestamps
        duration = 60.0  # default 1-minute candle
        if self._last_time:
            try:
                prev_dt = datetime.fromisoformat(self._last_time)
                curr_dt = datetime.fromisoformat(candle.time)
                dt = (curr_dt - prev_dt).total_seconds()
                if 0 < dt < 600:  # sanity: max 10 min
                    duration = dt
            except (ValueError, TypeError):
                pass
        self._last_time = candle.time

        # Velocity: price movement per second
        body = abs(candle.close - candle.open)
        if duration > 0:
            result["price_velocity"] = body / duration

        # Time accumulation outside VA
        if candle.close > vah and vah > 0:
            self._time_above_vah += duration
            self._time_below_val = max(0, self._time_below_val - duration * 0.5)  # decay
        elif candle.close < val and val > 0:
            self._time_below_val += duration
            self._time_above_vah = max(0, self._time_above_vah - duration * 0.5)  # decay
        else:
            # Inside VA — decay both
            self._time_above_vah = max(0, self._time_above_vah - duration * 0.5)
            self._time_below_val = max(0, self._time_below_val - duration * 0.5)

        # Acceptance: enough time outside + volume confirmation
        vol_ok = candle.volume > baseline_vol * self._acceptance_vol_ratio if baseline_vol > 0 else False
        if self._time_above_vah >= self._acceptance_time_threshold and vol_ok:
            result["acceptance_above"] = True
        if self._time_below_val >= self._acceptance_time_threshold and vol_ok:
            result["acceptance_below"] = True

        # Rejection detection: wick > body at VA edge + volume spike
        candle_range = candle.high - candle.low
        if candle_range > 0:
            upper_wick = candle.high - max(candle.open, candle.close)
            lower_wick = min(candle.open, candle.close) - candle.low
            body_size = abs(candle.close - candle.open)
            vol_spike = candle.volume > baseline_vol * 1.5 if baseline_vol > 0 else False

            # Rejection at high (near VAH): upper wick > body, price near VAH
            threshold = candle.close * 0.003
            if (upper_wick > body_size and vol_spike
                    and vah > 0 and abs(candle.high - vah) < threshold):
                result["rejection_at_high"] = True

            # Rejection at low (near VAL): lower wick > body, price near VAL
            if (lower_wick > body_size and vol_spike
                    and val > 0 and abs(candle.low - val) < threshold):
                result["rejection_at_low"] = True

        return result


# ---------------------------------------------------------------------------
# Break Detection — Initiative vs Responsive
# ---------------------------------------------------------------------------

def detect_break(
    data: list[OHLC],
    vah: float,
    val: float,
    ib_high: float,
    ib_low: float,
    baseline_vol: float,
) -> dict:
    """Detect initiative breaks, responsive fades, and absorption at key levels.

    Returns dict with break_direction, break_type, break_level, volume_ratio.
    """
    empty = {"break_direction": "", "break_type": "", "break_level": 0.0, "volume_ratio": 0.0}
    if len(data) < 3 or baseline_vol <= 0:
        return empty

    current = data[-1]
    prev = data[-2]
    vol_ratio = current.volume / baseline_vol if baseline_vol > 0 else 0.0
    body = abs(current.close - current.open)
    candle_range = current.high - current.low

    # Key levels to check
    levels_up: list[tuple[str, float]] = []   # levels that indicate upward break
    levels_down: list[tuple[str, float]] = []  # levels that indicate downward break
    if vah > 0:
        levels_up.append(("VAH", vah))
        levels_down.append(("VAL", val))
    if ib_high > 0:
        levels_up.append(("IBH", ib_high))
    if ib_low > 0 and ib_low != float("inf"):
        levels_down.append(("IBL", ib_low))

    # Check INITIATIVE BREAK upward
    for _label, level in levels_up:
        if level > 0 and current.close > level and prev.close <= level:
            if vol_ratio > 1.5:
                # Delta confirms: last 2 candles have positive delta
                delta_confirms = all(d.delta > 0 for d in data[-2:])
                if delta_confirms:
                    return {
                        "break_direction": "UP",
                        "break_type": "INITIATIVE",
                        "break_level": level,
                        "volume_ratio": round(vol_ratio, 2),
                    }

    # Check INITIATIVE BREAK downward
    for _label, level in levels_down:
        if level > 0 and current.close < level and prev.close >= level:
            if vol_ratio > 1.5:
                delta_confirms = all(d.delta < 0 for d in data[-2:])
                if delta_confirms:
                    return {
                        "break_direction": "DOWN",
                        "break_type": "INITIATIVE",
                        "break_level": level,
                        "volume_ratio": round(vol_ratio, 2),
                    }

    # Check ABSORPTION: flat candle + high absolute delta at key level
    threshold = current.close * 0.003
    if candle_range > 0 and body < candle_range * 0.30:
        delta_ratio = abs(current.delta) / current.volume if current.volume > 0 else 0
        if delta_ratio > 0.25:  # strong hidden delta
            for _label, level in levels_up + levels_down:
                if level > 0 and abs(current.close - level) < threshold:
                    return {
                        "break_direction": "UP" if current.delta > 0 else "DOWN",
                        "break_type": "ABSORPTION",
                        "break_level": level,
                        "volume_ratio": round(vol_ratio, 2),
                    }

    # Check RESPONSIVE FADE: touch extreme + no vol expansion + wick rejection
    upper_wick = current.high - max(current.open, current.close)
    lower_wick = min(current.open, current.close) - current.low

    # Responsive fade at high (touch VAH/IBH, rejected)
    for _label, level in levels_up:
        if level > 0 and abs(current.high - level) < threshold:
            if vol_ratio < 1.2 and upper_wick > body:
                return {
                    "break_direction": "DOWN",
                    "break_type": "RESPONSIVE",
                    "break_level": level,
                    "volume_ratio": round(vol_ratio, 2),
                }

    # Responsive fade at low (touch VAL/IBL, rejected)
    for _label, level in levels_down:
        if level > 0 and abs(current.low - level) < threshold:
            if vol_ratio < 1.2 and lower_wick > body:
                return {
                    "break_direction": "UP",
                    "break_type": "RESPONSIVE",
                    "break_level": level,
                    "volume_ratio": round(vol_ratio, 2),
                }

    return empty


# ---------------------------------------------------------------------------
# LVN Velocity Play Detection
# ---------------------------------------------------------------------------

def detect_lvn_play(
    candle: OHLC,
    lvns: list[float],
    hvns: list[float],
    poc: float,
    baseline_vol: float,
    cvd_slope: float,
    prev_cvd_slope: float = 0.0,
) -> dict | None:
    """Detect LVN rejection play: velocity spike + rejection candle + delta flip at LVN.

    Returns play details dict or None if no play detected.
    """
    if not lvns or candle.volume <= 0:
        return None

    threshold = candle.close * 0.003  # 0.3% proximity

    # Find nearest LVN
    nearest_lvn = None
    nearest_dist = float("inf")
    for lvn in lvns:
        dist = abs(candle.close - lvn)
        if dist < threshold and dist < nearest_dist:
            nearest_lvn = lvn
            nearest_dist = dist

    if nearest_lvn is None:
        return None

    # Velocity spike: volume > 2x baseline
    velocity_ratio = candle.volume / baseline_vol if baseline_vol > 0 else 0.0
    has_velocity = velocity_ratio > 2.0

    # Rejection candle: wick > body
    body = abs(candle.close - candle.open)
    upper_wick = candle.high - max(candle.open, candle.close)
    lower_wick = min(candle.open, candle.close) - candle.low
    has_rejection = max(upper_wick, lower_wick) > body and body > 0

    # Delta flip: CVD slope sign change
    has_delta_flip = (cvd_slope * prev_cvd_slope < 0) if prev_cvd_slope != 0 else False

    # Need at least 2 of 3 conditions
    score = sum([has_velocity, has_rejection, has_delta_flip])
    if score < 2:
        return None

    # Determine direction from rejection
    if lower_wick > upper_wick:
        direction = "LONG"  # rejected lower prices -> bounce up
    else:
        direction = "SHORT"  # rejected higher prices -> move down

    # Target: POC or nearest HVN
    target = poc
    if hvns:
        if direction == "LONG":
            above_hvns = [h for h in hvns if h > candle.close]
            if above_hvns:
                target = min(above_hvns)
        else:
            below_hvns = [h for h in hvns if h < candle.close]
            if below_hvns:
                target = max(below_hvns)

    return {
        "lvn_price": nearest_lvn,
        "direction": direction,
        "target": target,
        "velocity_ratio": round(velocity_ratio, 2),
        "has_rejection": has_rejection,
        "has_delta_flip": has_delta_flip,
    }


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
        self._structure_classifier: "MarketStructureClassifier | None" = None
        self._vwap_history: list[float] = []
        # Incremental aggressive prints state
        self._prev_agg_prints: list[AggressivePrint] = []
        self._prev_agg_data_len: int = 0
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

    def detect_displacement_leg(self, data: list[OHLC]) -> dict:
        """Detect displacement and return leg profile data.

        Always builds a leg profile from the most recent directional move
        (consecutive same-direction candles from the end). The strict displacement
        flag is set when the move also meets range expansion criteria.
        """
        empty = {"has_displacement": False, "profile": [], "lvns": [], "poc": 0.0, "vah": 0.0, "val": 0.0}
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
        leg_profile = create_profile(leg_candles, buckets=100)
        if len(leg_profile) < 3:
            return {"has_displacement": is_disp, "profile": leg_profile, "lvns": [], "poc": 0.0, "vah": 0.0, "val": 0.0}
        leg_lvns = find_lvns(leg_profile, self.config)

        # POC — VWAP tie-break (matches session logic)
        max_vol = max(p.volume for p in leg_profile)
        poc_candidates = [i for i, p in enumerate(leg_profile) if p.volume == max_vol]
        vwap_ref = (
            self._vwap_cum_quote_vol / self._vwap_cum_vol
            if self._vwap_cum_vol > 0 else data[-1].close
        )
        poc_idx = min(poc_candidates, key=lambda i: abs(leg_profile[i].price - vwap_ref))
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

        step = leg_profile[1].price - leg_profile[0].price if len(leg_profile) > 1 else 0
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
        prev_data = data[-(20 + N):-N]
        if len(prev_data) < 10:
            return False

        avg_range = sum(d.high - d.low for d in prev_data) / len(prev_data)
        leg_range = max(c.high for c in recent) - min(c.low for c in recent)

        if leg_range < avg_range * 1.5 * N:
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
    ) -> AMTResult:
        """Run the full AMT analysis pipeline."""
        empty = AMTResult(
            market_state=MarketState.BALANCED.value,
            poc=0, value_area_high=0, value_area_low=0,
        )

        if not data or len(data) < 5:
            return empty

        lookback = min(len(data), 200)
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
        vwap_ref = (
            self._vwap_cum_quote_vol / self._vwap_cum_vol
            if self._vwap_cum_vol > 0 else current.close
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
                    if up_idx + 1 < len(profile):
                        up_idx += 1
                        current_volume += profile[up_idx].volume
            elif can_go_down:
                # Expand downward by up to 2 rows
                for k in range(1, down_count + 1):
                    if down_idx - 1 >= 0:
                        down_idx -= 1
                        current_volume += profile[down_idx].volume

        # VAH = upper edge of top VA bin, VAL = lower edge of bottom VA bin
        step = profile[1].price - profile[0].price if len(profile) > 1 else 0
        half_step = step / 2
        vah = profile[up_idx].price + half_step    # upper edge
        val = profile[down_idx].price - half_step  # lower edge

        # Note: we no longer artificially expand VA width. A very tight VA
        # is valid market information (low volatility). Synthetic expansion was
        # creating false "near level" triggers in the Three-Align Gate.

        lvns = find_lvns(profile, self.config)
        hvns = find_hvns(profile, self.config)
        # LVN/HVN detection complete
        # Incremental aggressive prints — only compute last candle if data grew by 1
        agg_prints = find_aggressive_prints(
            recent_data, self.config,
            previous_prints=self._prev_agg_prints,
            previous_data_len=self._prev_agg_data_len,
        )
        self._prev_agg_prints = agg_prints
        self._prev_agg_data_len = len(recent_data)

        # Baseline volume for acceptance/rejection (mean of last 20 candles)
        baseline_vol = sum(d.volume for d in recent_data[-20:]) / min(20, len(recent_data)) if recent_data else 0.0

        # Acceptance/Rejection engine
        ar_state = self._ar_engine.update(current, vah, val, baseline_vol)

        # 2. Market State (Fabio: Displacement + Acceptance + ATR compression)
        market_state = MarketState.BALANCED

        leg_data = self.detect_displacement_leg(recent_data)
        has_displacement = leg_data["has_displacement"]
        has_acceptance = self.detect_acceptance(recent_data, vah, val)

        # Merge with AR engine state
        if ar_state["acceptance_above"] or ar_state["acceptance_below"]:
            has_acceptance = True

        # Balance ratio: fraction of recent candles inside VA (computed early for market state)
        balance_window = min(len(recent_data), 20)
        inside_count = sum(1 for d in recent_data[-balance_window:] if val <= d.close <= vah)
        balance_ratio = inside_count / balance_window if balance_window > 0 else 0.0
        ratio_imbalanced = balance_ratio < 0.70 if balance_window >= 5 else False

        # Require EITHER (displacement + acceptance) OR low balance ratio + acceptance
        # OR persistent price outside VA (slow drift / sustained breakout)
        # Safety override: zero candles in VA = definitive imbalance
        if balance_ratio == 0.0 and balance_window >= 5:
            market_state = MarketState.IMBALANCED
        elif (has_displacement and has_acceptance) or (ratio_imbalanced and has_acceptance):
            market_state = MarketState.IMBALANCED

        # Persistent outside-VA check: if price is clearly outside VA without
        # needing the strict displacement pattern (handles slow drifts)
        if market_state == MarketState.BALANCED and len(recent_data) >= 5:
            price_outside = current.close > vah or current.close < val
            if price_outside and has_acceptance:
                # Price is outside VA with 3+ closes confirming = IMBALANCED
                market_state = MarketState.IMBALANCED

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
        self._vwap_last_time = current.time

        self._vwap_cum_vol += current.volume
        self._vwap_cum_quote_vol += quote_vol
        self._vwap_cum_sq_vol += typical_price * typical_price * current.volume
        session_vwap = (
            self._vwap_cum_quote_vol / self._vwap_cum_vol
            if self._vwap_cum_vol > 0 else current.close
        )

        # VWAP standard deviation bands (±1σ, ±2σ)
        vwap_std = 0.0
        if self._vwap_cum_vol > 0:
            variance = (self._vwap_cum_sq_vol / self._vwap_cum_vol) - (session_vwap * session_vwap)
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
            data, self._poc_tracker._poc_history, self._vwap_history,
        )

        # Initial Balance tracking
        ib_high, ib_low, ib_complete = self._ib_tracker.update(current)

        # POC migration with price alignment
        poc_migration = self._poc_tracker.update(poc, current.close)

        # LVN velocity play detection
        lvn_play = detect_lvn_play(
            current, list(lvns), list(hvns), poc, baseline_vol,
            cvd_state.slope, self._prev_cvd_slope,
        )
        self._prev_cvd_slope = cvd_state.slope

        # Break detection — initiative vs responsive at key levels
        break_state = detect_break(recent_data, vah, val, ib_high, ib_low, baseline_vol)

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
            has_displacement=leg_data.get("has_displacement", False),
            market_structure=structure.state,
            structure_confidence=structure.confidence_score,
            ib_high=ib_high,
            ib_low=ib_low if ib_low != float("inf") else 0.0,
            ib_complete=ib_complete,
            prior_poc=prior_poc,
            prior_vah=prior_vah,
            prior_val=prior_val,
            gap_type=classify_gap(
                open_price=data[0].open if data else 0.0,
                prior_close=prior_poc,  # Use POC as proxy for prior close
                prior_range=prior_vah - prior_val if prior_vah > 0 and prior_val > 0 else 0.0,
            ) if prior_poc > 0 else "",
            opening_bias=opening_inventory_bias(
                open_price=data[0].open if data else 0.0,
                prior_vah=prior_vah,
                prior_val=prior_val,
            ) if prior_vah > 0 else "",
            acceptance_above=ar_state["acceptance_above"],
            acceptance_below=ar_state["acceptance_below"],
            rejection_at_high=ar_state["rejection_at_high"],
            rejection_at_low=ar_state["rejection_at_low"],
            price_velocity=ar_state["price_velocity"],
            poc_signal=poc_migration.signal,
            poc_vs_price=poc_migration.poc_vs_price,
            lvn_play=lvn_play,
            break_direction=break_state["break_direction"],
            break_type=break_state["break_type"],
            break_level=break_state["break_level"],
            ofi=obi,
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
        now_iso = current.time  # use tick timestamp, not wall clock

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
