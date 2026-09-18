from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.data_quality import DataQuality
from quant.decision.decision_service import QuantDecision
from quant.decision.signal_builder import Signal
from quant.engine.decision_loop import DecisionLoop


class _Risk:
    class _State:
        trades_today = 0
        halted = False
        consecutive_losses = 0
        consecutive_wins = 0
        equity = 100000.0
        risk_per_trade_pct = 0.01

    def can_trade(self): return True, ""
    def state(self): return self._State()
    def position_size(self, *args, **kwargs): return 1


class _OMS:
    lot_size = 1
    def __init__(self): self.submissions = []
    def submit(self, signal, quantity): self.submissions.append((signal, quantity))


class _PositionManager:
    current_position = None


class _AMT:
    warm_bars = 20
    interval_seconds = 300
    last_amt_dto = {}


def _bar():
    return Bar(time="2026-01-15T10:00:00+05:30", open=100, high=105, low=95, close=102, volume=1000)


def _decision():
    signal = Signal("LONG", "Triple-A", 100, 98, 106, 3, "Triple-A", "SYM", "t")
    return QuantDecision(True, signal, "Triple-A", "", (), model_label="Triple-A")


def _loop(oms, context, *, live=False):
    strategy = type("Strategy", (), {"should_enter": lambda self, ctx: _decision()})()
    loop = DecisionLoop(
        config={"symbol": "SYM", "market": "NSE", "cooldown_bars": 0, "live_mode": live},
        deps={"risk": _Risk(), "oms": oms, "strategy": strategy, "amt_engine": _AMT(),
              "get_position_manager": lambda: _PositionManager(), "execution_enabled": True},
        state={"get_bar_index": lambda: 10, "get_entry_bar_index": lambda: 0,
               "set_entry_bar_index": lambda value: None, "get_last_close_bar_index": lambda: -1,
               "get_latch": lambda: {}, "set_latch": lambda key, value: None,
               "clear_latch": lambda: None, "get_cert_records": lambda: [],
               "get_last_depth": lambda: None, "get_recent_decisions": lambda: [],
               "get_exposure_state": lambda: None},
        emit=lambda event: None,
    )
    loop._build_context = lambda bar, amt_dto, cooldown: context
    return loop


def _context(quality):
    return DecisionContext(bar=_bar(), symbol="SYM", data_quality=quality, agent_probability=0.7)


def test_live_proxy_entry_is_blocked_before_oms_submission():
    oms = _OMS()
    decision = _loop(oms, _context(DataQuality.CANDLE_DISTRIBUTED), live=True).evaluate({}, _bar())
    assert decision.approved is False
    assert decision.reason == "PROXY_FLOW_BLOCKED"
    assert oms.submissions == []


def test_live_unavailable_entry_is_blocked_before_oms_submission():
    oms = _OMS()
    decision = _loop(oms, _context(DataQuality.UNAVAILABLE), live=True).evaluate({}, _bar())
    assert decision.reason == "PROXY_FLOW_BLOCKED"
    assert oms.submissions == []


def test_paper_proxy_entry_remains_allowed_and_marked_proxy_mode():
    oms = _OMS()
    decision = _loop(oms, _context(DataQuality.CANDLE_DISTRIBUTED)).evaluate({}, _bar())
    assert decision.approved is True
    assert decision.metadata["mode"] == "PROXY_MODE"
    assert oms.submissions


def test_paper_tick_exact_entry_is_not_marked_proxy_mode():
    oms = _OMS()
    decision = _loop(oms, _context(DataQuality.TICK_EXACT)).evaluate({}, _bar())
    assert decision.metadata == {}
