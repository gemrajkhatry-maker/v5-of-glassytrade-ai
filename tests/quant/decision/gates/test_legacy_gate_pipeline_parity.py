"""Parity: GatePipeline.evaluate via legacy shim vs moved quant module.

GateContext/GateResult are the same class objects through the shim, so parity
of ``evaluate`` output is asserted field-by-field on identical contexts.
"""

from __future__ import annotations

from app.domain.fabio_ai.services.gate_pipeline import (
    GateContext as LegacyGateContext,
    GatePipeline as LegacyGatePipeline,
)
from quant.decision.gates.legacy_gate_pipeline import (
    GateContext,
    GatePipeline,
)
from quant.contracts.enums import MarketState
from tests.quant.parity import assert_parity


def _base_ctx(**overrides) -> GateContext:
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


def test_all_pass_parity():
    assert_parity(LegacyGatePipeline().evaluate, GatePipeline().evaluate, _base_ctx())


def test_warmup_fail_parity():
    assert_parity(LegacyGatePipeline().evaluate, GatePipeline().evaluate, _base_ctx(candle_count=1))


def test_session_fail_parity():
    assert_parity(LegacyGatePipeline().evaluate, GatePipeline().evaluate, _base_ctx(eia_window_active=True))


def test_rr_fail_parity():
    assert_parity(LegacyGatePipeline().evaluate, GatePipeline().evaluate, _base_ctx(r_r_ratio=1.2))


def test_risk_halt_parity():
    assert_parity(
        LegacyGatePipeline().evaluate,
        GatePipeline().evaluate,
        _base_ctx(is_risk_halted=True, halt_reason="Daily loss"),
    )
