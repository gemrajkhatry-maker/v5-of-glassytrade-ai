import pytest

from quant.execution.live_oms import LiveOMS
from quant.execution.oms import PaperOMS

from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.data_quality import DataQuality
from quant.decision.decision_service import QuantDecision
from quant.decision.signal_builder import Signal
from quant.engine.decision_loop import DecisionLoop
from quant.events import DecisionProduced


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


class _OMS:
    lot_size = 1

    def __init__(self):
        self.submissions = []
        self.is_live = False

    def submit(self, signal, quantity):
        self.submissions.append((signal, quantity))


class _PositionManager:
    current_position = None


class _AMT:
    warm_bars = 20
    interval_seconds = 300
    last_amt_dto = {}


class _Broker:
    """Live broker double: records submissions and fills at entry price.

    Blocked-quality tests assert submissions == [] before OMS runs; allowed
    qualities (TICK_EXACT / PRICE_DIRECTION_PROXY) must reach the broker and
    fill so DecisionLoop can approve.
    """

    def __init__(self, fill_price: float = 100.0, fill_qty: float = 1.0):
        from decimal import Decimal

        self.submissions = []
        self._fill_price = fill_price
        self._fill_qty = fill_qty
        self._Decimal = Decimal

    def execute_order(self, signal, portfolio, symbol, contract_ref=None):
        from quant.contracts.entities import Position as BrokerPosition
        from quant.contracts.enums import Side, SignalType, Source

        self.submissions.append((signal, portfolio, symbol))
        return BrokerPosition(
            symbol=symbol,
            side=Side.LONG if getattr(signal, "type", SignalType.BUY) in (SignalType.BUY, "BUY", "LONG") else Side.SHORT,
            source=Source.AMT,
            entry_price=self._Decimal(str(self._fill_price)),
            size=self._Decimal(str(self._fill_qty)),
            stop_loss=self._Decimal("0"),
            take_profit=self._Decimal("0"),
            entry_time="2026-01-15T10:00:00+05:30",
        )


class _RecordingPaperOMS(PaperOMS):
    def __init__(self):
        super().__init__()
        self.submissions = []

    def submit(self, signal, quantity):
        self.submissions.append((signal, quantity))
        return None


def _bar():
    return Bar(time="2026-01-15T10:00:00+05:30", open=100, high=105, low=95, close=102, volume=1000)


def _decision():
    signal = Signal("LONG", "Triple-A", 100, 98, 106, 3, "Triple-A", "SYM", "t")
    return QuantDecision(True, signal, "Triple-A", "", (), model_label="Triple-A")


def _loop(oms, context, *, underlying_gateway=None, live_mode=None, records=None, events=None):
    strategy = type("Strategy", (), {"should_enter": lambda self, ctx: _decision()})()
    config = {"symbol": "SYM", "market": "NSE", "cooldown_bars": 0}
    if live_mode is not None:
        config["live_mode"] = live_mode
    loop = DecisionLoop(
        config=config,
        deps={"risk": _Risk(), "oms": oms, "strategy": strategy, "amt_engine": _AMT(),
              "get_position_manager": lambda: _PositionManager(), "execution_enabled": True,
              "underlying_gateway": underlying_gateway},
        state={"get_bar_index": lambda: 10, "get_entry_bar_index": lambda: 0,
               "set_entry_bar_index": lambda value: None, "get_last_close_bar_index": lambda: -1,
               "get_latch": lambda: {}, "set_latch": lambda key, value: None,
               "clear_latch": lambda: None, "get_cert_records": lambda: records if records is not None else [],
               "get_last_depth": lambda: None, "get_recent_decisions": lambda: [],
               "get_exposure_state": lambda: None},
         emit=(events.append if events is not None else lambda event: None),
    )
    loop._build_context = lambda bar, amt_dto, cooldown: context
    return loop


def _context(quality):
    return DecisionContext(
        bar=_bar(), symbol="SYM", data_quality=quality, agent_probability=0.7,
        evidence_provenance={
            "footprint_imbalance": quality,
            "cvd_delta": quality,
            "ofi_depth": quality,
            "absorption": quality,
            "stacked_imbalance": quality,
        },
    )


def test_live_proxy_entry_is_blocked_before_oms_submission():
    broker = _Broker()
    oms = LiveOMS(broker=broker, portfolio=object())
    decision = _loop(oms, _context(DataQuality.CANDLE_DISTRIBUTED)).evaluate({}, _bar())

    assert decision.approved is False
    assert decision.reason == "PROXY_FLOW_BLOCKED"
    assert broker.submissions == []


def test_live_unavailable_entry_is_blocked_before_oms_submission():
    broker = _Broker()
    oms = LiveOMS(broker=broker, portfolio=object())
    decision = _loop(oms, _context(DataQuality.UNAVAILABLE)).evaluate({}, _bar())

    assert decision.reason == "PROXY_FLOW_BLOCKED"
    assert broker.submissions == []


