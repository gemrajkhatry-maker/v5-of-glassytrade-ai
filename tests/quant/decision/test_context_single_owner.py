"""DecisionContext: one construction owner across all three engine wrappers.

History: ``DecisionLoop._build_context``, ``ExitManager._build_context`` and
``QuantEngine._build_context`` each assembled the context inline and had
drifted:

- position source: exit/runtime used ``pm.current_position or state.position``
  (dual-authority: pm execution book with state fallback) while decision_loop
  read only ``pm.current_position`` — a flat pm with an open state position
  produced a flat entry context;
- range warmup: only decision_loop threaded ``range_bars_enabled /
  live_range_bars / live_minutes``, so thesis-flip and advisor contexts
  computed ``warmup_complete`` on the time path while range mode was live.

Contract pinned here: for identical engine inputs, all three wrappers produce
identical position source and identical range-warmup ``warmup_complete``.
"""

from __future__ import annotations

from types import SimpleNamespace

from quant.bars import Bar
from quant.engine.decision_loop import DecisionLoop
from quant.engine.exit_manager import ExitManager
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway

_BAR = Bar(
    time="2026-01-15T10:00:00+05:30", open=100, high=105, low=95,
    close=102, volume=1000,
)


def _pos(side: str, size: float):
    return SimpleNamespace(
        side=side, size=size, entry=100.0, sl=95.0, tp=110.0, bars_held=3,
    )


class _Risk:
    class _State:
        trades_today = 0
        halted = False
        consecutive_losses = 0
        consecutive_wins = 0
        equity = 100000.0
        risk_per_trade_pct = 0.01

    def can_trade(self):
        return True, ""

    def state(self):
        return self._State()

    def position_size(self, *args, **kwargs):
        return 1


class _AMT:
    warm_bars = 20
    interval_seconds = 300
    last_amt_dto = {}
    last_snapshot = None


def _loop(*, pm_position=None, state_position=None, range_warmup=(False, 0, 0.0)):
    class _PM:
        current_position = pm_position

    strategy = type("Strategy", (), {"should_enter": lambda self, ctx: None})()
    return DecisionLoop(
        config={"symbol": "SYM", "market": "NSE", "cooldown_bars": 0},
        deps={
            "risk": _Risk(), "oms": SimpleNamespace(is_live=False, lot_size=1),
            "strategy": strategy, "amt_engine": _AMT(),
            "get_position_manager": lambda: _PM(),
            "execution_enabled": True, "underlying_gateway": None,
        },
        state={
            "get_bar_index": lambda: 10, "get_entry_bar_index": lambda: 0,
            "set_entry_bar_index": lambda value: None,
            "get_last_close_bar_index": lambda: -1,
            "get_latch": lambda: {}, "set_latch": lambda key, value: None,
            "clear_latch": lambda: None, "get_cert_records": lambda: [],
            "get_last_depth": lambda: None, "get_recent_decisions": lambda: [],
            "get_exposure_state": lambda: None,
            "get_state": lambda: SimpleNamespace(position=state_position),
            "get_range_warmup": lambda: range_warmup,
        },
        emit=lambda event: None,
    )


def _exit(*, pm_position=None, state_position=None, range_warmup=(False, 0, 0.0)):
    class _PM:
        current_position = pm_position

    state_obj = {"value": SimpleNamespace(position=state_position)}
    return ExitManager(
        config={"symbol": "SYM", "market": "NSE", "contract_expiry": None,
                "tick_size": 0.05, "cooldown_bars": 0},
        deps={
            "get_position_manager": lambda: _PM(),
            "strategy": object(), "amt_engine": _AMT(),
            "aggregator": SimpleNamespace(interval_seconds=300),
            "underlying_gateway": None, "risk": _Risk(),
        },
        state={
            "get_bar_index": lambda: 10, "get_entry_bar_index": lambda: 0,
            "get_last_close_bar_index": lambda: -1,
            "set_last_close_bar_index": lambda value: None,
            "get_state": lambda: state_obj["value"],
            "set_state": lambda value: state_obj.__setitem__("value", value),
            "get_range_warmup": lambda: range_warmup,
        },
        emit=lambda event: None,
    )


def _engine(*, pm_position=None, state_position=None, range_bars=False):
    eng = QuantEngine(
        SyntheticGateway([]), "SYM", interval_seconds=1,
        range_bars_enabled=range_bars,
    )
    # Time-path control: bar_index >= warmup_bars (15) with a cold AMT engine
    # would report warmup_complete=True — only range threading can yield False.
    eng._bar_index = 15
    if pm_position is not None:
        eng._get_position_manager().current_position = pm_position
    if state_position is not None:
        eng.state = eng.state.with_position(state_position)
    return eng


def _all_contexts(*, pm_position=None, state_position=None, range_warmup=(False, 0, 0.0)):
    range_on = bool(range_warmup[0])
    return {
        "decision_loop": _loop(
            pm_position=pm_position, state_position=state_position,
            range_warmup=range_warmup,
        )._build_context(_BAR, {}, 0.0),
        "exit_manager": _exit(
            pm_position=pm_position, state_position=state_position,
            range_warmup=range_warmup,
        )._build_context(_BAR, {}, 0.0),
        "runtime": _engine(
            pm_position=pm_position, state_position=state_position,
            range_bars=range_on,
        )._build_context(_BAR, {}, 0.0),
    }


def test_wrappers_prefer_pm_position_over_state():
    """Dual-authority: pm execution book wins; state is the fallback only."""
    ctxs = _all_contexts(
        pm_position=_pos("LONG", 10.0), state_position=_pos("SHORT", -5.0),
    )
    for name, ctx in ctxs.items():
        assert ctx.position_open is True, name
        assert ctx.position_side == "LONG", name


def test_wrappers_fall_back_to_state_position_when_pm_flat():
    """pm.current_position or state.position — identical in all three."""
    ctxs = _all_contexts(state_position=_pos("SHORT", -5.0))
    for name, ctx in ctxs.items():
        assert ctx.position_open is True, name
        assert ctx.position_side == "SHORT", name


def test_wrappers_thread_range_bar_warmup():
    """Range mode: live counters own warmup — not the time path.

    With range on and zero live range closes the time path would answer
    ``warmup_complete=True`` (bar_index + warm_bars >= warmup_bars); every
    wrapper must instead report the range-bar answer (False).
    """
    ctxs = _all_contexts(range_warmup=(True, 0, 0.0))
    for name, ctx in ctxs.items():
        assert ctx.warmup_complete is False, name


def test_wrappers_produce_identical_context_facts():
    """One owner: same inputs → same position + warmup facts everywhere."""
    ctxs = _all_contexts(
        pm_position=_pos("LONG", 10.0), state_position=_pos("SHORT", -5.0),
        range_warmup=(True, 0, 0.0),
    )
    facts = {
        name: (ctx.position_open, ctx.position_side, ctx.warmup_complete)
        for name, ctx in ctxs.items()
    }
    assert len(set(facts.values())) == 1, facts
