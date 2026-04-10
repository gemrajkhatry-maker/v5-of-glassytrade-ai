"""Edge case tests — gap opens, low liquidity, market open volatility, broker failures."""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from types import SimpleNamespace
from appv2.domain.services.market_state_engine import detect_market_state
from appv2.domain.services.session_context import get_session_info, SessionPhase
from appv2.domain.services.gate_pipeline import GateContext, run_gate_pipeline
from appv2.domain.services.liquidity_filter import LiquidityFilter
from appv2.domain.services.order_retry import OrderRetryHandler
from appv2.domain.enums.market_state import MarketState


def test_gap_open_above_vah():
    """Gap open above VAH should trigger PROBING state."""
    # Price gaps way above VAH with no displacement or acceptance
    result = detect_market_state(
        price=120.0,  # Well above VAH=110
        poc=100.0,
        vah=110.0,
        val=90.0,
        tick_size=0.05,
        has_displacement=False,
        has_acceptance=False,
    )
    assert result.state == MarketState.PROBING
    assert "outside" in result.trigger.lower() and "va" in result.trigger.lower()


def test_gap_open_below_val():
    """Gap open below VAL should trigger PROBING state."""
    result = detect_market_state(
        price=80.0,  # Well below VAL=90
        poc=100.0,
        vah=110.0,
        val=90.0,
        tick_size=0.05,
        has_displacement=False,
        has_acceptance=False,
    )
    assert result.state == MarketState.PROBING


def test_low_liquidity_filter():
    """Illiquid contracts should be filtered out."""
    filt = LiquidityFilter(min_oi=10000, min_volume_5min=100, max_spread_bps=50, min_ltp=5.0)

    contracts = [
        # Liquid contract
        {"oi": 50000, "volume": 500, "spread_bps": 20, "ltp": 50},
        # Too low OI
        {"oi": 100, "volume": 500, "spread_bps": 20, "ltp": 50},
        # Too low volume
        {"oi": 50000, "volume": 10, "spread_bps": 20, "ltp": 50},
        # Too wide spread
        {"oi": 50000, "volume": 500, "spread_bps": 200, "ltp": 50},
        # Too low LTP (near zero premium)
        {"oi": 50000, "volume": 500, "spread_bps": 20, "ltp": 1},
    ]

    filtered = filt.filter(contracts)
    assert len(filtered) == 1  # Only the first one passes
    assert filtered[0]["oi"] == 50000


def test_session_phase_opening_noise():
    """Opening phase (09:15-09:30) should not allow entries."""
    from appv2.domain.services.session_context import _to_ist
    from datetime import datetime, timezone, timedelta

    IST = timezone(timedelta(hours=5, minutes=30))

    info = get_session_info(
        timestamp=datetime(2024, 1, 15, 9, 20, tzinfo=IST),  # 09:20 IST
        open_price=100, prior_vah=110, prior_val=90,
        exchange="NSE",
    )
    assert info.phase == SessionPhase.OPENING
    assert not info.allows_entry


def test_order_retry_exponential_backoff():
    """Order retry should use exponential backoff."""
    handler = OrderRetryHandler(max_attempts=3, base_backoff_ms=100)

    # Verify backoff increases exponentially
    backoff_1 = handler._get_backoff_ms(1)
    backoff_2 = handler._get_backoff_ms(2)
    backoff_3 = handler._get_backoff_ms(3)

    assert backoff_2 > backoff_1
    assert backoff_3 > backoff_2
    # Rough check: should be ~2× each time
    assert backoff_2 > backoff_1 * 1.5
    assert backoff_3 > backoff_2 * 1.5


def test_order_retry_max_backoff_cap():
    """Backoff should be capped at max_backoff_ms."""
    handler = OrderRetryHandler(
        max_attempts=10,
        base_backoff_ms=100,
        max_backoff_ms=1000,
    )

    # At attempt 10, raw backoff would be 100 * 2^9 = 51200ms
    # But should be capped at 1000ms
    backoff = handler._get_backoff_ms(10)
    assert backoff <= 1100  # 1000 + 10% jitter


def test_gate_rejects_during_opening_phase():
    """Gates should reject during opening noise phase."""
    ctx = GateContext(
        session_phase="OPENING",
        market_state="BALANCED",
        data_candles=50,
        is_risk_halted=False,
        price=100.0,
        entry_zone=100.0,
        aggression_score=3.0,
        opposing_level=105.0,
        r_r_ratio=2.0,
        tick_age_seconds=5,
        tick_size=0.05,
    )

    passed, reason, detail = run_gate_pipeline(ctx)
    assert not passed
    assert "warmup" in reason.lower() or "Warmup" in reason


def test_market_open_volatility_gate():
    """First 15 minutes should have restricted trading (Phase 1 = NO TRADE)."""
    ctx = GateContext(
        session_phase="OPENING",  # 09:15-09:30
        market_state="NO_TRADE",
        data_candles=5,
        is_risk_halted=False,
        price=100.0,
        entry_zone=100.0,
        aggression_score=0.0,
        opposing_level=105.0,
        r_r_ratio=0.0,
        tick_age_seconds=5,
        tick_size=0.05,
    )

    # Should fail on BOTH session warmup AND NO_TRADE state
    passed, reason, detail = run_gate_pipeline(ctx)
    assert not passed
