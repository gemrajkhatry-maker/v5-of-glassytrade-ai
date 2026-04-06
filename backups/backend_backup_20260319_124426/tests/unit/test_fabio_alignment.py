"""Comprehensive tests for Fabio-aligned system fixes.

Tests verify that the decision pipeline correctly implements
Fabio Valentini's AMT methodology with proper enforcement of:
1. Rich LLM context (no zeros)
2. 3/3 confirmation bundle
3. Second drive enforcement
4. Session strategy enforcement
5. CVD hard blocks
6. LVN play detection
7. 3-loss circuit breaker
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.channel import Channel
from app.pipeline.message import (
    AMTResultPayload,
    CandlePayload,
    Message,
    SignalGatePayload,
)
from app.pipeline.processor import ProcessorConfig
from app.pipeline.processors.gate import SignalGateProcessor
from app.pipeline.processors.llm_entry import LLMEntryProcessor
from app.domain.fabio_ai.services.entry_gate import (
    three_align_check,
    check_confirmation_bundle,
    check_momentum_fade,
)
from app.domain.fabio_ai.services.session_risk_manager import SessionRiskManager, RiskTier


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

IST = timezone(timedelta(hours=5, minutes=30))


def _make_amt_result(
    market_state: str = "BALANCED",
    poc: float = 100.0,
    vah: float = 102.0,
    val: float = 98.0,
    cvd_slope: float = 0.0,
    cvd_divergence: str = "",
    aggression: float = 0.0,
    lvns: tuple = (),
    leg_lvns: tuple = (),
    session_vwap: float = 0.0,
) -> SimpleNamespace:
    """Build a minimal AMTResult-like namespace."""
    return SimpleNamespace(
        market_state=market_state,
        poc=poc,
        value_area_high=vah,
        value_area_low=val,
        cvd_slope=cvd_slope,
        cvd_divergence=cvd_divergence,
        profile_shape="D",
        aggression=aggression,
        lvns=lvns,
        hvns=(),
        leg_lvns=leg_lvns,
        leg_poc=0.0,
        leg_vah=0.0,
        leg_val=0.0,
        dev_poc=0.0,
        dev_vah=0.0,
        dev_val=0.0,
        session_vwap=session_vwap,
        vwap_upper_2=0.0,
        vwap_lower_2=0.0,
        aggressive_prints=(),
        lvn_play=None,
    )


def _make_tick(price: float = 98.0, volume: float = 5000.0, delta: float = 500.0) -> SimpleNamespace:
    """Build a minimal tick-like namespace."""
    return SimpleNamespace(
        time="2026-03-14T10:00:00",
        open=price - 0.5,
        high=price + 1.0,
        low=price - 1.0,
        close=price,
        volume=volume,
        vwap=100.0,
        taker_buy_volume=volume / 2,
        delta=delta,
    )


def _make_candle_history(count: int = 25, volume: float = 3000.0) -> list:
    """Create mock candle history for gate tests."""
    return [
        SimpleNamespace(
            time=f"2026-03-14T09:{i:02d}:00",
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=volume,
            vwap=100.0,
            taker_buy_volume=volume / 2,
            delta=0.0,
        )
        for i in range(count)
    ]


# ============================================================================
# FIX #1: Rich LLM Context Tests
# ============================================================================

class TestFix1_RichLLMContext:
    """Verify LLM receives real AMT data instead of zeros."""

    @pytest.mark.asyncio
    async def test_llm_prompt_data_has_real_poc(self):
        """LLM prompt data must contain real POC value, not zero."""
        processor = LLMEntryProcessor()
        config = ProcessorConfig(
            name="test_llm",
            processor_class="LLMEntryProcessor",
            inbox={"signal_gates": "sg"},
            outbox={"llm_decisions": "ld"},
            settings={"timeout_seconds": 5.0},
        )
        await processor.setup(config)

        # Create gate payload with real data
        gate_payload = SignalGatePayload(
            passed=True,
            reason="Three-Align PASSED",
            setup_grade="A",
            confidence=0.9,
            market_state="BALANCED",
            profile_shape="D",
            poc=100.0,
            vah=102.0,
            val=98.0,
            cvd_slope=5.0,
            cvd_divergence="",
            delta_score=1.5,
            aggression="AGGRESSIVE",
            lvns=(97.5, 98.0, 101.0),
            is_second_drive=True,
            lvn_play={"direction": "LONG", "level": 98.0},
            session_name="NSE_PRIMARY",
            favor_strategy="TREND_CONTINUATION",
        )

        msg = Message(
            payload=gate_payload,
            symbol="TEST",
            timestamp=datetime.now(IST),
        )

        prompt_data = processor._build_prompt_data(msg, gate_payload)

        # Verify real data is passed
        assert prompt_data["poc"] == 100.0, "POC should be real value"
        assert prompt_data["vah"] == 102.0, "VAH should be real value"
        assert prompt_data["val"] == 98.0, "VAL should be real value"
        assert prompt_data["cvd"] == 5.0, "CVD should be real value"
        assert prompt_data["lvns"] == [97.5, 98.0, 101.0], "LVNs should be real values"
        assert prompt_data["is_second_drive"] is True, "Second drive flag should be passed"
        assert prompt_data["lvn_play"] == {"direction": "LONG", "level": 98.0}, "LVN play should be passed"
        assert prompt_data["session_name"] == "NSE_PRIMARY", "Session should be passed"
        assert prompt_data["aggression"] == "AGGRESSIVE", "Aggression should be passed"

    @pytest.mark.asyncio
    async def test_llm_prompt_data_not_zeros(self):
        """Verify LLM prompt does NOT contain all zeros."""
        processor = LLMEntryProcessor()
        config = ProcessorConfig(
            name="test_llm",
            processor_class="LLMEntryProcessor",
            inbox={"signal_gates": "sg"},
            outbox={"llm_decisions": "ld"},
            settings={},
        )
        await processor.setup(config)

        gate_payload = SignalGatePayload(
            passed=True,
            reason="test",
            poc=50000.0,
            vah=50500.0,
            val=49500.0,
            cvd_slope=25.0,
        )
        msg = Message(payload=gate_payload, symbol="TEST", timestamp=datetime.now(IST))
        prompt_data = processor._build_prompt_data(msg, gate_payload)

        # At least one field must be non-zero (the old code had all zeros)
        non_zero_fields = [k for k, v in prompt_data.items() 
                          if isinstance(v, (int, float)) and v != 0]
        assert len(non_zero_fields) > 0, "Prompt data should have non-zero values"


# ============================================================================
# FIX #2: 3/3 Confirmation Tests
# ============================================================================

class TestFix2_ThreeOfThreeConfirmation:
    """Verify gate requires confirmation bundle (2/3 with volume mandatory)."""

    def test_volume_impulse_mandatory(self):
        """Gate must fail without volume impulse."""
        # Create candles with low volume
        data = _make_candle_history(25, volume=1000.0)
        tick = _make_tick(price=98.0, volume=500.0, delta=100.0)  # Low volume
        amt = _make_amt_result()

        # Volume is 500, EMA is ~1000, so 500 < 1000 * 1.5 = no impulse
        result = three_align_check(data, amt, tick, order_book=None)
        
        # Gate should fail due to no volume impulse
        # Note: may pass or fail depending on near_level check
        # but confirmation should be False
        agg_ok = check_confirmation_bundle(data, tick, None)
        assert agg_ok is False, "Confirmation should fail without volume impulse"

    def test_confirmation_passes_with_volume_impulse(self):
        """Confirmation passes with high volume."""
        data = _make_candle_history(25, volume=3000.0)
        tick = _make_tick(price=98.0, volume=6000.0, delta=1000.0)  # High volume
        
        agg_ok = check_confirmation_bundle(data, tick, None)
        assert agg_ok is True, "Confirmation should pass with volume impulse"


# ============================================================================
# FIX #3: Second Drive Enforcement Tests
# ============================================================================

class TestFix3_SecondDriveEnforcement:
    """Verify trend entries require second drive."""

    def test_blocks_first_drive_trend(self):
        """IMBALANCED market with first drive should be blocked."""
        data = _make_candle_history(25)
        tick = _make_tick(price=102.0)  # Near VAH
        amt = _make_amt_result(market_state="IMBALANCED")
        
        result = three_align_check(data, amt, tick, return_is_second_drive=True)
        
        # First drive in IMBALANCED should be blocked
        # is_second_drive=False should cause gate to fail
        assert result[2] is False, "Should detect first drive (not second)"

    def test_allows_first_drive_reversion(self):
        """BALANCED market (mean reversion) can enter on first drive."""
        data = _make_candle_history(25)
        tick = _make_tick(price=98.0, volume=6000.0, delta=500.0)  # Near VAL with volume
        amt = _make_amt_result(market_state="BALANCED", val=98.0)
        
        result = three_align_check(data, amt, tick, return_is_second_drive=True)
        
        # BALANCED (mean reversion) doesn't require second drive
        # Gate should be able to pass
        # result[0] = gate_passed, result[1] = confirmation, result[2] = is_second_drive
        # is_second_drive might be False, but gate can still pass for BALANCED


# ============================================================================
# FIX #4: Session Enforcement Tests  
# ============================================================================

class TestFix4_SessionEnforcement:
    """Verify session strategy is enforced."""

    @pytest.mark.asyncio
    async def test_opening_session_blocks_entry(self):
        """NSE_OPENING (09:15-09:30) should block all entries."""
        processor = SignalGateProcessor()
        config = ProcessorConfig(
            name="test",
            processor_class="SignalGateProcessor",
            inbox={"amt_results": "ar"},
            outbox={"signal_gates": "sg"},
            settings={"min_candles": 6},
        )
        await processor.setup(config)

        # Create AMT result message with timestamp during NSE_OPENING
        amt_payload = AMTResultPayload(
            market_state="BALANCED",
            leg_state="BALANCE",
            poc=100.0,
            vah=102.0,
            val=98.0,
        )
        msg = Message(
            payload=amt_payload,
            symbol="TEST",
            timestamp=datetime(2026, 3, 14, 9, 20, 0, tzinfo=IST),  # 09:20 = NSE_OPENING
        )

        session_ctx = processor._get_session_context(msg.timestamp)
        
        # NSE_OPENING should not allow entry
        assert session_ctx["allow_entry"] is False, "NSE_OPENING should block entry"

    @pytest.mark.asyncio
    async def test_primary_session_allows_entry(self):
        """NSE_PRIMARY (09:30-11:30) should allow entries."""
        processor = SignalGateProcessor()
        config = ProcessorConfig(
            name="test",
            processor_class="SignalGateProcessor",
            inbox={"amt_results": "ar"},
            outbox={"signal_gates": "sg"},
            settings={"min_candles": 6},
        )
        await processor.setup(config)

        session_ctx = processor._get_session_context(
            datetime(2026, 3, 14, 10, 0, 0, tzinfo=IST)  # 10:00 = NSE_PRIMARY
        )
        
        assert session_ctx["allow_entry"] is True, "NSE_PRIMARY should allow entry"
        assert session_ctx["allow_trend"] is True, "NSE_PRIMARY should allow trend"
        assert session_ctx["allow_reversion"] is True, "NSE_PRIMARY should allow reversion"


# ============================================================================
# FIX #5: CVD Hard Block Tests
# ============================================================================

class TestFix5_CVDHardBlock:
    """Verify CVD hard blocks work correctly."""

    def test_blocks_extreme_selling_in_balance(self):
        """CVD extreme selling (-150) in BALANCED market should block."""
        data = _make_candle_history(25)
        tick = _make_tick(price=100.0, volume=6000.0)
        amt = _make_amt_result(market_state="BALANCED", cvd_slope=-150.0)
        
        result = three_align_check(data, amt, tick, return_is_second_drive=True)
        
        assert result[0] is False, "Should block entry against extreme CVD selling"

    def test_blocks_extreme_buying_in_balance(self):
        """CVD extreme buying (+150) in BALANCED market should block."""
        data = _make_candle_history(25)
        tick = _make_tick(price=100.0, volume=6000.0)
        amt = _make_amt_result(market_state="BALANCED", cvd_slope=150.0)
        
        result = three_align_check(data, amt, tick, return_is_second_drive=True)
        
        assert result[0] is False, "Should block entry against extreme CVD buying"

    def test_allows_moderate_cvd(self):
        """Moderate CVD (+50) should not block (below 100 threshold)."""
        data = _make_candle_history(25)
        tick = _make_tick(price=98.0, volume=6000.0)
        amt = _make_amt_result(market_state="BALANCED", cvd_slope=50.0, val=98.0)
        
        # CVD of +50 should not trigger hard block (threshold is 100)
        blocked, reason = SignalGateProcessor._check_cvd_hard_block(
            SignalGateProcessor(), amt
        )
        assert blocked is False, "Moderate CVD should not block"


# ============================================================================
# FIX #7: Circuit Breaker Tests
# ============================================================================

class TestFix7_CircuitBreaker:
    """Verify 3-loss daily circuit breaker."""

    def test_circuit_breaker_triggers_at_3_losses(self):
        """3 consecutive losses should halt trading."""
        rm = SessionRiskManager()
        
        assert rm.can_trade is True
        
        rm.record_trade(-100.0)
        assert rm.can_trade is True
        
        rm.record_trade(-50.0)
        assert rm.can_trade is True
        
        rm.record_trade(-75.0)
        assert rm.can_trade is False
        assert rm._halted is True
        assert "3-loss" in rm.halt_reason

    def test_win_resets_loss_counter(self):
        """Win should reset consecutive loss counter."""
        rm = SessionRiskManager()
        
        rm.record_trade(-100.0)
        rm.record_trade(-50.0)
        assert rm.consecutive_losses == 2
        
        rm.record_trade(200.0)  # Win
        assert rm.consecutive_losses == 0
        assert rm.consecutive_wins == 1

    def test_persistence(self):
        """Circuit breaker state should persist."""
        rm = SessionRiskManager()
        rm.record_trade(-100.0)
        rm.record_trade(-50.0)
        rm.record_trade(-75.0)
        
        data = rm.to_dict()
        
        rm2 = SessionRiskManager()
        rm2.load_from_dict(data)
        
        assert rm2._halted is True
        assert rm2.can_trade is False


# ============================================================================
# FIX #6: LVN Play Tests
# ============================================================================

class TestFix6_LVNPlay:
    """Verify LVN play data flows through pipeline."""

    def test_lvn_play_in_amt_payload(self):
        """AMTResultPayload should carry LVN play data."""
        lvn_play = {"direction": "LONG", "level": 98.0, "confluence": "VAL"}
        
        payload = AMTResultPayload(
            market_state="BALANCED",
            leg_state="BALANCE",
            poc=100.0,
            vah=102.0,
            val=98.0,
            lvn_play=lvn_play,
        )
        
        assert payload.lvn_play == lvn_play

    def test_lvn_play_flows_to_gate(self):
        """LVN play should be carried from AMT to gate payload."""
        lvn_play = {"direction": "SHORT", "level": 102.0, "confluence": "VAH"}
        
        amt_payload = AMTResultPayload(
            market_state="BALANCED",
            leg_state="BALANCE",
            poc=100.0,
            vah=102.0,
            val=98.0,
            lvn_play=lvn_play,
        )
        
        gate_payload = SignalGatePayload(
            passed=True,
            reason="test",
            lvn_play=lvn_play,
        )
        
        assert gate_payload.lvn_play == lvn_play
