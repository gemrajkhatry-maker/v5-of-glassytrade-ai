"""B2 remainder: durable signal identity across process restart.

One logical decision (same symbol, bar time, entry/SL/TP) must always map to
exactly one broker order — across mapping, retries, and process restarts.
Fresh ``uuid4`` per construction broke that: replaying the same approved bar
after a crash minted a NEW id and broker-side correlation dedup could no
longer block the duplicate. Identity is therefore derived (uuid5) from the
decision content; explicit ``signal_id=...`` still wins (tests, certification).
"""

from quant.contracts.entities import (
    Signal as BrokerSignal,
    SetupType,
    SignalType,
    Source,
)
from quant.decision.signal_builder import Signal as EngineSignal
from quant.execution.broker_mapper import to_broker_signal


def _engine_signal(**overrides) -> EngineSignal:
    defaults = dict(
        type="LONG",
        reason="All 4 gates passed",
        entry=100.0,
        sl=95.0,
        tp=110.0,
        rr=2.0,
        model_label="Triple-A",
        symbol="TEST",
        timestamp="2026-09-04T10:00:00+05:30",
    )
    defaults.update(overrides)
    return EngineSignal(**defaults)


def _broker_signal(**overrides) -> BrokerSignal:
    defaults = dict(
        type=SignalType.BUY,
        price=100.0,
        reason="All 4 gates passed",
        stop_loss=95.0,
        take_profit=110.0,
        timestamp="2026-09-04T10:00:00+05:30",
        setup=SetupType.MEAN_REVERSION,
        source=Source.AMT,
    )
    defaults.update(overrides)
    return BrokerSignal(**defaults)


# ---------------------------------------------------------------------------
# Engine signal identity (quant/decision/signal_builder.Signal)
# ---------------------------------------------------------------------------


def test_engine_signal_id_is_stable_across_reconstruction():
    """Rebuilding the same approved decision after a crash re-derives the SAME id."""
    first = _engine_signal()
    second = _engine_signal()
    assert first.signal_id == second.signal_id


def test_engine_signal_id_is_a_uuid5():
    import uuid

    parsed = uuid.UUID(_engine_signal().signal_id)
    assert parsed.version == 5


def test_engine_signal_id_changes_with_decision_content():
    base = _engine_signal().signal_id
    assert _engine_signal(entry=100.5).signal_id != base
    assert _engine_signal(sl=94.5).signal_id != base
    assert _engine_signal(tp=110.5).signal_id != base
    assert _engine_signal(symbol="OTHER").signal_id != base
    assert _engine_signal(timestamp="2026-09-04T10:15:00+05:30").signal_id != base
    assert _engine_signal(type="SHORT").signal_id != base
    assert _engine_signal(model_label="VA_Fade").signal_id != base


def test_engine_signal_explicit_id_wins():
    assert _engine_signal(signal_id="cert-replay-42").signal_id == "cert-replay-42"


# ---------------------------------------------------------------------------
# Broker signal identity (quant/contracts/entities.Signal)
# ---------------------------------------------------------------------------


def test_broker_signal_id_is_stable_across_reconstruction():
    assert _broker_signal().signal_id == _broker_signal().signal_id


def test_broker_signal_id_changes_with_content():
    base = _broker_signal().signal_id
    assert _broker_signal(price=100.5).signal_id != base
    assert _broker_signal(type=SignalType.SELL).signal_id != base
    assert _broker_signal(setup=SetupType.TREND_MODEL).signal_id != base


def test_broker_signal_explicit_id_wins():
    sig = BrokerSignal.create(
        type=SignalType.BUY,
        price=100.0,
        reason="r",
        stop_loss=95.0,
        take_profit=110.0,
        timestamp="t",
        setup=SetupType.MEAN_REVERSION,
        source=Source.AMT,
        signal_id="explicit-id",
    )
    assert sig.signal_id == "explicit-id"


# ---------------------------------------------------------------------------
# Mapper preservation: engine decision -> broker order identity
# ---------------------------------------------------------------------------


def test_mapper_maps_identical_decisions_to_identical_broker_ids():
    """Same logical decision mapped twice (retry/restart) -> one broker identity."""
    assert to_broker_signal(_engine_signal(), 4.0).signal_id == to_broker_signal(
        _engine_signal(), 4.0
    ).signal_id


def test_mapper_preserves_explicit_engine_id():
    sig = _engine_signal(signal_id="decision-xyz")
    broker_sig = to_broker_signal(sig, 4.0)
    assert broker_sig.signal_id == "decision-xyz"
    assert broker_sig.metadata["engine_signal_id"] == "decision-xyz"
