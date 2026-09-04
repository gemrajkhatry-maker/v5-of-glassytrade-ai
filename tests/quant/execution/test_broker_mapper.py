from decimal import Decimal

from quant.contracts.enums import SetupType, SignalType
from quant.decision.signal_builder import Signal as EngineSignal
from quant.execution.broker_mapper import to_broker_signal


def _engine_signal(direction="LONG", model_label="Triple-A"):
    return EngineSignal(
        type=direction, reason="test", entry=100.25, sl=99.5, tp=102.0,
        rr=2.0, model_label=model_label, symbol="NIFTY AUG FUT", timestamp="t0",
    )


def test_long_maps_to_buy_with_decimal_prices():
    broker_sig = to_broker_signal(_engine_signal("LONG"))
    assert broker_sig.type == SignalType.BUY
    assert broker_sig.price == Decimal("100.25")
    assert broker_sig.stop_loss == Decimal("99.5")
    assert broker_sig.take_profit == Decimal("102.0")


def test_short_maps_to_sell():
    broker_sig = to_broker_signal(_engine_signal("SHORT"))
    assert broker_sig.type == SignalType.SELL


def test_model_label_maps_to_setup_type():
    assert to_broker_signal(_engine_signal(model_label="LVN_Sniper")).setup == SetupType.MEAN_REVERSION
    assert to_broker_signal(_engine_signal(model_label="VA_Fade")).setup == SetupType.RESPONSIVE_FADE
    assert to_broker_signal(_engine_signal(model_label="Triple-A")).setup == SetupType.TREND_MODEL


def test_unknown_model_label_defaults_to_trend_model():
    assert to_broker_signal(_engine_signal(model_label="Unknown")).setup == SetupType.TREND_MODEL


# ---------------------------------------------------------------------------
# C1: the engine-sized quantity must travel with the broker signal so the
# adapter executes the exact size the risk layer approved (never re-sizes).
# ---------------------------------------------------------------------------

def test_quantity_carried_into_metadata():
    broker_sig = to_broker_signal(_engine_signal("LONG"), quantity=130.0)
    assert broker_sig.metadata is not None
    assert broker_sig.metadata.get("order_quantity") == 130.0


def test_signal_identity_is_preserved_across_mapping():
    signal = _engine_signal("LONG")
    broker_sig = to_broker_signal(signal, quantity=130.0)

    assert broker_sig.signal_id == signal.signal_id
    assert broker_sig.metadata["engine_signal_id"] == signal.signal_id


def test_repeated_mapping_reuses_same_broker_identity():
    signal = _engine_signal("LONG")

    first = to_broker_signal(signal, quantity=130.0)
    retry = to_broker_signal(signal, quantity=130.0)

    assert first.signal_id == retry.signal_id


def test_no_quantity_omits_order_quantity():
    broker_sig = to_broker_signal(_engine_signal("LONG"))
    assert "order_quantity" not in (broker_sig.metadata or {})


def test_zero_quantity_omits_order_quantity():
    broker_sig = to_broker_signal(_engine_signal("LONG"), quantity=0.0)
    assert "order_quantity" not in (broker_sig.metadata or {})
