"""Signal mapper — engine world -> IBroker world.

The live decision loop produces ``quant.decision.signal_builder.Signal``
(LONG/SHORT, float ``entry``/``sl``/``tp``). ``IBroker.execute_order`` expects
``quant.contracts.entities.Signal`` (BUY/SELL, Decimal ``price``/``stop_loss``).
These are two different types on purpose (engine math stays float-fast;
broker money stays Decimal-precise) — this is the one place they cross.

ponytail: model_label -> SetupType is a lookup table, not a classifier. Add a
label here when a new playbook needs a distinct SetupType.
"""

from __future__ import annotations

from quant.contracts.decimal_utils import to_decimal
from quant.contracts.entities import Signal as BrokerSignal
from quant.contracts.enums import SetupType, SignalType, Source
from quant.decision.signal_builder import Signal as EngineSignal

_SETUP_BY_MODEL_LABEL: dict[str, SetupType] = {
    "Triple-A": SetupType.TREND_MODEL,
    "LVN_Sniper": SetupType.MEAN_REVERSION,
    "VA_Fade": SetupType.RESPONSIVE_FADE,
}


def to_broker_signal(signal: EngineSignal) -> BrokerSignal:
    """Map an approved engine ``Signal`` onto the ``IBroker`` contract."""
    return BrokerSignal.create(
        type=SignalType.BUY if signal.type == "LONG" else SignalType.SELL,
        price=to_decimal(signal.entry),
        reason=signal.reason,
        stop_loss=to_decimal(signal.sl),
        take_profit=to_decimal(signal.tp),
        timestamp=signal.timestamp,
        setup=_SETUP_BY_MODEL_LABEL.get(signal.model_label, SetupType.TREND_MODEL),
        source=Source.AMT,
        metadata={"rr": signal.rr, "model_label": signal.model_label},
    )
