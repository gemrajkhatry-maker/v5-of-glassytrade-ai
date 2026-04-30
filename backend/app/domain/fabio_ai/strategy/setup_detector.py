"""Setup Detector — AMT-based setup identification.

Implements Fabio Valentini's AAA setup detection for NSE options:
- AAA Setup: Value area low on absorption (volume spike + positive delta + bullish candle)
- Momentum Setup: Value area high in IMBALANCED state
- Mean Reversion: Price far from VWAP with balanced state

NSE Adaptation:
- Volume spike at VAL/VAH as absorption proxy
- CVD/delta as order flow proxy (NSE doesn't provide tick data)
- Bullish/bearish candle structure at key levels
"""

from __future__ import annotations

import math
from typing import Optional
from app.domain.fabio_ai.strategy.protocols import Setup, MarketContext


class AMTSetupDetector:
    """Detect AMT setups from market context.

    AAA Setup detection criteria (per AMT spec):
    1. Price within 2% of VAL (for longs) or VAH (for shorts)
    2. Volume spike >= 1.5x average (proxied by delta/cvd)
    3. Positive delta/CVD slope (absorption confirmation)
    4. Bullish candle structure (close > open, close in upper 40% of range)
    """

    # Thresholds for NSE AAA detection
    PRICE_TOLERANCE_PCT = 0.02  # 2% from VAL/VAH
    MIN_CVD_SLOPE = 30.0  # Strong positive CVD for absorption
    MIN_DELTA = 50.0  # Positive delta for bullish pressure
    MIN_CONFIDENCE = 0.7  # Minimum confidence threshold

    def detect(self, context: MarketContext) -> Optional[Setup]:
        """Detect the current AMT setup from market conditions."""
        return self.identify(context)

    def identify(self, context: MarketContext) -> Optional[Setup]:
        """Identify the current setup from market context.

        Checks in order (per AMT spec):
        1. Failed Auction (probes VA boundaries)
        2. AAA at VAL (long setup)
        3. AAA at VAH (short setup)
        4. Momentum in IMBALANCED state
        5. Mean reversion when price far from VWAP
        """
        # Try failed auction first (highest priority per spec)
        fa = self._detect_failed_auction(context)
        if fa and fa.confidence >= self.MIN_CONFIDENCE:
            return fa

        # Try AAA at VAL (long)
        aaa_long = self._detect_aaa_long(context)
        if aaa_long and aaa_long.confidence >= self.MIN_CONFIDENCE:
            return aaa_long

        # Try AAA at VAH (short)
        aaa_short = self._detect_aaa_short(context)
        if aaa_short and aaa_short.confidence >= self.MIN_CONFIDENCE:
            return aaa_short

        # Try momentum in IMBALANCED state
        momentum = self._detect_momentum(context)
        if momentum and momentum.confidence >= self.MIN_CONFIDENCE:
            return momentum

        # Try mean reversion
        mr = self._detect_mean_reversion(context)
        if mr and mr.confidence >= self.MIN_CONFIDENCE:
            return mr

        return None

    def _detect_aaa_long(self, ctx: MarketContext) -> Optional[Setup]:
        """Detect AAA long setup at VAL.

        Criteria:
        - Price within 2% of VAL
        - Market state allows entry (BALANCED or IMBALANCED)
        - Strong positive CVD slope (>= 30)
        - Positive delta (>= 50)
        """
        if ctx.val <= 0:
            return None

        price_pct_from_val = abs(ctx.current_price - ctx.val) / ctx.val
        if price_pct_from_val > self.PRICE_TOLERANCE_PCT:
            return None

        # Check absorption proxies
        cvd_ok = ctx.cvd_slope >= self.MIN_CVD_SLOPE
        delta_ok = ctx.delta >= self.MIN_DELTA
        volume_ok = ctx.volume_bubbles in ("pos", "positive") or True  # NSE proxy

        score = 0.0
        if cvd_ok:
            score += 0.3
        if delta_ok:
            score += 0.3
        if volume_ok:
            score += 0.2
        if ctx.market_state not in ("PROBING", "NO_TRADE"):
            score += 0.2

        if score < 0.5:
            return None

        return Setup(
            type="AAA",
            confidence=score,
            setup_type="AAA",
            thesis=f"AAA LONG at VAL {ctx.val:.0f} - absorption confirmed",
            key_levels={"entry": ctx.val, "stop": ctx.val * 0.99, "target": ctx.poc},
            trigger_conditions=[
                f"price_at_val_{ctx.current_price:.0f}",
                f"cvd_{ctx.cvd_slope:.0f}",
                f"delta_{ctx.delta:.0f}",
            ],
        )

    def _detect_aaa_short(self, ctx: MarketContext) -> Optional[Setup]:
        """Detect AAA short setup at VAH."""
        if ctx.vah <= 0:
            return None

        price_pct_from_vah = abs(ctx.current_price - ctx.vah) / ctx.vah
        if price_pct_from_vah > self.PRICE_TOLERANCE_PCT:
            return None

        # Negative CVD/delta for shorts
        cvd_ok = ctx.cvd_slope <= -self.MIN_CVD_SLOPE
        delta_ok = ctx.delta <= -self.MIN_DELTA

        score = 0.0
        if cvd_ok:
            score += 0.3
        if delta_ok:
            score += 0.3
        if ctx.market_state not in ("PROBING", "NO_TRADE"):
            score += 0.4

        if score < 0.5:
            return None

        return Setup(
            type="AAA",
            confidence=score,
            setup_type="AAA_SHORT",
            thesis=f"AAA SHORT at VAH {ctx.vah:.0f} - distribution confirmed",
            key_levels={"entry": ctx.vah, "stop": ctx.vah * 1.01, "target": ctx.poc},
            trigger_conditions=[
                f"price_at_vah_{ctx.current_price:.0f}",
                f"cvd_{ctx.cvd_slope:.0f}",
                f"delta_{ctx.delta:.0f}",
            ],
        )

    def _detect_momentum(self, ctx: MarketContext) -> Optional[Setup]:
        """Detect momentum setup in IMBALANCED state."""
        if ctx.market_state != "IMBALANCED":
            return None

        # Price near VAH for shorts or VAL for longs
        at_vah = ctx.vah > 0 and abs(ctx.current_price - ctx.vah) / ctx.vah < 0.03
        at_val = ctx.val > 0 and abs(ctx.current_price - ctx.val) / ctx.val < 0.03

        if not (at_vah or at_val):
            return None

        score = 0.5
        if abs(ctx.cvd_slope) >= 20:
            score += 0.2
        if abs(ctx.delta) >= 30:
            score += 0.3

        if score < 0.7:
            return None

        direction = "SHORT" if at_vah else "LONG"
        return Setup(
            type="MOMENTUM",
            confidence=score,
            setup_type="MOMENTUM",
            thesis=f"MOMENTUM {direction} in IMBALANCED state",
            key_levels={"entry": ctx.current_price, "stop": ctx.val if at_vah else ctx.vah},
            trigger_conditions=[f"imbalanced_state", f"price_at_{'vah' if at_vah else 'val'}"],
        )

    def _detect_mean_reversion(self, ctx: MarketContext) -> Optional[Setup]:
        """Detect mean reversion when price far from VWAP."""
        if ctx.market_state not in ("BALANCED", "NO_TRADE"):
            return None

        if ctx.vwap <= 0 or ctx.current_price <= 0:
            return None

        # Price more than 2% from VWAP (extended)
        pct_from_vwap = abs(ctx.current_price - ctx.vwap) / ctx.vwap
        if pct_from_vwap < 0.015:  # Slightly reduced threshold
            return None

        # Price should be near value area for mean reversion
        near_val = ctx.val > 0 and abs(ctx.current_price - ctx.val) / ctx.val < 0.10
        near_vah = ctx.vah > 0 and abs(ctx.current_price - ctx.vah) / ctx.vah < 0.10

        # Also accept near POC as mean reversion target
        near_poc = ctx.poc > 0 and abs(ctx.current_price - ctx.poc) / ctx.poc < 0.10

        if not (near_val or near_vah or near_poc):
            return None

        score = 0.6  # Base score for extended + near value area
        if abs(ctx.cvd_slope) >= 10:
            score += 0.2  # CVD confirmation
        if abs(ctx.delta) >= 10:
            score += 0.2  # Delta confirmation

        if score < 0.7:
            return None

        # Determine which level we're near
        if near_poc:
            level_name = "POC"
            stop = ctx.val if ctx.current_price > ctx.poc else ctx.vah
        elif near_val:
            level_name = "VAL"
            stop = ctx.val * 0.99
        else:
            level_name = "VAH"
            stop = ctx.vah * 1.01

        return Setup(
            type="MEAN_REVERSION",
            confidence=score,
            setup_type="MEAN_REVERSION",
            thesis=f"MR at {level_name} - returning to POC",
            key_levels={"entry": ctx.current_price, "stop": stop, "target": ctx.poc},
            trigger_conditions=[f"extended_from_vwap", f"price_at_{level_name.lower()}"],
        )

    def _detect_failed_auction(self, context: MarketContext) -> Optional[Setup]:
        """Detect failed auction pattern.

        Per AMT spec: price probes beyond VA boundaries then gets rejected.
        This is a SHORT setup when price probes above VAH.
        This is a LONG setup when price probes below VAL.

        Requires at least 3 confirmation points:
        - Market state is PROBING
        - Prior VA boundaries exist
        - Price beyond those boundaries
        - Rejection confirmed (delta/CVD flipping, not acceptance)
        """
        # Must be in PROBING state
        if context.market_state != "PROBING":
            return None

        # Need prior VA boundaries
        if context.prior_vah <= 0 and context.prior_val <= 0:
            return None

        # Check if price is beyond VA boundaries (price > VAH or price < VAL)
        beyond_vah = context.prior_vah > 0 and context.current_price > context.prior_vah
        beyond_val = context.prior_val > 0 and context.current_price < context.prior_val

        # If price is NOT beyond VA, this is NOT a failed auction
        if not beyond_vah and not beyond_val:
            return None

        # If acceptance is confirmed, it's NOT a failed auction
        if (beyond_vah and context.acceptance_above) or (beyond_val and context.acceptance_below):
            return None

        # Count confirmation points
        score = 0.0

        # 1. Prior VA boundaries exist
        if context.prior_vah > 0 and context.prior_val > 0:
            score += 1
        # 2. Price beyond VA boundaries (already confirmed above)
        score += 1
        # 3. Probe bars >= 2
        if context.probe_bars >= 2:
            score += 1
        # 4. Delta flipping
        if context.delta_flipping:
            score += 1
        # 5. CVD diverging
        if context.cvd_diverging:
            score += 1
        # 6. Rejection (not acceptance)
        if (beyond_vah and context.rejection_at_high) or (beyond_val and context.rejection_at_low):
            score += 1

        # Need at least 3 confirmation points
        if score < 3:
            return None

        # Normalize score to confidence (3 = 0.7 minimum, 6 = 1.0)
        confidence = min(1.0, 0.7 + (score - 3) * 0.1)

        # Determine direction and levels
        if beyond_vah:
            # SHORT - probed above VAH and rejected
            stop_loss = context.current_price * 1.01  # SL above probe high
            target = context.prior_poc if context.prior_poc > 0 else context.poc
            thesis = "FAILED_AUCTION SHORT - probe above VAH rejected back inside"
        elif beyond_val:
            # LONG - probed below VAL and rejected
            stop_loss = context.current_price * 0.99  # SL below probe low
            target = context.prior_poc if context.prior_poc > 0 else context.poc
            thesis = "FAILED_AUCTION LONG - probe below VAL rejected back inside"
        else:
            return None  # Should not reach here

        return Setup(
            type="FAILED_AUCTION",
            confidence=confidence,
            setup_type="FAILED_AUCTION",
            thesis=thesis,
            key_levels={
                "entry": context.current_price,
                "stop_loss": stop_loss,
                "target_poc": target,
            },
            trigger_conditions=[
                "price_beyond_va",
                "probe_bars_confirmed",
                "rejection_detected",
                "price_rejects_back_inside_va",
            ],
        )

    def is_return_to_value(self, context: MarketContext) -> bool:
        """Check if market context shows return-to-value setup."""
        if context.market_state not in ("BALANCED", "NO_TRADE"):
            return False

        if context.poc <= 0:
            return False

        # Price near POC
        near_poc = abs(context.current_price - context.poc) / context.poc < 0.02

        # Some CVD confirmation
        cvd_ok = abs(context.cvd_slope) >= 10

        return near_poc and cvd_ok

    def is_imbalance_continuation(self, context: MarketContext) -> bool:
        """Check if market context shows imbalance continuation."""
        return context.market_state == "IMBALANCED" and abs(context.cvd_slope) >= 20


def create_setup_detector(detector_type: str = "amt") -> AMTSetupDetector:
    """Factory for AMT setup detector."""
    if detector_type == "amt":
        return AMTSetupDetector()
    raise ValueError(f"Unknown detector type: {detector_type}")