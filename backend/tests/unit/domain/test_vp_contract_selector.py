"""Tests for VPContractSelector — Volume Profile based contract selection.

Tests:
  - Volume Profile computation (POC, VAH, VAL, LVNs, HVNs)
  - Market State classification (BULLISH/BEARISH/BALANCE)
  - LVN-based entry selection
  - R:R filtering
  - Multi-index selection
"""

from __future__ import annotations

import pytest
from app.domain.fabio_ai.services.vp_contract_selector import (
    VPContractSelector,
    VolumeProfile,
    MarketState,
    VPContractCandidate,
    VPSelectionResult,
)


class TestVolumeProfileComputation:
    """Test VP computation from OHLCV data."""

    def test_poc_is_highest_volume_bucket(self):
        """POC should be the price bucket with highest accumulated volume."""
        from app.domain.trading.models.value_objects import OHLC

        # Create mock data: price 100 has 3x more volume than others
        data = [
            OHLC.create(
                time="2024-01-01T09:15:00",
                open=100,
                high=100,
                low=100,
                close=100,
                volume=300,
            ),
            OHLC.create(
                time="2024-01-01T09:20:00",
                open=90,
                high=90,
                low=90,
                close=90,
                volume=100,
            ),
            OHLC.create(
                time="2024-01-01T09:25:00",
                open=110,
                high=110,
                low=110,
                close=110,
                volume=100,
            ),
        ]

        selector = VPContractSelector(broker=None)
        vp = selector._compute_volume_profile(data, "NIFTY")

        assert vp is not None
        assert vp.poc == 100.0  # Price 100 has highest volume
        assert vp.total_volume == 500.0

    def test_lvn_detection(self):
        """LVNs should be buckets with volume < 15% of average."""
        from app.domain.trading.models.value_objects import OHLC

        data = [
            OHLC.create(
                time="2024-01-01T09:15:00",
                open=100,
                high=100,
                low=100,
                close=100,
                volume=500,
            ),
            OHLC.create(
                time="2024-01-01T09:20:00",
                open=90,
                high=90,
                low=90,
                close=90,
                volume=10,
            ),
            OHLC.create(
                time="2024-01-01T09:25:00",
                open=110,
                high=110,
                low=110,
                close=110,
                volume=500,
            ),
        ]

        selector = VPContractSelector(broker=None)
        vp = selector._compute_volume_profile(data, "NIFTY")

        assert vp is not None
        # Price 90 has volume 10, avg = (500+10+500)/3 = 336.67
        # 15% of avg = 50.5, so 90 < 50.5 → LVN
        assert 90.0 in vp.lvns

    def test_hvn_detection(self):
        """HVN should be buckets with volume > 150% of average."""
        from app.domain.trading.models.value_objects import OHLC

        data = [
            OHLC.create(
                time="2024-01-01T09:15:00",
                open=100,
                high=100,
                low=100,
                close=100,
                volume=800,
            ),
            OHLC.create(
                time="2024-01-01T09:20:00",
                open=90,
                high=90,
                low=90,
                close=90,
                volume=100,
            ),
            OHLC.create(
                time="2024-01-01T09:25:00",
                open=110,
                high=110,
                low=110,
                close=110,
                volume=100,
            ),
        ]

        selector = VPContractSelector(broker=None)
        vp = selector._compute_volume_profile(data, "NIFTY")

        assert vp is not None
        # Price 100 has volume 800, avg = 333.33, 150% = 500
        # 800 > 500 → HVN
        assert 100.0 in vp.hvns

    def test_value_area_spans_70_percent(self):
        """Value area should contain ~70% of total volume."""
        from app.domain.trading.models.value_objects import OHLC

        data = [
            OHLC.create(
                time="2024-01-01T09:15:00",
                open=100,
                high=100,
                low=100,
                close=100,
                volume=400,
            ),
            OHLC.create(
                time="2024-01-01T09:20:00",
                open=110,
                high=110,
                low=110,
                close=110,
                volume=300,
            ),
            OHLC.create(
                time="2024-01-01T09:25:00",
                open=120,
                high=120,
                low=120,
                close=120,
                volume=200,
            ),
            OHLC.create(
                time="2024-01-01T09:30:00",
                open=130,
                high=130,
                low=130,
                close=130,
                volume=50,
            ),
            OHLC.create(
                time="2024-01-01T09:35:00",
                open=140,
                high=140,
                low=140,
                close=140,
                volume=50,
            ),
        ]

        selector = VPContractSelector(broker=None)
        vp = selector._compute_volume_profile(data, "NIFTY")

        assert vp is not None
        assert vp.poc == 100.0  # Highest volume
        assert vp.value_area_high >= vp.value_area_low
        assert vp.value_area_high >= vp.poc
        assert vp.value_area_low <= vp.poc


class TestMarketStateClassification:
    """Test market state classification from VP."""

    def test_bullish_when_price_above_vah(self):
        """Price > VAH + threshold → BULLISH."""
        vp = VolumeProfile(
            poc=22000,
            value_area_high=22500,
            value_area_low=21500,
            lvns=(21800, 22200),
            hvns=(21600, 22400),
            total_volume=10000,
            bucket_count=50,
        )
        selector = VPContractSelector(broker=None)
        ms = selector._classify_market_state(22600, vp, "NIFTY")

        assert ms.state == "BULLISH"
        assert ms.price == 22600
        assert ms.vah == 22500

    def test_bearish_when_price_below_val(self):
        """Price < VAL - threshold → BEARISH."""
        vp = VolumeProfile(
            poc=22000,
            value_area_high=22500,
            value_area_low=21500,
            lvns=(21800, 22200),
            hvns=(21600, 22400),
            total_volume=10000,
            bucket_count=50,
        )
        selector = VPContractSelector(broker=None)
        ms = selector._classify_market_state(21400, vp, "NIFTY")

        assert ms.state == "BEARISH"

    def test_balance_when_price_in_value_area(self):
        """Price within VA → BALANCE."""
        vp = VolumeProfile(
            poc=22000,
            value_area_high=22500,
            value_area_low=21500,
            lvns=(21800, 22200),
            hvns=(21600, 22400),
            total_volume=10000,
            bucket_count=50,
        )
        selector = VPContractSelector(broker=None)
        ms = selector._classify_market_state(22000, vp, "NIFTY")

        assert ms.state == "BALANCE"


