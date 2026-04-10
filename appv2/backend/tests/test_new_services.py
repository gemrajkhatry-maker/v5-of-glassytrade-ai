"""Tests for new domain services."""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from types import SimpleNamespace
from appv2.domain.services.acceptance_rejection import AcceptanceRejectionEngine
from appv2.domain.services.displacement_detector import detect_displacement, compute_atr
from appv2.domain.services.expiry_manager import ExpiryManager
from appv2.domain.services.theta_decay import ThetaDecayAnalyzer
from appv2.domain.services.underlying_router import UnderlyingRouter
from appv2.domain.services.liquidity_filter import LiquidityFilter


def test_acceptance_detection():
    """2+ candles beyond VA = acceptance."""
    engine = AcceptanceRejectionEngine(required_bars=2)

    # Two candles above VAH
    c1 = SimpleNamespace(high=106, low=104, close=105, open=104, range=2, body=1, volume=100)
    c2 = SimpleNamespace(high=107, low=105, close=106, open=105, range=2, body=1, volume=120)

    r1 = engine.update(c1, vah=103, val=97, avg_volume=100)
    assert not r1.accepted  # Only 1 bar

    r2 = engine.update(c2, vah=103, val=97, avg_volume=100)
    assert r2.accepted  # 2 bars


def test_rejection_detection():
    """Rejection wick > 50% of range = rejection."""
    engine = AcceptanceRejectionEngine()  # Fresh engine

    # high=110, low=100, close=100, open=100 → range=10
    # Wick above VAH=102: 110 - max(102, 100, 100) = 8
    # wick_ratio = 8/10 = 80% → rejection
    c = SimpleNamespace(high=110, low=100, close=100, open=100, range=10, body=0, volume=100)

    result = engine.update(c, vah=102, val=95, avg_volume=100)
    assert result.rejected, f"Expected rejection but got {result}"


def test_displacement_detection():
    """Displacement = range > 1.5× ATR + volume > 1.5× avg."""
    candle = SimpleNamespace(
        high=105, low=100, close=104, open=100,
        range=5, body=4, volume=150, is_bullish=True,
    )

    result = detect_displacement(candle, atr=3.0, avg_volume=100)
    assert result.detected
    assert result.direction == "UP"
    assert result.range_ratio == 5 / 3


def test_atr_computation():
    """ATR should compute correctly from candle list."""
    candles = []
    prev_close = 100
    for i in range(20):
        c = SimpleNamespace(
            high=100 + i, low=100 - i, close=100 + (i % 3),
            open=prev_close, volume=100,
        )
        candles.append(c)
        prev_close = c.close

    atr = compute_atr(candles, period=14)
    assert atr > 0


def test_expiry_manager():
    """Expiry manager should correctly identify expiry days."""
    mgr = ExpiryManager()
    from appv2.domain.services.session_context import IST
    from datetime import datetime

    # Test on a non-Thursday
    info = mgr.get_info(datetime(2024, 1, 15, 10, 0, tzinfo=IST))  # Monday
    assert not info.is_expiry_day

    # Test on a Thursday
    info = mgr.get_info(datetime(2024, 1, 18, 10, 0, tzinfo=IST))  # Thursday
    assert info.is_expiry_day

    # Test gamma trap (Thursday after 14:30)
    info = mgr.get_info(datetime(2024, 1, 18, 14, 35, tzinfo=IST))
    assert info.is_gamma_trap


def test_theta_decay_analysis():
    """Theta cost should be computed correctly."""
    analyzer = ThetaDecayAnalyzer(max_theta_cost_pct=20.0)

    result = analyzer.analyze(
        theta=-2.0,  # ₹2/day decay
        hours_to_expiry=6.0,
        expected_profit=10.0,
    )

    assert result.theta_per_hour == pytest.approx(2.0 / 24, abs=0.01)
    assert result.total_theta_cost == pytest.approx(0.5, abs=0.01)
    assert result.theta_cost_pct == pytest.approx(5.0, abs=0.1)
    assert result.is_viable  # 5% < 20%


def test_underlying_router():
    """Router should correctly map options to underlying futures."""
    router = UnderlyingRouter()

    mapping = router.resolve("NIFTY 20 MAR 23400 CE")
    assert mapping.underlying == "NIFTY"
    assert mapping.futures_symbol == "NIFTY"
    assert mapping.is_option

    mapping = router.resolve("CRUDEOIL")
    assert mapping.underlying == "CRUDEOIL"
    assert not mapping.is_option


def test_liquidity_filter():
    """Filter should exclude illiquid contracts."""
    filt = LiquidityFilter(min_oi=10000, min_volume_5min=100, max_spread_bps=50, min_ltp=5.0)

    contracts = [
        {"oi": 50000, "volume": 500, "spread_bps": 20, "ltp": 50},  # Liquid
        {"oi": 500, "volume": 10, "spread_bps": 200, "ltp": 1},  # Illiquid
        {"oi": 20000, "volume": 200, "spread_bps": 30, "ltp": 25},  # Liquid
    ]

    filtered = filt.filter(contracts)
    assert len(filtered) == 2


# Need pytest for approx
import pytest
