import pytest

from quant.execution.live_oms import EmergencyFlattenError, LiveOMS
from quant.execution.oms import PaperOMS

from quant.bars import Bar
from quant.decision.data_quality import (
    REQUIRED_EVIDENCE_FAMILIES,
    DataQuality,
    failed_evidence_families,
)
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

    Blocked-quality tests assert submissions == [] before OMS runs; exact
    evidence must reach the broker and fill so DecisionLoop can approve.
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

    def supports_native_stop_loss(self) -> bool:
        return True

    def place_stop_loss(self, symbol, side, quantity, stop_price, contract_ref=None):
        return "proxy-stop-1"


class _LegacyBroker:
    def __init__(self):
        self.submissions = []

    def execute_order(self, signal, portfolio, symbol, contract_ref=None):
        self.submissions.append((signal, portfolio, symbol))


class _RecordingPaperOMS(PaperOMS):
    def __init__(self):
        super().__init__()
        self.submissions = []

    def submit(self, signal, quantity):
        self.submissions.append((signal, quantity))
        return None


def _exact_provenance() -> dict[str, DataQuality]:
    return {family: DataQuality.TICK_EXACT for family in REQUIRED_EVIDENCE_FAMILIES}


def _bar():
    return Bar(time="2026-01-15T10:00:00+05:30", open=100, high=105, low=95, close=102, volume=1000)


def _decision():
    signal = Signal("LONG", "Triple-A", 100, 98, 106, 3, "Triple-A", "SYM", "t")
    return QuantDecision(True, signal, "Triple-A", "", (), model_label="Triple-A")


