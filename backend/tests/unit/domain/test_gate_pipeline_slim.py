import pytest

from app.domain.fabio_ai.services.gate_pipeline import GateContext, GatePipeline, GateReason
from app.domain.trading.models.enums import MarketState


def test_gate_context_has_triple_a_fields_with_defaults():
    ctx = GateContext()
    assert ctx.absorption_detected is False
    assert ctx.absorption_bar_age == 0
    assert ctx.vwap_breakout is None


def test_gate_context_accepts_explicit_values():
    ctx = GateContext(
        absorption_detected=True,
        absorption_bar_age=2,
        vwap_breakout="LONG",
    )
    assert ctx.absorption_detected is True
    assert ctx.absorption_bar_age == 2
    assert ctx.vwap_breakout == "LONG"


def _qualified(**overrides) -> GateContext:
    """Fully-qualified context that satisfies all 5 gates."""
    defaults = dict(
        symbol="SYM",
        candle_count=10,
        tick_age_seconds=1.0,
        market_state=MarketState.IMBALANCED,
        poc=100.0,
        vah=105.0,
        val=95.0,
        price=106.0,
        tick_size=0.1,
        nearest_level=106.0,
        distance_to_level_ticks=1.0,
        drive_number=2,
        drive_entry_valid=True,
        aggression_score=3.0,
        cvd_conflict=False,
        is_risk_halted=False,
        position_size_ok=True,
        eia_window_active=False,
        setup_type="IMBALANCE_CONTINUATION",
        r_r_ratio=2.0,
        cushion_ticks=3.0,
        absorption_detected=True,
        absorption_bar_age=0,
        vwap_breakout=None,
    )
    defaults.update(overrides)
    return GateContext(**defaults)


def test_exactly_five_gates_evaluated_on_pass():
    """The slim pipeline runs exactly 5 gates, never 12."""
    result = GatePipeline().evaluate(_qualified())
    assert result.passed is True
    assert result.gate_count == 5


def test_fully_qualified_context_passes():
    result = GatePipeline().evaluate(_qualified())
    assert result.passed is True
    assert result.reason == GateReason.TRADE
    assert result.is_trade is True


def test_risk_reward_gate_rejects_low_rr():
    """Gate 5 (R:R >= 1.5) is now a hard gate — low RR always rejects."""
    result = GatePipeline().evaluate(_qualified(r_r_ratio=1.2))
    assert result.passed is False
    assert result.gate == 5
    assert result.reason == GateReason.SKIP
    assert result.gate_count == 5


def test_session_phase_gate_blocks_warmup():
    """Gate 1 (session phase) folds the old warm-up + EIA checks."""
    result = GatePipeline().evaluate(_qualified(candle_count=1))
    assert result.passed is False
    assert result.gate == 1
    assert result.reason == GateReason.BLOCKED


def test_session_phase_gate_blocks_eia_window():
    result = GatePipeline().evaluate(_qualified(eia_window_active=True))
    assert result.passed is False
    assert result.gate == 1
    assert result.reason == GateReason.SUPPRESSED


def test_no_position_gate_blocks_first_drive():
    """Gate 2 (no-position/cooldown) folds the old drive + risk-halt checks."""
    result = GatePipeline().evaluate(_qualified(drive_number=1))
    assert result.passed is False
    assert result.gate == 2
    assert result.reason == GateReason.FLAT


def test_no_position_gate_blocks_risk_halt():
    result = GatePipeline().evaluate(_qualified(is_risk_halted=True, halt_reason="Daily loss"))
    assert result.passed is False
    assert result.gate == 2
    assert result.reason == GateReason.SESSION_STOPPED


def test_vwap_breakout_alone_does_not_pass_gate_4():
    """A lone VWAP breakout is NOT a confirmed edge without absorption context."""
    result = GatePipeline().evaluate(
        _qualified(absorption_detected=False, absorption_bar_age=0, vwap_breakout="LONG")
    )
    assert result.passed is False
    assert result.gate == 4
    assert result.reason == GateReason.WAIT


def test_absorption_context_enables_gate_4():
    """Fresh absorption + breakout direction aligns the strategy edge."""
    result = GatePipeline().evaluate(
        _qualified(
            vwap_breakout="LONG",
            absorption_detected=True,
            absorption_bar_age=2,
        )
    )
    assert result.passed is True


def test_absorption_too_old_does_not_enable_gate_4():
    """Stale absorption is not an accumulation context — edge must be fresh."""
    result = GatePipeline().evaluate(
        _qualified(
            vwap_breakout="LONG",
            absorption_detected=True,
            absorption_bar_age=20,
        )
    )
    assert result.passed is False
    assert result.gate == 4


def test_aggression_phase_passes_gate_4():
    result = GatePipeline().evaluate(_qualified(vwap_breakout=None, absorption_detected=False))
    assert result.passed is True
