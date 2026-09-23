"""B-6 metrics canary: the served Prometheus counters actually increment.

Unit-level with an injected ``MetricsRegistry`` — after N ticks / M
decisions / 1 paper trade the counter values match:

* ``ticks_processed_total`` moves on the REAL tick path (``TickHandler``),
  never once-per-decision (the old ``decision_loop`` mislabel).
* ``decisions_evaluated_total`` / ``decisions_approved_total`` /
  ``decisions_blocked_total`` move on each entry ``DecisionProduced``.
* ``trades_executed_total`` moves on a successful paper fill once the
  composition root wires the counter into ``deps["trades_executed"]``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import app.infrastructure.telemetry as telemetry_adapter
from app.core.metrics import MetricsRegistry
from app.infrastructure.telemetry import PrometheusTelemetry
from quant.brokers.gateway import Tick
from quant.contracts.ports.telemetry import NullTelemetry
from quant.engine.tick_handler import TickHandler
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway
from tests.quant.runtime.test_runtime import _ticks
from tests.quant.test_decision_loop import (
    FakeBar,
    FakeOMS,
    FakeRisk,
    FakeStrategy,
    make_decision,
    make_decision_loop,
)


@pytest.fixture
def registry(monkeypatch):
    """A fresh MetricsRegistry injected as the host adapter's sink.

    Exact counter values (not deltas) — the registry starts empty, and
    nothing leaks into the process-wide singleton.
    """
    reg = object.__new__(MetricsRegistry)
    MetricsRegistry.__init__(reg)
    monkeypatch.setattr(telemetry_adapter, "metrics", reg)
    return reg


def _served(reg: MetricsRegistry, name: str) -> float:
    return reg.counter(name, "").value


def _handler(telemetry) -> TickHandler:
    return TickHandler(
        symbol="NIFTY24SEPFUT",
        macro_aggregator=MagicMock(),
        micro_aggregator=None,
        amt_engine=MagicMock(),
        state_getter=lambda: MagicMock(position=None),
        manage_tick_exit_callback=MagicMock(),
        decide_callback=MagicMock(),
        on_bar_closed_callback=MagicMock(),
        manage_exit_callback=MagicMock(),
        telemetry=telemetry,
    )


def _tick(i: int):
    tick = MagicMock()
    tick.price = 20000.0
    tick.time = f"2026-09-16T10:00:{i:02d}"
    tick.depth = None
    return tick


class _TickSink(NullTelemetry):
    def __init__(self) -> None:
        self.ticks = 0

    def record_tick(self) -> None:
        self.ticks += 1


def test_n_ticks_increment_ticks_processed(registry):
    """Real tick handling moves ticks_processed_total, one per tick."""
    handler = _handler(PrometheusTelemetry())

    for i in range(5):
        handler.process_tick(_tick(i))

    assert _served(registry, "ticks_processed_total") == 5


def test_decision_evaluation_does_not_move_ticks_processed(registry):
    """The decision_loop mislabel is gone: evaluating a decision increments
    decisions_evaluated_total, never ticks_processed_total."""
    loop = make_decision_loop(
        strategy=FakeStrategy(make_decision(approved=True)),
        telemetry=PrometheusTelemetry(),
    )

    loop.evaluate({}, FakeBar())

    assert _served(registry, "ticks_processed_total") == 0
    assert _served(registry, "decisions_evaluated_total") == 1
    assert _served(registry, "decisions_approved_total") == 1
    assert _served(registry, "decisions_blocked_total") == 0


def test_m_decisions_split_approved_and_blocked(registry):
    """M evaluations land as evaluated = approved + blocked."""
    telemetry = PrometheusTelemetry()
    approved = make_decision_loop(
        strategy=FakeStrategy(make_decision(approved=True)),
        telemetry=telemetry,
    )
    blocked = make_decision_loop(
        strategy=FakeStrategy(
            make_decision(approved=False, signal=None, reason="NO_EDGE")
        ),
        telemetry=telemetry,
    )

    for _ in range(2):
        approved.evaluate({}, FakeBar())
    for _ in range(3):
        blocked.evaluate({}, FakeBar())

    assert _served(registry, "decisions_evaluated_total") == 5
    assert _served(registry, "decisions_approved_total") == 2
    assert _served(registry, "decisions_blocked_total") == 3


def test_guard_decisions_count_as_blocked(registry):
    """HALTED and COOLDOWN emit DecisionProduced — they count too."""
    telemetry = PrometheusTelemetry()
    halted = make_decision_loop(risk=FakeRisk(can_trade=False), telemetry=telemetry)
    cooldown = make_decision_loop(
        bar_index=6,
        last_close_bar_index=3,
        cooldown_bars=5,
        telemetry=telemetry,
    )

    assert halted.evaluate({}, FakeBar()) is None
    assert cooldown.evaluate({}, FakeBar()) is None

    assert _served(registry, "decisions_evaluated_total") == 2
    assert _served(registry, "decisions_approved_total") == 0
    assert _served(registry, "decisions_blocked_total") == 2


def test_one_paper_trade_increments_trades_executed(registry):
    """A successful paper fill moves the injected trades_executed counter."""
    counter = registry.counter(
        "trades_executed_total", "Trades successfully executed"
    )
    loop = make_decision_loop(
        strategy=FakeStrategy(make_decision(approved=True)),
        oms=FakeOMS(),
        trades_executed=counter,
        telemetry=PrometheusTelemetry(),
    )

    loop.evaluate({}, FakeBar())

    assert counter.value == 1
    assert _served(registry, "decisions_approved_total") == 1


def test_engine_passes_telemetry_into_tick_handler():
    """The runtime path wires the host sink into the tick handler, so
    production ticks reach ticks_processed_total."""
    sink = _TickSink()
    engine = QuantEngine(
        SyntheticGateway(_ticks()), "SYM", interval_seconds=1, telemetry=sink
    )

    handler = engine._create_tick_handler()
    assert handler.telemetry is sink

    handler.process_tick(Tick("t0", 100.0, 10.0, 6.0, 4.0))
    assert sink.ticks == 1
