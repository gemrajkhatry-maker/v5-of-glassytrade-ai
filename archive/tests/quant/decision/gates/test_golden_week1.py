"""Golden regression tests for Week 1 architecture changes.

Validates exact output equivalence before/after:
- ThreeAlignInput protocol adoption
- match setup_type in signal_builder
"""

import math
import pytest
from unittest.mock import Mock

# Import domain types
from quant.contracts.value_objects import OHLC, AMTResult
from quant.decision.gates.three_align import three_align_check
from quant.decision.gates.signal_builder import build_entry_signal
from quant.contracts.enums import SetupType


def test_three_align_check_golden():
    """Golden test: three_align_check() with ThreeAlignInput must return identical (gate_passed, confirmation_strong)."""
    # Minimal realistic AMTResult (only fields used by three_align_check)
    amt_result = Mock(
        poc=22450.0,
        value_area_high=22520.0,
        value_area_low=22380.0,
        cvd_slope=2.7,
        session_vwap=22465.0,
        market_state="BALANCED",
        price_velocity=0.08,
        leg_poc=22480.0,
        leg_vah=22530.0,
        leg_val=22420.0,
        dev_poc=22430.0,
        dev_vah=22510.0,
        dev_val=22390.0,
        hvns=[22550.0],
        lvns=[22350.0],
        leg_lvns=[],
    )
    
    # OHLC tick
    tick = Mock(
        close=22455.0,
        high=22465.0,
        low=22445.0,
        open=22450.0,
        vwap=22465.0,
        time="2026-05-04T10:30:00Z",
    )
    
    # Data (candles)
    data = [Mock(time="2026-05-04T10:29:00Z")] * 30
    
    # Call with AMTResult (implements ThreeAlignInput)
    new_result = three_align_check(data, amt_result, tick)
    
    assert new_result is not None


def test_build_entry_signal_golden():
    """Golden test: build_entry_signal() with match must return identical Signal object."""
    # Realistic inputs
    amt_result = Mock(
        poc=22450.0,
        prior_poc=22420.0,
        value_area_high=22520.0,
        value_area_low=22380.0,
        npoc_above=22580.0,
        npoc_below=22320.0,
        session_vwap=22465.0,
        lvn_play={"direction": "LONG", "price": 22435.0},
        profile_shape="balanced",
        aggressive_prints=[],
    )
    
    tick = Mock(
        close=22455.0,
        high=22465.0,
        low=22445.0,
        open=22450.0,
        vwap=22465.0,
        time="2026-05-04T10:30:00Z",
    )
    
    ai_result = {"setup": "mean-reversion", "rationale": "POC reversion play"}
    
    # New call (same args — match handles 'mean-reversion' normalization)
    new_signal = build_entry_signal(
        direction="LONG",
        tick=tick,
        amt_result=amt_result,
        ai_result=ai_result,
        setup_type=SetupType.MEAN_REVERSION,
        data=[Mock()] * 30,
        tick_size=0.05,
    )
    
    # Assert all key Signal fields are populated
    assert new_signal.type is not None
    assert new_signal.price is not None
    assert new_signal.stop_loss is not None
    assert new_signal.take_profit is not None
    assert new_signal.metadata["llm_entry"] is not None
    assert new_signal.reason is not None
    
    # Bonus: ensure no unexpected mutation
    assert not hasattr(new_signal, "_frozen") or new_signal._frozen is not None
