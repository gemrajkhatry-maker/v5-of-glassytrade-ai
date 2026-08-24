from dataclasses import dataclass

from quant.brokers.synthetic import SyntheticGateway
from quant.runtime import QuantEngine


@dataclass(frozen=True)
class _TestBar:
    time: str = "t1"
    open: float = 1.0
    high: float = 1.0
    low: float = 1.0
    close: float = 1.0
    volume: float = 1.0
    buy_volume: float = 1.0
    sell_volume: float = 1.0
    delta: float = 1.0


def _bar():
    from quant.events import BarClosed

    return BarClosed(symbol="SYM", time="t1", bar=_TestBar())


def test_runtime_events_carry_ordered_causal_metadata():
    engine = QuantEngine(
        SyntheticGateway([]), "SYM", interval_seconds=1, stream_id="metadata:SYM"
    )
    engine._emit(_bar())
    event = engine.events[0]
    assert event.session_id == "metadata:SYM"
    assert event.sequence == 1
    assert event.correlation_id == "metadata:SYM"
    assert event.causation_id == ""
    assert event.source == "quant_engine"


def test_runtime_event_causation_links_following_events():
    engine = QuantEngine(
        SyntheticGateway([]), "SYM", interval_seconds=1, stream_id="metadata:SYM"
    )
    first = _bar()
    second = _bar()
    engine._emit(first)
    engine._emit(second)
    assert engine.events[1].sequence == 2
    assert engine.events[1].causation_id == engine.events[0].event_id


def test_default_stream_ids_are_unique_for_independent_engines():
    first = QuantEngine(SyntheticGateway([]), "SYM", interval_seconds=1)
    second = QuantEngine(SyntheticGateway([]), "SYM", interval_seconds=1)
    assert first._session_id != second._session_id


def test_explicit_stream_id_makes_replay_identity_stable():
    first = QuantEngine(
        SyntheticGateway([]), "SYM", interval_seconds=1, stream_id="replay:SYM"
    )
    second = QuantEngine(
        SyntheticGateway([]), "SYM", interval_seconds=1, stream_id="replay:SYM"
    )
    first._emit(_bar())
    second._emit(_bar())
    assert first.events == second.events