def _loop(oms, quality, *, underlying_gateway=None, live_mode=None, records=None,
          events=None, provenance=None):
    """DecisionLoop whose context carries *quality* through the real
    ``DecisionContextBuilder`` path (quality rides the AMT DTO keys the builder
    reads) — no private ``_build_context`` patch (Task 19: one owner)."""
    strategy = type("Strategy", (), {"should_enter": lambda self, ctx: _decision()})()
    config = {"symbol": "SYM", "market": "NSE", "cooldown_bars": 0}
    if live_mode is not None:
        config["live_mode"] = live_mode
    amt = _AMT()
    prov = provenance if provenance is not None else quality
    if isinstance(prov, DataQuality):
        prov = {family: prov for family in REQUIRED_EVIDENCE_FAMILIES}
    elif not isinstance(prov, dict):
        prov = {}
    amt.last_amt_dto = {
        "dataQuality": quality.value,
        "evidenceProvenance": {
            family: (
                prov[family].value
                if family in prov and isinstance(prov[family], DataQuality)
                else str(prov.get(family, "UNAVAILABLE"))
            )
            for family in REQUIRED_EVIDENCE_FAMILIES
        },
    }
    loop = DecisionLoop(
        config=config,
        deps={"risk": _Risk(), "oms": oms, "strategy": strategy, "amt_engine": amt,
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
    return loop


def test_failed_evidence_families_uses_required_order():
    provenance = {
        "footprint_imbalance": DataQuality.TICK_EXACT,
        "cvd_delta": DataQuality.PRICE_DIRECTION_PROXY,
        "ofi_depth": DataQuality.UNAVAILABLE,
        "absorption": DataQuality.TICK_EXACT,
        "stacked_imbalance": DataQuality.TICK_EXACT,
    }

    assert failed_evidence_families(provenance) == ("cvd_delta", "ofi_depth")


def test_live_block_names_each_non_exact_family_when_aggregate_is_exact():
    provenance = {
        "footprint_imbalance": DataQuality.TICK_EXACT,
        "cvd_delta": DataQuality.PRICE_DIRECTION_PROXY,
        "ofi_depth": DataQuality.UNAVAILABLE,
        "absorption": DataQuality.TICK_EXACT,
        "stacked_imbalance": DataQuality.TICK_EXACT,
    }
    oms = LiveOMS(broker=_Broker(), portfolio=object())

    decision = _loop(
        oms, DataQuality.TICK_EXACT, provenance=provenance,
    ).evaluate({}, _bar())

    assert decision.approved is False
    assert decision.reason == "PROXY_FLOW_BLOCKED"
    assert any("cvd_delta" in reason for reason in decision.block_reasons)
    assert any("ofi_depth" in reason for reason in decision.block_reasons)


def test_paper_replay_keeps_proxy_metadata_for_family_failure():
    provenance = {
        "footprint_imbalance": DataQuality.TICK_EXACT,
        "cvd_delta": DataQuality.PRICE_DIRECTION_PROXY,
        "ofi_depth": DataQuality.UNAVAILABLE,
        "absorption": DataQuality.TICK_EXACT,
        "stacked_imbalance": DataQuality.TICK_EXACT,
    }
    oms = _RecordingPaperOMS()

    decision = _loop(
        oms, DataQuality.TICK_EXACT, provenance=provenance,
    ).evaluate({}, _bar())

    assert decision.approved is True
    assert decision.metadata["mode"] == "PROXY_MODE"
    assert decision.metadata["failed_evidence_families"] == ["cvd_delta", "ofi_depth"]


def test_live_proxy_entry_is_blocked_before_oms_submission():
    broker = _Broker()
    oms = LiveOMS(broker=broker, portfolio=object())
    decision = _loop(oms, DataQuality.CANDLE_DISTRIBUTED).evaluate({}, _bar())

    assert decision.approved is False
    assert decision.reason == "PROXY_FLOW_BLOCKED"
    assert broker.submissions == []


def test_live_unavailable_entry_is_blocked_before_oms_submission():
    broker = _Broker()
    oms = LiveOMS(broker=broker, portfolio=object())
    decision = _loop(oms, DataQuality.UNAVAILABLE).evaluate({}, _bar())

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
    """Candle-only and unavailable grades block live OMS."""
    oms = LiveOMS(broker=_Broker(), portfolio=object())
    decision = _loop(oms, quality).evaluate({}, _bar())

    assert decision.approved is False
    assert decision.reason == "PROXY_FLOW_BLOCKED"


def test_live_price_direction_proxy_is_blocked():
    broker = _Broker()
    oms = LiveOMS(broker=broker, portfolio=object())
    decision = _loop(oms, DataQuality.PRICE_DIRECTION_PROXY).evaluate({}, _bar())

    assert decision.approved is False
    assert decision.reason == "PROXY_FLOW_BLOCKED"
    assert broker.submissions == []


def test_legacy_broker_without_capability_is_blocked_before_entry():
    broker = _LegacyBroker()
    oms = LiveOMS(broker=broker, portfolio=object())

    with pytest.raises(EmergencyFlattenError, match="native stop"):
        oms.submit(_decision().signal, quantity=1)

    assert broker.submissions == []


def test_live_tick_exact_entry_passes_to_live_oms():
    oms = LiveOMS(broker=_Broker(), portfolio=object())
    decision = _loop(oms, DataQuality.TICK_EXACT).evaluate({}, _bar())

    assert decision.approved is True


def test_live_uses_family_provenance_instead_of_aggregate_quality():
    oms = LiveOMS(broker=_Broker(), portfolio=object())
    provenance = {
        family: DataQuality.TICK_EXACT
        for family in REQUIRED_EVIDENCE_FAMILIES
    }
    provenance["cvd_delta"] = DataQuality.PRICE_DIRECTION_PROXY

    decision = _loop(
        oms, DataQuality.TICK_EXACT, provenance=provenance,
    ).evaluate({}, _bar())

    assert decision.reason == "PROXY_FLOW_BLOCKED"


def test_live_uses_exact_families_when_aggregate_quality_is_proxy():
    broker = _Broker()
    oms = LiveOMS(broker=broker, portfolio=object())

    decision = _loop(
        oms,
        DataQuality.PRICE_DIRECTION_PROXY,
        provenance=_exact_provenance(),
    ).evaluate({}, _bar())

    assert decision.approved is True
    assert decision.reason != "PROXY_FLOW_BLOCKED"
    assert broker.submissions


@pytest.mark.parametrize("family", REQUIRED_EVIDENCE_FAMILIES)
def test_live_blocks_each_required_family_when_not_exact(family):
    provenance = _exact_provenance()
    provenance[family] = DataQuality.PRICE_DIRECTION_PROXY
    broker = _Broker()
    oms = LiveOMS(broker=broker, portfolio=object())

    decision = _loop(
        oms, DataQuality.TICK_EXACT, provenance=provenance,
    ).evaluate({}, _bar())

    assert decision.approved is False
    assert decision.reason == "PROXY_FLOW_BLOCKED"
    assert decision.metadata["failed_evidence_families"] == [family]
    assert any(family in reason for reason in decision.block_reasons)
    assert broker.submissions == []


@pytest.mark.parametrize("family", REQUIRED_EVIDENCE_FAMILIES)
@pytest.mark.parametrize("bad_kind", ["missing", "invalid"])
def test_live_fails_closed_for_missing_or_invalid_family(family, bad_kind):
    provenance = _exact_provenance()
    if bad_kind == "missing":
        del provenance[family]
    else:
        provenance[family] = "NOT_A_PROVENANCE"
    broker = _Broker()
    oms = LiveOMS(broker=broker, portfolio=object())

    decision = _loop(
        oms, DataQuality.TICK_EXACT, provenance=provenance,
    ).evaluate({}, _bar())

    assert decision.approved is False
    assert decision.reason == "PROXY_FLOW_BLOCKED"
    assert decision.metadata["failed_evidence_families"] == [family]
    assert broker.submissions == []


def test_live_capability_cannot_be_downgraded_by_false_config_override():
    broker = _Broker()
    oms = LiveOMS(broker=broker, portfolio=object())
    decision = _loop(
        oms, DataQuality.CANDLE_DISTRIBUTED, live_mode=False,
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
    decision = _loop(oms, DataQuality.CANDLE_DISTRIBUTED).evaluate({}, _bar())

    assert decision.reason == "PROXY_FLOW_BLOCKED"
    assert oms.submissions == []


def test_blocked_proxy_is_recorded_in_event_and_certification():
    records = []
    events = []
    oms = LiveOMS(broker=_Broker(), portfolio=object())
    decision = _loop(
        oms, DataQuality.CANDLE_DISTRIBUTED, records=records, events=events,
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
        _RecordingPaperOMS(), DataQuality.CANDLE_DISTRIBUTED,
        records=records, events=events,
    ).evaluate({}, _bar())

    assert decision.metadata["mode"] == "PROXY_MODE"
    assert [event.decision.metadata["mode"] for event in events if isinstance(event, DecisionProduced)] == [
        "PROXY_MODE"
    ]
    assert records[-1]["metadata"]["mode"] == "PROXY_MODE"


def test_paper_proxy_entry_remains_allowed_and_marked_proxy_mode():
    oms = _RecordingPaperOMS()
    decision = _loop(oms, DataQuality.CANDLE_DISTRIBUTED).evaluate({}, _bar())

    assert decision.approved is True
    assert decision.metadata["mode"] == "PROXY_MODE"
    assert oms.submissions


def test_paper_tick_exact_entry_is_not_marked_proxy_mode():
    oms = _OMS()
    decision = _loop(oms, DataQuality.TICK_EXACT).evaluate({}, _bar())

    assert decision.metadata == {}


def test_live_proxy_gate_runs_before_option_translation():
    oms = LiveOMS(broker=_Broker(), portfolio=object())
    loop = _loop(
        oms,
        DataQuality.CANDLE_GAUSSIAN,
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
