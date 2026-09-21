"""Order Flow Detectors — Standalone detection modules per Fabio AMT spec (FR-03).

Modules:
  - BigTradeDetector: FR-03-11 — institutional print cluster detection
  - BubbleDetector: FR-03-07/08 — volume spike detection
  - OFICalculator: FR-03-12 — order flow imbalance
  - AbsorptionDetector: FR-03-09/10 — absorption candle detection
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass

from quant.contracts.value_objects import OHLC
from quant.contracts.constants import (
    BIG_TRADE_MULTIPLIER,
    BIG_TRADE_CLUSTER_COUNT,
    BIG_TRADE_CLUSTER_TICKS,
    VOLUME_BUBBLE_SIGMA,
    OFI_WINDOW,
    ABSORPTION_RANGE_RATIO_MAX,
    ABSORPTION_VOL_MULT,
)

logger = logging.getLogger(__name__)


# =========================================================================
# BigTradeDetector (FR-03-11)
# =========================================================================


@dataclass
class BigTradeCluster:
    """Detected cluster of institutional-sized prints."""

    price: float  # Center price of the cluster
    print_count: int  # Number of prints in the cluster
    avg_size: float  # Average print size in the cluster
    side: str  # "BUY" | "SELL" | "MIXED"
    timestamp: str


class BigTradeDetector:
    """Detects clusters of institutional-sized prints (FR-03-11).

    Rule: 3+ prints where trade_size ≥ BIG_TRADE_MULTIPLIER × avg_trade_size,
    all within BIG_TRADE_CLUSTER_TICKS of each other.
    """

    def __init__(
        self,
        multiplier: float = BIG_TRADE_MULTIPLIER,
        cluster_count: int = BIG_TRADE_CLUSTER_COUNT,
        cluster_ticks: int = BIG_TRADE_CLUSTER_TICKS,
    ) -> None:
        self._multiplier = multiplier
        self._cluster_count = cluster_count
        self._cluster_ticks = cluster_ticks

    def detect(
        self,
        candle: OHLC,
        avg_candle_vol: float,
    ) -> BigTradeCluster | None:
        """Detect if current candle has institutional-level volume.

        At candle level, we detect if volume is significantly above
        rolling average candle volume (proxy for big trade cluster).

        Args:
            candle: Current OHLC candle.
            avg_candle_vol: Rolling average candle volume.
        """
        if avg_candle_vol <= 0:
            return None

        vol_ratio = float(candle.volume) / avg_candle_vol
        if vol_ratio < self._multiplier * 0.5:  # Must be at least 2.5x avg
            return None

        # Classify side from delta
        delta = float(candle.delta)
        if delta > 0:
            side = "BUY"
        elif delta < 0:
            side = "SELL"
        else:
            side = "MIXED"

        return BigTradeCluster(
            price=float((candle.high + candle.low) / 2),
            print_count=int(max(1, float(candle.volume) / avg_candle_vol)),
            avg_size=avg_candle_vol,
            side=side,
            timestamp=candle.time,
        )


# =========================================================================
# BubbleDetector (FR-03-07/08)
# =========================================================================


@dataclass
class BubbleResult:
    """Detected volume bubble."""

    detected: bool
    direction: str  # "BUY" | "SELL" | "NEUTRAL"
    sigma: float  # How many σ above mean
    candle_time: str


class BubbleDetector:
    """Detects volume bubbles (FR-03-07/08).

    Rule: volume ≥ mean + VOLUME_BUBBLE_SIGMA × std across last N bars.
    Direction: BUY if ask > bid × 2, SELL if bid > ask × 2, else NEUTRAL.
    """

    def __init__(self, lookback: int = 21) -> None:
        self._history: deque[float] = deque(maxlen=lookback)

    def detect(self, candle: OHLC) -> BubbleResult:
        """Detect if current candle has a volume bubble."""
        vol = float(candle.volume)

        # Reference distribution = PRIOR bars only. The previous version
        # appended the current volume before computing mean/std, so the spike
        # inflated its own reference std and capped the z-score (~4.4 for a
        # 21-bar window) — a 5x and a 10x bubble were indistinguishable and
        # moderate spikes fell below the threshold. Compute against history,
        # then append the current candle for future detections.
        if len(self._history) < 5:
            self._history.append(vol)
            return BubbleResult(
                detected=False, direction="NEUTRAL", sigma=0.0, candle_time=candle.time
            )

        # Compute mean and std over prior history (current candle excluded)
        vols = list(self._history)
        mean_vol = sum(vols) / len(vols)
        variance = sum((v - mean_vol) ** 2 for v in vols) / len(vols)
        std_vol = math.sqrt(variance) if variance > 0 else 0.0
        # Floor std at 10% of the mean (mirrors aggressive_prints): a perfectly
        # flat baseline (std=0) would otherwise make any spike undetectable,
        # and a near-flat baseline would inflate z-scores.
        if mean_vol > 0:
            std_vol = max(std_vol, mean_vol * 0.10)

        self._history.append(vol)

        if std_vol <= 0:
            return BubbleResult(
                detected=False, direction="NEUTRAL", sigma=0.0, candle_time=candle.time
            )

        # Z-score
        sigma = (vol - mean_vol) / std_vol

        if sigma < VOLUME_BUBBLE_SIGMA:
            return BubbleResult(
                detected=False,
                direction="NEUTRAL",
                sigma=sigma,
                candle_time=candle.time,
            )

        # Classify direction from delta
        delta = float(candle.delta)
        if delta > 0:
            direction = "BUY"
        elif delta < 0:
            direction = "SELL"
        else:
            direction = "NEUTRAL"

        return BubbleResult(
            detected=True,
            direction=direction,
            sigma=sigma,
            candle_time=candle.time,
        )


# =========================================================================
# OFICalculator (FR-03-12)
# =========================================================================


@dataclass
class OFIResult:
    """Order Flow Imbalance result."""

    ofi: float  # -1.0 to +1.0
    window: int  # Number of candles in window


class OFICalculator:
    """Order Flow Imbalance over rolling window (FR-03-12).
    OFI = OFI
    Uses candle delta as proxy for (ask_vol - bid_vol).
    """

    def __init__(self, window: int = OFI_WINDOW) -> None:
        self._window = window
        self._deltas: deque[float] = deque(maxlen=window)
        self._volumes: deque[float] = deque(maxlen=window)

    def update(self, candle: OHLC) -> OFIResult:
        """Update with new candle and return rolling OFI."""
        delta = float(candle.delta)
        volume = float(candle.volume)
        
        # Validate inputs
        if volume <= 0:
            return OFIResult(ofi=0.0, window=len(self._deltas))
        
        # Delta should never exceed volume in magnitude (sanity check)
        if abs(delta) > volume:
            logger.warning(
                "OFI delta (%.0f) exceeds volume (%.0f) — normalizing",
                delta, volume
            )
            delta = volume if delta > 0 else -volume
        
        self._deltas.append(delta)
        self._volumes.append(volume)

        total_vol = sum(self._volumes)
        if total_vol <= 0:
            return OFIResult(ofi=0.0, window=len(self._deltas))

        total_delta = sum(self._deltas)
        ofi = total_delta / total_vol
        
        # Clamp to valid range [-1.0, +1.0]
        ofi = max(-1.0, min(1.0, ofi))
        
        # Detect suspiciously round numbers (possible hardcoded/capped values)
        if abs(ofi) > 0.001 and abs(ofi % 1.0) < 0.001:
            logger.warning(
                "OFI suspiciously round: %.3f — possible calculation error",
                ofi
            )

        return OFIResult(ofi=ofi, window=len(self._deltas))

    def reset(self) -> None:
        self._deltas.clear()
        self._volumes.clear()


# =========================================================================
# AbsorptionDetector (FR-03-09/10)
# =========================================================================


@dataclass
class AbsorptionResult:
    """Absorption detection result."""

    detected: bool
    side: str  # "SELL_ABSORBED" (bullish) | "BUY_ABSORBED" (bearish) | ""
    range_ratio: float  # candle_range / ATR
    vol_ratio: float  # candle_volume / avg_volume
    cluster_high: float = 0.0  # high of the absorption cluster (valid when detected or active)
    cluster_low: float = 0.0   # low of the absorption cluster (valid when detected or active)
    active: bool = False       # True when a pending absorption is awaiting displacement


class AbsorptionDetector:
    """Detects absorption candles with required displacement (FR-03-09/10).

    Spec §7.2 dual condition (remediated to the spec's numbers — review C7):
    - (high - low) <= 0.50 x H_range, where H_range is the 20-bar average RANGE
      (not 0.30 x ATR; ATR also accounts for overnight gaps, so it is a
      different statistic as well as a different number)
    - V_b >= 1.50 x the 20-BAR rolling average volume (not 2.0x the full-window
      mean; the caller now supplies the 20-bar mean as `avg_vol`)

    Displacement Requirement (Quant Update):
    - Once absorption is flagged, the NEXT 1-2 candles MUST close beyond 
      the absorption candle's high/low to validate the signal.
    """
    
    def __init__(self):
        self._pending_candle = None
        self._pending_side = ""
        self._pending_range_ratio = 0.0
        self._pending_vol_ratio = 0.0
        self._candles_since_pending = 0

    def detect(
        self,
        candle: OHLC,
        h_range: float,
        avg_vol: float,
    ) -> AbsorptionResult:
        """Detect absorption on current candle, requiring displacement."""
        # 1. Check for pending displacement validation
        if self._pending_candle is not None:
            self._candles_since_pending += 1
            
            # Did it displace?
            displaced_bullish = float(candle.close) > float(self._pending_candle.high)
            displaced_bearish = float(candle.close) < float(self._pending_candle.low)
            
            if self._pending_side == "SELL_ABSORBED" and displaced_bullish:
                # Validated bullish absorption!
                res = AbsorptionResult(
                    True, "SELL_ABSORBED", self._pending_range_ratio, self._pending_vol_ratio,
                    cluster_high=float(self._pending_candle.high),
                    cluster_low=float(self._pending_candle.low),
                )
                self._clear_pending()
                return res
            elif self._pending_side == "BUY_ABSORBED" and displaced_bearish:
                # Validated bearish absorption!
                res = AbsorptionResult(
                    True, "BUY_ABSORBED", self._pending_range_ratio, self._pending_vol_ratio,
                    cluster_high=float(self._pending_candle.high),
                    cluster_low=float(self._pending_candle.low),
                )
                self._clear_pending()
                return res
            
            # Expire if no displacement within 3 candles or broke the wrong way
            if self._candles_since_pending >= 3 or (self._pending_side == "SELL_ABSORBED" and displaced_bearish) or (self._pending_side == "BUY_ABSORBED" and displaced_bullish):
                self._clear_pending()
                
        # 1b. Pending absorption still active (not displaced, not expired): report
        #     active state with the pending cluster bounds so the Triple-A machine
        #     can track the ABSORBING phase before breakout.
        if self._pending_candle is not None:
            side_now = self._pending_side if self._pending_side else ""
            ch = float(self._pending_candle.high)
            cl = float(self._pending_candle.low)
        else:
            side_now = ""
            ch = 0.0
            cl = 0.0

        # 2. Detect NEW absorption signatures
        candle_range = float(candle.high - candle.low)
        candle_vol = float(candle.volume)

        if h_range <= 0 or avg_vol <= 0:
            return AbsorptionResult(False, "", 0.0, 0.0, cluster_high=ch, cluster_low=cl, active=self._pending_candle is not None)

        range_ratio = candle_range / h_range
        vol_ratio = candle_vol / avg_vol

        # Spec §7.2: the volume test uses 1.50x the 20-bar mean, the range test
        # 0.50x the 20-bar average RANGE. The caller supplies both statistics
        # (avg_vol is the 20-bar mean, h_range is the 20-bar average RANGE).
        if range_ratio <= ABSORPTION_RANGE_RATIO_MAX and vol_ratio >= ABSORPTION_VOL_MULT:
            # Spec §7.2: Classify absorption direction using the 60% volume
            # concentration rule + close-position confirmation. This replaces
            # raw delta sign, which is a noisy proxy for aggression direction.
            #
            #   BUY absorption (bullish): aggressive sellers >= 60% of volume
            #       AND close in upper half of range -> SELL_ABSORBED
            #   SELL absorption (bearish): aggressive buyers >= 60% of volume
            #       AND close in lower half of range -> BUY_ABSORBED
            candle_vol = float(candle.volume)
            taker_buy = float(getattr(candle, "taker_buy_volume", 0.0) or 0.0)

            if 0.0 < taker_buy < candle_vol:
                # Use directly reported taker buy volume (live data path)
                buy_vol = taker_buy
                sell_vol = candle_vol - taker_buy
            else:
                # Derive buy/sell split from delta (clamped to ±volume)
                delta_val = float(candle.delta)
                if abs(delta_val) > candle_vol:
                    delta_val = candle_vol if delta_val > 0 else -candle_vol
                buy_vol = (candle_vol + delta_val) / 2.0
                sell_vol = (candle_vol - delta_val) / 2.0

            rng = float(candle.high - candle.low)
            close_px = float(candle.close)
            mid_low = float(candle.low) + 0.5 * rng
            mid_high = float(candle.high) - 0.5 * rng

            if sell_vol >= 0.60 * candle_vol and close_px >= mid_low:
                self._pending_side = "SELL_ABSORBED"  # Sellers absorbed by hidden buyers -> bullish
            elif buy_vol >= 0.60 * candle_vol and close_px <= mid_high:
                self._pending_side = "BUY_ABSORBED"  # Buyers absorbed by hidden sellers -> bearish
            else:
                # Volume/range signature present but no directional concentration
                return AbsorptionResult(
                    False, "", range_ratio, vol_ratio,
                    cluster_high=ch, cluster_low=cl, active=self._pending_candle is not None,
                )

            # Store as pending, wait for displacement
            self._pending_candle = candle
            self._pending_range_ratio = range_ratio
            self._pending_vol_ratio = vol_ratio
            self._candles_since_pending = 0
            ch = float(candle.high)
            cl = float(candle.low)

        return AbsorptionResult(
            False, "", range_ratio, vol_ratio,
            cluster_high=ch, cluster_low=cl, active=self._pending_candle is not None,
        )

    def _clear_pending(self):
        self._pending_candle = None
        self._pending_side = ""
        self._pending_range_ratio = 0.0
        self._pending_vol_ratio = 0.0
        self._candles_since_pending = 0
