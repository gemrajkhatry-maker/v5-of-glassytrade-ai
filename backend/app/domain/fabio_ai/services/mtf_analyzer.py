"""Multi-Timeframe AMT Analyzer — Aligning Daily/Hourly/5M auctions.

Implements Fabio AMT methodology:
- Daily: Structural Bias (VAH/VAL)
- 1H: Execution Bias (POC/VA)
- 5M: Entry (LVN Play / Re-test)

Alignment logic:
- BULLISH if 5M > 1H VAH AND 1H > Daily VAH
- BEARISH if 5M < 1H VAL AND 1H < Daily VAL
- BALANCE if 5M inside 1H VA
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.domain.services.volume_profile import create_profile
from app.domain.fabio_ai.services.market_state_engine import detect_market_state

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, AMTResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MTFLevel:
    poc: float
    vah: float
    val: float
    state: str  # "BULLISH", "BEARISH", "BALANCE"


@dataclass(frozen=True)
class MTFAlignmentResult:
    alignment: str  # "ALIGNED_BULLISH", "ALIGNED_BEARISH", "DIVERGENT", "BALANCE"
    daily: MTFLevel
    hourly: MTFLevel
    confidence: float


class MultiTimeframeAMTAnalyzer:
    """Orchestrates multi-timeframe auction alignment."""

    def __init__(self, broker=None) -> None:
        self._broker = broker
        self._daily_ohlc: list[OHLC] = []
        self._hourly_ohlc: list[OHLC] = []

    def compute_alignment(
        self,
        current_price: float,
        daily_ohlc: list[OHLC],
        hourly_ohlc: list[OHLC],
    ) -> MTFAlignmentResult:
        """Compute the MTF alignment based on provided OHLC data."""

        # 1. Daily Level (Structural)
        d_profile = create_profile(daily_ohlc, buckets=100)
        d_poc, d_vah, d_val = self._extract_va(d_profile)
        d_state = self._detect_basic_state(current_price, d_vah, d_val)

        # 2. Hourly Level (Execution)
        h_profile = create_profile(hourly_ohlc, buckets=100)
        h_poc, h_vah, h_val = self._extract_va(h_profile)
        h_state = self._detect_basic_state(current_price, h_vah, h_val)

        # 3. Alignment Logic
        alignment = "DIVERGENT"
        if d_state == "BULLISH" and h_state == "BULLISH":
            alignment = "ALIGNED_BULLISH"
        elif d_state == "BEARISH" and h_state == "BEARISH":
            alignment = "ALIGNED_BEARISH"
        elif d_state == "BALANCE" and h_state == "BALANCE":
            alignment = "BALANCE"

        return MTFAlignmentResult(
            alignment=alignment,
            daily=MTFLevel(poc=d_poc, vah=d_vah, val=d_val, state=d_state),
            hourly=MTFLevel(poc=h_poc, vah=h_vah, val=h_val, state=h_state),
            confidence=0.8 if alignment != "DIVERGENT" else 0.4,
        )

    def _extract_va(self, profile):
        """Simple VA extraction for higher timeframes."""
        if not profile:
            return 0, 0, 0
        total_vol = sum(p.volume for p in profile)
        max_vol = max(p.volume for p in profile)
        poc = next(p.price for p in profile if p.volume == max_vol)
        
        # 70% VA
        target = total_vol * 0.7
        curr = max_vol
        sorted_p = sorted(profile, key=lambda p: p.price)
        poc_idx = next(i for i, p in enumerate(sorted_p) if p.price == poc)
        up, dn = poc_idx, poc_idx
        while curr < target and (up + 1 < len(sorted_p) or dn - 1 >= 0):
            up_v = sorted_p[up+1].volume if up+1 < len(sorted_p) else 0
            dn_v = sorted_p[dn-1].volume if dn-1 >= 0 else 0
            if up_v >= dn_v and up+1 < len(sorted_p):
                up += 1
                curr += up_v
            elif dn-1 >= 0:
                dn -= 1
                curr += dn_v
            else:
                break
        
        return poc, sorted_p[up].price, sorted_p[dn].price

    def _detect_basic_state(self, price, vah, val):
        if price > vah: return "BULLISH"
        if price < val: return "BEARISH"
        return "BALANCE"
