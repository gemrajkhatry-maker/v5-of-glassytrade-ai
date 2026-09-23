"""B3: DecisionLoop emits through the public telemetry sink on every pass."""

from __future__ import annotations

from quant.contracts.ports.telemetry import NullTelemetry
from quant.engine.decision_loop import DecisionLoop


class _Recorder(NullTelemetry):
    def __init__(self) -> None:
        self.ticks = 0
        self.signals: list[str] = []

    def record_tick(self) -> None:
        self.ticks += 1

    def record_signal(self, direction: str) -> None:
        self.signals.append(direction)


def test_decision_loop_defaults_to_null_telemetry():
    loop = DecisionLoop(
        config={"symbol": "SYM"},
        deps={"risk": object(), "oms": object(), "strategy": object(), "amt_engine": object(), "get_position_manager": lambda: None},
        state={
            "get_bar_index": lambda: 0,
            "get_entry_bar_index": lambda: 0,
            "set_entry_bar_index": lambda v: None,
            "get_last_close_bar_index": lambda: 0,
            "get_latch": lambda: {},
            "set_latch": lambda k, v: None,
            "clear_latch": lambda: None,
            "get_cert_records": lambda: [],
            "get_open_trade_risk": lambda: 0.0,
            "set_open_trade_risk": lambda v: None,
            "get_exposure_state": lambda: None,
            "set_exposure_state": lambda v: None,
        },
        emit=lambda e: None,
    )
    assert not hasattr(loop, "_telemetry")
    assert isinstance(loop.telemetry, NullTelemetry)


def test_decision_loop_uses_injected_sink():
    sink = _Recorder()
    loop = DecisionLoop(
        config={"symbol": "SYM"},
        deps={"risk": object(), "oms": object(), "strategy": object(), "amt_engine": object(), "get_position_manager": lambda: None},
        state={
            "get_bar_index": lambda: 0,
            "get_entry_bar_index": lambda: 0,
            "set_entry_bar_index": lambda v: None,
            "get_last_close_bar_index": lambda: 0,
            "get_latch": lambda: {},
            "set_latch": lambda k, v: None,
            "clear_latch": lambda: None,
            "get_cert_records": lambda: [],
            "get_open_trade_risk": lambda: 0.0,
            "set_open_trade_risk": lambda v: None,
            "get_exposure_state": lambda: None,
            "set_exposure_state": lambda v: None,
        },
        emit=lambda e: None,
        telemetry=sink,
    )
    assert loop.telemetry is sink
