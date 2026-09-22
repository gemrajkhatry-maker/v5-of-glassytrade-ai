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

from typing import Any

from quant.contracts.decimal_utils import to_decimal
from quant.contracts.entities import Signal as BrokerSignal
from quant.contracts.enums import SetupType, SignalType, Source
from quant.decision.setup_labels import canonical_setup_type
from quant.decision.signal_builder import Signal as EngineSignal

_SETUP_BY_CANONICAL: dict[str, SetupType] = {
    "TRIPLE_A": SetupType.TREND_MODEL,
    "LVN_SNIPER": SetupType.MEAN_REVERSION,
    "VA_FADE": SetupType.RESPONSIVE_FADE,
    "SECOND_DRIVE": SetupType.MEAN_REVERSION,
    "INITIATIVE": SetupType.TREND_MODEL,
    "SQUEEZE": SetupType.TREND_MODEL,
}


def to_broker_signal(signal: EngineSignal, quantity: float | None = None) -> BrokerSignal:
    """Map an approved engine ``Signal`` onto the ``IBroker`` contract.

    ``quantity`` is the engine-sized, lot-snapped order size produced by the
    risk layer. When provided it is carried in metadata as ``order_quantity``
    so the broker adapter executes exactly that size — the adapter must never
    re-derive quantity against its own portfolio view (C1).
    """
    metadata: dict[str, Any] = {
        "rr": signal.rr,
        "model_label": signal.model_label,
        "engine_signal_id": signal.signal_id,
    }
    if quantity is not None and quantity > 0:
        metadata["order_quantity"] = float(quantity)
    canon = canonical_setup_type(signal.model_label)
    # Unlabeled signals must not silently become TREND_MODEL.
    setup = _SETUP_BY_CANONICAL.get(canon, SetupType.TREND_MODEL) if canon else SetupType.MEAN_REVERSION
    return BrokerSignal.create(
        type=SignalType.BUY if signal.type == "LONG" else SignalType.SELL,
        price=to_decimal(signal.entry),
        reason=signal.reason,
        stop_loss=to_decimal(signal.sl),
        take_profit=to_decimal(signal.tp),
        timestamp=signal.timestamp,
        setup=setup,
        source=Source.AMT,
        metadata=metadata,
        signal_id=signal.signal_id,
    )
