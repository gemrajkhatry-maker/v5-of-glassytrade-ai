"""VP Contract Selector — Volume Profile based contract selection.

Implements the Fabio AMT methodology for selecting option contracts:
1. Volume Profile computation (VAH, VAL, POC, LVNs, HVNs)
2. Market State classification (BULLISH/BEARISH/BALANCE)
3. LVN-based entry zone identification
4. Risk-Reward filtering (R:R ≥ threshold)
5. Multi-index selection across NIFTY, BANKNIFTY, FINNIFTY

This replaces the momentum-based option_scanner with a structure-driven approach
that uses Volume Profile levels to find high-conviction entry zones.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import FrozenSet

from app.domain.trading.models.value_objects import OHLC

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VolumeProfile:
    """Computed Volume Profile from OHLCV data."""

    poc: float
    value_area_high: float
    value_area_low: float
    lvns: tuple[float, ...]  # Low Volume Nodes (gap zones / entry levels)
    hvns: tuple[float, ...]  # High Volume Nodes (support/resistance)
    total_volume: float
    bucket_count: int


@dataclass(frozen=True)
class MarketState:
    """Market state from VP analysis."""

    state: str  # "BULLISH", "BEARISH", "BALANCE"
    price: float
    vah: float
    val: float
    poc: float
    distance_to_vah: float
    distance_to_val: float


@dataclass(frozen=True)
class VPContractCandidate:
    """A contract candidate selected by VP analysis."""

    symbol: str
    underlying: str
    option_type: str  # "CE" or "PE"
    strike: int
    entry_price: float  # LVN mid-price
    stop_price: float  # HVN level
    target_price: float  # VAH or VAL
    rr_ratio: float
    market_state: str
    lvn_zone: str  # Description of the LVN zone


@dataclass(frozen=True)
class VPSelectionResult:
    """Result of multi-index VP contract selection."""

    candidates: tuple[VPContractCandidate, ...]
    market_states: dict[str, MarketState]
    total_contracts: int


class VPContractSelector:
    """Volume Profile based contract selector.

    Uses yesterday's OHLCV data to compute Volume Profile levels,
    classifies market state, and selects option contracts based on
    LVN entry zones with R:R filtering.
    """

    # Index/underlying configuration — exchange-aware
    NSE_INDICES: tuple[str, ...] = ("NIFTY", "BANKNIFTY", "FINNIFTY")
    MCX_UNDERLYINGS: tuple[str, ...] = ("CRUDEOIL", "NATURALGAS", "GOLD", "SILVER")

    STRIKE_INTERVALS: dict[str, int] = {
        "NIFTY": 50,
        "BANKNIFTY": 100,
        "FINNIFTY": 50,
        "CRUDEOIL": 50,
        "NATURALGAS": 5,
        "GOLD": 100,
        "SILVER": 500,
    }

    # VP bucket size (in price units)
    BUCKET_SIZES: dict[str, float] = {
        "NIFTY": 10.0,
        "BANKNIFTY": 25.0,
        "FINNIFTY": 10.0,
        "CRUDEOIL": 10.0,
        "NATURALGAS": 1.0,
        "GOLD": 10.0,
        "SILVER": 25.0,
    }

    # Imbalance threshold (points beyond VA for BULLISH/BEARISH)
    IMBALANCE_THRESHOLDS: dict[str, float] = {
        "NIFTY": 50.0,
        "BANKNIFTY": 100.0,
        "FINNIFTY": 50.0,
        "CRUDEOIL": 20.0,
        "NATURALGAS": 5.0,
        "GOLD": 50.0,
        "SILVER": 100.0,
    }

    # Minimum R:R to keep a contract
    MIN_RR_RATIO: float = 2.5

    # LVN threshold: volume < 15% of average
    LVN_THRESHOLD_PCT: float = 0.15

    # HVN threshold: volume > 150% of average
    HVN_THRESHOLD_PCT: float = 1.50

    # Value Area: 70% of total volume
    VALUE_AREA_PCT: float = 0.70

    def __init__(self, broker, exchange: str = "NSE", default_underlyings: list[str] | None = None) -> None:
        self._broker = broker
        self._exchange = exchange
        self._default_underlyings = default_underlyings or []

    def select_contracts(
        self,
        current_prices: dict[str, float] | None = None,
        min_rr: float | None = None,
    ) -> VPSelectionResult:
        """Select contracts for all indices using VP analysis.

        Args:
            current_prices: Optional override for current prices {index: price}.
                           If None, fetches from broker.
            min_rr: Optional override for minimum R:R ratio.

        Returns:
            VPSelectionResult with selected candidates and market states.
        """
        if min_rr is None:
            min_rr = self.MIN_RR_RATIO

        all_candidates: list[VPContractCandidate] = {}
        market_states: dict[str, MarketState] = {}

        # Select underlyings based on exchange
        if self._exchange == "MCX":
            underlyings = self.MCX_UNDERLYINGS
        else:
            underlyings = self.NSE_INDICES

        for index in underlyings:
            try:
                # Step 1: Get yesterday's data and compute VP
                ohlcv_data = self._fetch_yesterday_data(index)
                if not ohlcv_data:
                    logger.warning("No yesterday data for %s — skipping", index)
                    continue

                vp = self._compute_volume_profile(ohlcv_data, index)
                if vp is None:
                    logger.warning("VP computation failed for %s — skipping", index)
                    continue

                # Step 2: Get current price
                if current_prices and index in current_prices:
                    price = current_prices[index]
                else:
                    price = self._fetch_current_price(index)
                if price <= 0:
                    logger.warning("No current price for %s — skipping", index)
                    continue

                # Step 3: Classify market state
                ms = self._classify_market_state(price, vp, index)
                market_states[index] = ms

                logger.info(
                    "VP %s: price=%.2f POC=%.2f VAH=%.2f VAL=%.2f state=%s "
                    "LVNs=%s HVNs=%s",
                    index,
                    price,
                    vp.poc,
                    vp.value_area_high,
                    vp.value_area_low,
                    ms.state,
                    [f"{l:.0f}" for l in vp.lvns],
                    [f"{h:.0f}" for h in vp.hvns],
                )

                # Step 4: Select contracts based on state
                candidates = self._select_by_state(index, vp, ms, min_rr)
                all_candidates.setdefault(index, []).extend(candidates)

            except Exception as e:
                logger.error("VP selection failed for %s: %s", index, e)

        # Flatten candidates
        flat = []
        for idx_candidates in all_candidates.values():
            flat.extend(idx_candidates)

        return VPSelectionResult(
            candidates=tuple(flat),
            market_states=market_states,
            total_contracts=len(flat),
        )

    def _fetch_yesterday_data(self, index: str) -> list[OHLC] | None:
        """Fetch yesterday's OHLCV data for volume profile computation."""
        try:
            import asyncio
            from datetime import datetime, timedelta, timezone

            from app.shared.timezones import IST as ist
            now = datetime.now(ist)

            # Build symbol for the index future
            symbol = f"{index} {now.strftime('%d %b').upper()} FUT"

            # Run async fetch_history in sync context
            loop = asyncio.new_event_loop()
            try:
                data = loop.run_until_complete(
                    self._broker.fetch_history(
                        symbol=symbol,
                        interval="5",
                        limit=200,
                    )
                )
            finally:
                loop.close()

            if data and len(data) > 0:
                return list(data[-200:])  # Last 200 candles
            return None

        except Exception as e:
            logger.error("Failed to fetch yesterday data for %s: %s", index, e)
            return None

    def _fetch_current_price(self, index: str) -> float:
        """Fetch current price for an index."""
        try:
            # Try to get from broker's latest quote
            quote = self._broker.get_quote(index, "NFO")
            if quote and hasattr(quote, "last_price"):
                return float(quote.last_price)
            return 0.0
        except Exception:
            return 0.0

    def _compute_volume_profile(
        self, data: list[OHLC], index: str
    ) -> VolumeProfile | None:
        """Compute Volume Profile from OHLCV data.

        Step 1: Volume Profile Computation
        - Build histogram: Group volume by price buckets
        - Find POC: Bucket with highest volume
        - Build Value Area (70% rule)
        - Identify LVNs: Buckets with volume < 15% of average
        - Identify HVNs: Buckets with volume > 150% of average
        """
        if not data:
            return None

        bucket_size = self.BUCKET_SIZES.get(index, 10.0)

        # Build volume histogram
        volume_by_price: dict[float, float] = {}
        total_volume = 0.0

        for candle in data:
            close_price = float(candle.close)
            volume = float(candle.volume) if candle.volume else 1.0

            # Round to bucket
            bucket = round(close_price / bucket_size) * bucket_size
            volume_by_price[bucket] = volume_by_price.get(bucket, 0.0) + volume
            total_volume += volume

        if not volume_by_price or total_volume <= 0:
            return None

        # Find POC: bucket with highest volume
        poc = max(volume_by_price, key=volume_by_price.get)
        poc_volume = volume_by_price[poc]

        # Compute average volume per bucket
        avg_volume = total_volume / len(volume_by_price)

        # Build Value Area (70% rule)
        vah, val = self._build_value_area(volume_by_price, poc, total_volume)

        # Identify LVNs: volume < 15% of average
        lvns = tuple(
            sorted(
                price
                for price, vol in volume_by_price.items()
                if vol < avg_volume * self.LVN_THRESHOLD_PCT
            )
        )

        # Identify HVNs: volume > 150% of average
        hvns = tuple(
            sorted(
                price
                for price, vol in volume_by_price.items()
                if vol > avg_volume * self.HVN_THRESHOLD_PCT
            )
        )

        return VolumeProfile(
            poc=poc,
            value_area_high=vah,
            value_area_low=val,
            lvns=lvns,
            hvns=hvns,
            total_volume=total_volume,
            bucket_count=len(volume_by_price),
        )

    def _build_value_area(
        self,
        volume_by_price: dict[float, float],
        poc: float,
        total_volume: float,
    ) -> tuple[float, float]:
        """Build Value Area using 70% rule.

        Start at POC, expand up/down adding next highest volume bucket.
        Stop when 70% of total volume captured.
        """
        target_volume = total_volume * self.VALUE_AREA_PCT
        sorted_prices = sorted(volume_by_price.keys())

        if not sorted_prices:
            return poc, poc

        poc_idx = sorted_prices.index(poc)
        captured_volume = volume_by_price[poc]
        vah_idx = poc_idx
        val_idx = poc_idx

        while captured_volume < target_volume:
            above_vol = 0.0
            below_vol = 0.0

            if vah_idx + 1 < len(sorted_prices):
                above_vol = volume_by_price[sorted_prices[vah_idx + 1]]
            if val_idx - 1 >= 0:
                below_vol = volume_by_price[sorted_prices[val_idx - 1]]

            if above_vol >= below_vol and vah_idx + 1 < len(sorted_prices):
                vah_idx += 1
                captured_volume += above_vol
            elif val_idx - 1 >= 0:
                val_idx -= 1
                captured_volume += below_vol
            else:
                break

        vah = sorted_prices[vah_idx]
        val = sorted_prices[val_idx]

        return vah, val

    def _classify_market_state(
        self, price: float, vp: VolumeProfile, index: str
    ) -> MarketState:
        """Classify market state from VP levels.

        Step 2: Market State Classification
        - IF price > VAH + threshold → BULLISH IMBALANCE
        - IF price < VAL - threshold → BEARISH IMBALANCE
        - ELSE → BALANCE
        """
        threshold = self.IMBALANCE_THRESHOLDS.get(index, 50.0)
        distance_to_vah = vp.value_area_high - price
        distance_to_val = price - vp.value_area_low

        if price > vp.value_area_high + threshold:
            state = "BULLISH"
        elif price < vp.value_area_low - threshold:
            state = "BEARISH"
        else:
            state = "BALANCE"

        return MarketState(
            state=state,
            price=price,
            vah=vp.value_area_high,
            val=vp.value_area_low,
            poc=vp.poc,
            distance_to_vah=distance_to_vah,
            distance_to_val=distance_to_val,
        )

    def _select_by_state(
        self,
        index: str,
        vp: VolumeProfile,
        ms: MarketState,
        min_rr: float,
    ) -> list[VPContractCandidate]:
        """Select contracts based on market state.

        Step 3: Contract Selection by State

        BULLISH: LVN below price → CE contract, target VAH, stop at HVN
        BEARISH: LVN above price → PE contract, target VAL, stop at HVN
        BALANCE: Run both, wait for direction confirmation
        """
        candidates: list[VPContractCandidate] = []
        interval = self.STRIKE_INTERVALS.get(index, 50)

        if ms.state == "BULLISH":
            candidates.extend(self._select_bullish(index, vp, ms, interval, min_rr))
        elif ms.state == "BEARISH":
            candidates.extend(self._select_bearish(index, vp, ms, interval, min_rr))
        else:
            # BALANCE: run both
            candidates.extend(self._select_bullish(index, vp, ms, interval, min_rr))
            candidates.extend(self._select_bearish(index, vp, ms, interval, min_rr))

        # Sort by R:R descending, take top 2 per index
        candidates.sort(key=lambda c: -c.rr_ratio)
        return candidates[:2]

    def _select_bullish(
        self,
        index: str,
        vp: VolumeProfile,
        ms: MarketState,
        interval: int,
        min_rr: float,
    ) -> list[VPContractCandidate]:
        """Select CE contracts for BULLISH state.

        For each LVN below current price:
          → Entry zone = LVN mid-price
          → Strike = Round(LVN to nearest lot increment)
          → Stop = HVN below LVN
          → Target = VAH
        """
        candidates = []
        price = ms.price

        for lvn in vp.lvns:
            if lvn >= price:
                continue  # Only LVNs below current price

            # Find HVN below this LVN for stop
            hvn_below = self._find_nearest_hvn(lvn, vp.hvns, direction="below")
            if hvn_below is None:
                continue

            entry = lvn
            stop = hvn_below
            target = ms.vah

            # Minimum SL floor per instrument (prevents guaranteed losses from tight SL)
            min_sl_dist = {
                "NATURALGAS": 0.50,
                "CRUDEOIL": 2.00,
                "NIFTY": 5.00,
                "BANKNIFTY": 15.00,
                "FINNIFTY": 10.00,
            }.get(index, 0.50)
            if abs(entry - stop) < min_sl_dist:
                stop = entry - min_sl_dist  # widen SL to minimum distance

            # Step 4: R:R filter
            risk = abs(entry - stop)
            reward = abs(target - entry)
            if risk <= 0:
                continue
            rr = reward / risk

            if rr < min_rr:
                logger.debug(
                    "%s CE LVN=%.0f: R:R %.2f < %.2f — discarded",
                    index,
                    lvn,
                    rr,
                    min_rr,
                )
                continue

            # Round strike to nearest interval
            strike = round(entry / interval) * interval

            lvn_zone = f"LVN {lvn:.0f}-{lvn + self.BUCKET_SIZES.get(index, 10):.0f}"

            candidates.append(
                VPContractCandidate(
                    symbol=f"{index} CE {strike}",
                    underlying=index,
                    option_type="CE",
                    strike=strike,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=target,
                    rr_ratio=rr,
                    market_state=ms.state,
                    lvn_zone=lvn_zone,
                )
            )

            logger.info(
                "%s CE %d: entry=%.0f stop=%.0f target=%.0f R:R=%.1f (%s)",
                index,
                strike,
                entry,
                stop,
                target,
                rr,
                lvn_zone,
            )

        return candidates

    def _select_bearish(
        self,
        index: str,
        vp: VolumeProfile,
        ms: MarketState,
        interval: int,
        min_rr: float,
    ) -> list[VPContractCandidate]:
        """Select PE contracts for BEARISH state.

        For each LVN above current price:
          → Entry zone = LVN mid-price
          → Strike = Round(LVN to nearest lot increment)
          → Stop = HVN above LVN
          → Target = VAL
        """
        candidates = []
        price = ms.price

        for lvn in vp.lvns:
            if lvn <= price:
                continue  # Only LVNs above current price

            # Find HVN above this LVN for stop
            hvn_above = self._find_nearest_hvn(lvn, vp.hvns, direction="above")
            if hvn_above is None:
                continue

            entry = lvn
            stop = hvn_above
            target = ms.val

            # Minimum SL floor per instrument (prevents guaranteed losses from tight SL)
            min_sl_dist = {
                "NATURALGAS": 0.50,
                "CRUDEOIL": 2.00,
                "NIFTY": 5.00,
                "BANKNIFTY": 15.00,
                "FINNIFTY": 10.00,
            }.get(index, 0.50)
            if abs(entry - stop) < min_sl_dist:
                stop = entry + min_sl_dist  # widen SL to minimum distance (SHORT)

            # Step 4: R:R filter
            risk = abs(stop - entry)
            reward = abs(entry - target)
            if risk <= 0:
                continue
            rr = reward / risk

            if rr < min_rr:
                logger.debug(
                    "%s PE LVN=%.0f: R:R %.2f < %.2f — discarded",
                    index,
                    lvn,
                    rr,
                    min_rr,
                )
                continue

            # Round strike to nearest interval
            strike = round(entry / interval) * interval

            lvn_zone = f"LVN {lvn:.0f}-{lvn + self.BUCKET_SIZES.get(index, 10):.0f}"

            candidates.append(
                VPContractCandidate(
                    symbol=f"{index} PE {strike}",
                    underlying=index,
                    option_type="PE",
                    strike=strike,
                    entry_price=entry,
                    stop_price=stop,
                    target_price=target,
                    rr_ratio=rr,
                    market_state=ms.state,
                    lvn_zone=lvn_zone,
                )
            )

            logger.info(
                "%s PE %d: entry=%.0f stop=%.0f target=%.0f R:R=%.1f (%s)",
                index,
                strike,
                entry,
                stop,
                target,
                rr,
                lvn_zone,
            )

        return candidates

    def _find_nearest_hvn(
        self,
        price: float,
        hvns: tuple[float, ...],
        direction: str = "below",
    ) -> float | None:
        """Find nearest HVN in the given direction."""
        if direction == "below":
            below = [h for h in hvns if h < price]
            return max(below) if below else None
        else:
            above = [h for h in hvns if h > price]
            return min(above) if above else None