@pytest.mark.parametrize(
    "quality",
    [
        DataQuality.CANDLE_DISTRIBUTED,
        DataQuality.CANDLE_GAUSSIAN,
        DataQuality.UNAVAILABLE,
    ],
)
def test_live_blocks_candle_and_unavailable_quality(quality):
    """Candle-only / unavailable grades still block live OMS. PROXY is
    accepted because Dhan has no aggressor flag (honest tape ceiling)."""
    oms = LiveOMS(broker=_Broker(), portfolio=object())
    decision = _loop(oms, _context(quality)).evaluate({}, _bar())

    assert decision.approved is False
    assert decision.reason == "PROXY_FLOW_BLOCKED"


def test_live_accepts_price_direction_proxy():
    oms = LiveOMS(broker=_Broker(), portfolio=object())
    decision = _loop(oms, _context(DataQuality.PRICE_DIRECTION_PROXY)).evaluate({}, _bar())
    assert decision.approved is True


def test_live_tick_exact_entry_passes_to_live_oms():
    oms = LiveOMS(broker=_Broker(), portfolio=object())
    decision = _loop(oms, _context(DataQuality.TICK_EXACT)).evaluate({}, _bar())

    assert decision.approved is True


def test_live_blocks_one_non_exact_evidence_family_even_when_aggregate_is_exact():
    oms = LiveOMS(broker=_Broker(), portfolio=object())
    context = _context(DataQuality.TICK_EXACT)
    # A non-exact data_quality (regardless of aggregate) blocks live entry
    context = context.__class__(
        **{
            **context.__dict__,
            "data_quality": DataQuality.CANDLE_DISTRIBUTED,
        }
    )
    decision = _loop(oms, context).evaluate({}, _bar())

    assert decision.reason == "PROXY_FLOW_BLOCKED"


def test_live_capability_cannot_be_downgraded_by_false_config_override():
    broker = _Broker()
    oms = LiveOMS(broker=broker, portfolio=object())
    decision = _loop(
        oms, _context(DataQuality.CANDLE_DISTRIBUTED), live_mode=False,
    ).evaluate({}, _bar())

    assert decision.reason == "PROXY_FLOW_BLOCKED"
    assert broker.submissions == []


def test_missing_live_capability_blocks_proxy_by_default():
    class _UnknownOMS:
        lot_size = 1

        def __init__(self):
            self.submissions = []

        def submit(self, signal, quantity):
            self.submissions.append((signal, quantity))

    oms = _UnknownOMS()
    decision = _loop(oms, _context(DataQuality.CANDLE_DISTRIBUTED)).evaluate({}, _bar())

    assert decision.reason == "PROXY_FLOW_BLOCKED"
    assert oms.submissions == []


def test_blocked_proxy_is_recorded_in_event_and_certification():
    records = []
    events = []
    oms = LiveOMS(broker=_Broker(), portfolio=object())
    decision = _loop(
        oms, _context(DataQuality.CANDLE_DISTRIBUTED), records=records, events=events,
    ).evaluate({}, _bar())

    assert decision.reason == "PROXY_FLOW_BLOCKED"
    assert [event.decision.reason for event in events if isinstance(event, DecisionProduced)] == [
        "PROXY_FLOW_BLOCKED"
    ]
    assert records[-1]["reason"] == "PROXY_FLOW_BLOCKED"
    assert records[-1]["metadata"]["data_quality"] == DataQuality.CANDLE_DISTRIBUTED.value


def test_paper_proxy_metadata_is_observable_in_event_and_certification():
    records = []
    events = []
    decision = _loop(
        _RecordingPaperOMS(), _context(DataQuality.CANDLE_DISTRIBUTED),
        records=records, events=events,
    ).evaluate({}, _bar())

    assert decision.metadata["mode"] == "PROXY_MODE"
    assert [event.decision.metadata["mode"] for event in events if isinstance(event, DecisionProduced)] == [
        "PROXY_MODE"
    ]
    assert records[-1]["metadata"]["mode"] == "PROXY_MODE"


def test_paper_proxy_entry_remains_allowed_and_marked_proxy_mode():
    oms = _RecordingPaperOMS()
    decision = _loop(oms, _context(DataQuality.CANDLE_DISTRIBUTED)).evaluate({}, _bar())

    assert decision.approved is True
    assert decision.metadata["mode"] == "PROXY_MODE"
    assert oms.submissions


def test_paper_tick_exact_entry_is_not_marked_proxy_mode():
    oms = _OMS()
    decision = _loop(oms, _context(DataQuality.TICK_EXACT)).evaluate({}, _bar())

    assert decision.metadata == {}


def test_live_proxy_gate_runs_before_option_translation():
    oms = LiveOMS(broker=_Broker(), portfolio=object())
    loop = _loop(
        oms,
        _context(DataQuality.CANDLE_GAUSSIAN),
        underlying_gateway=object(),
    )
    translated = False

    def fail_if_translated(*args, **kwargs):
        nonlocal translated
        translated = True
        raise AssertionError("proxy decision was translated")

    loop._translate_signal_for_option = fail_if_translated
    decision = loop.evaluate({}, _bar())

    assert decision.reason == "PROXY_FLOW_BLOCKED"
    assert translated is False
