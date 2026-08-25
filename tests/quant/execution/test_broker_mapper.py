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