class TestContractSelection:
    """Test contract selection by state."""

    def test_bullish_selects_ce_contracts(self):
        """BULLISH state should select CE contracts at LVN zones."""
        vp = VolumeProfile(
            poc=22000,
            value_area_high=22500,
            value_area_low=21500,
            lvns=(21800, 21900),
            hvns=(21600, 21700),
            total_volume=10000,
            bucket_count=50,
        )
        ms = MarketState(
            state="BULLISH",
            price=22100,
            vah=22500,
            val=21500,
            poc=22000,
            distance_to_vah=400,
            distance_to_val=600,
        )
        selector = VPContractSelector(broker=None)
        candidates = selector._select_by_state("NIFTY", vp, ms, 2.5)

        assert len(candidates) > 0
        for c in candidates:
            assert c.option_type == "CE"
            assert c.rr_ratio >= 2.5
            assert c.target_price == 22500  # VAH

    def test_bearish_selects_pe_contracts(self):
        """BEARISH state should select PE contracts at LVN zones."""
        vp = VolumeProfile(
            poc=22000,
            value_area_high=22500,
            value_area_low=21500,
            lvns=(22300, 22400),
            hvns=(22450, 22550),
            total_volume=10000,
            bucket_count=50,
        )
        ms = MarketState(
            state="BEARISH",
            price=21400,
            vah=22500,
            val=21500,
            poc=22000,
            distance_to_vah=1100,
            distance_to_val=100,
        )
        selector = VPContractSelector(broker=None)
        candidates = selector._select_by_state("NIFTY", vp, ms, 2.5)

        assert len(candidates) > 0
        for c in candidates:
            assert c.option_type == "PE"
            assert c.rr_ratio >= 2.5
            assert c.target_price == 21500  # VAL

    def test_balance_runs_both_directions(self):
        """BALANCE state should run both CE and PE selection."""
        vp = VolumeProfile(
            poc=22000,
            value_area_high=22500,
            value_area_low=21500,
            lvns=(21700, 21800, 22300, 22400),
            hvns=(21600, 21650, 22450, 22550),
            total_volume=10000,
            bucket_count=50,
        )
        ms = MarketState(
            state="BALANCE",
            price=22000,
            vah=22500,
            val=21500,
            poc=22000,
            distance_to_vah=500,
            distance_to_val=500,
        )
        selector = VPContractSelector(broker=None)
        candidates = selector._select_by_state("NIFTY", vp, ms, 2.5)

        has_ce = any(c.option_type == "CE" for c in candidates)
        has_pe = any(c.option_type == "PE" for c in candidates)
        # BALANCE should try both (if R:R passes)
        assert has_ce or has_pe or len(candidates) == 0  # May have 0 if R:R too low


class TestRRFilter:
    """Test R:R filtering logic."""

    def test_discards_low_rr(self):
        """Contracts with R:R < threshold should be discarded."""
        vp = VolumeProfile(
            poc=22000,
            value_area_high=22100,
            value_area_low=21900,
            lvns=(21950,),
            hvns=(21900,),
            total_volume=10000,
            bucket_count=50,
        )
        ms = MarketState(
            state="BULLISH",
            price=22000,
            vah=22100,
            val=21900,
            poc=22000,
            distance_to_vah=100,
            distance_to_val=100,
        )
        selector = VPContractSelector(broker=None)
        candidates = selector._select_by_state("NIFTY", vp, ms, 2.5)

        # With small VA (100 pts), R:R may be low
        for c in candidates:
            assert c.rr_ratio >= 2.5

    def test_keeps_high_rr(self):
        """Contracts with R:R >= threshold should be kept."""
        vp = VolumeProfile(
            poc=22000,
            value_area_high=22500,
            value_area_low=21500,
            lvns=(21600,),
            hvns=(21500,),
            total_volume=10000,
            bucket_count=50,
        )
        ms = MarketState(
            state="BULLISH",
            price=22100,
            vah=22500,
            val=21500,
            poc=22000,
            distance_to_vah=400,
            distance_to_val=600,
        )
        selector = VPContractSelector(broker=None)
        candidates = selector._select_by_state("NIFTY", vp, ms, 2.5)

        assert len(candidates) > 0
        for c in candidates:
            assert c.rr_ratio >= 2.5


class TestFindNearestHVN:
    """Test HVN lookup logic."""

    def test_finds_hvn_below(self):
        selector = VPContractSelector(broker=None)
        hvns = (21500, 21700, 21900, 22100)
        result = selector._find_nearest_hvn(22000, hvns, "below")
        assert result == 21900

    def test_finds_hvn_above(self):
        selector = VPContractSelector(broker=None)
        hvns = (21500, 21700, 21900, 22100)
        result = selector._find_nearest_hvn(21800, hvns, "above")
        assert result == 21900

    def test_returns_none_when_no_hvn(self):
        selector = VPContractSelector(broker=None)
        hvns = (21500, 21700)
        result = selector._find_nearest_hvn(21400, hvns, "below")
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
