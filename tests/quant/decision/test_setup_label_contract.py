"""Stage 1 contract: SetupType is the only money-path label.

Unlabeled Gate-3 passes must not become Triple-A. Terminal TP reads SetupType,
so a VA_FADE mislabeled as Triple-A must not take the trend ladder.
"""

from __future__ import annotations

from quant.decision.decision_service import _label_from_gate_results
from quant.decision.result import GateResult
from quant.decision.setup_labels import (
    canonical_setup_type,
    is_terminal_setup,
    label_from_setup_key,
)
from quant.decision.signal_builder import Signal
from quant.execution.exit_checks import is_terminal_tp_only
from quant.execution.order import Order, Position


def test_unlabeled_gate3_pass_is_empty_not_triple_a():
    results = (
        GateResult(1, True, "ok"),
        GateResult(2, True, "ok"),
        GateResult(3, True, "something passed", setup_key=""),
        GateResult(4, True, "ok"),
    )
    assert _label_from_gate_results(results) == ""
    assert label_from_setup_key("") == ""


def test_va_fade_and_triple_a_cannot_share_a_label():
    assert label_from_setup_key("VA_FADE") != label_from_setup_key("TRIPLE_A")
    assert canonical_setup_type("VA_Fade") == "VA_FADE"
    assert canonical_setup_type("Triple-A") == "TRIPLE_A"
    assert canonical_setup_type("") == ""


def test_terminal_tp_reads_setup_type_not_display_string_shape():
    assert is_terminal_setup("VA_FADE") is True
    assert is_terminal_setup("VA_Fade") is True
    assert is_terminal_setup("Triple-A") is False

    fade_sig = Signal(
        type="LONG",
        reason="Value-Area fade",
        entry=100.0,
        sl=99.0,
        tp=102.0,
        rr=2.0,
        model_label="VA_Fade",
        symbol="S",
        timestamp="t0",
    )
    trend_sig = Signal(
        type="LONG",
        reason="All 4 gates passed",
        entry=100.0,
        sl=99.0,
        tp=102.0,
        rr=2.0,
        model_label="Triple-A",
        symbol="S",
        timestamp="t0",
    )
    fade_pos = Position(
        order=Order(fade_sig, 1.0), open_price=100.0, open_time="t0", size=1.0,
    )
    trend_pos = Position(
        order=Order(trend_sig, 1.0), open_price=100.0, open_time="t0", size=1.0,
    )
    assert is_terminal_tp_only(fade_pos) is True
    assert is_terminal_tp_only(trend_pos) is False
