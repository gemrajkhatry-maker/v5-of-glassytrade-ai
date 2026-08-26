"""LiveOMS — routes engine Signals to a real IBroker.

DEAD CODE — not constructed by any coordinator as of 2026-08-25; see spec
docs/superpowers/specs/2026-08-25-refactor-program-design.md, open-decision #1.
Kept (not deleted) pending that user decision.

Built and tested ahead of activation. NOT constructed by QuantCoordinator yet:
``QuantEngine`` still always uses ``PaperOMS`` (see runtime.py). Wiring this in
means picking an ``IOMS``-shaped seam and a Signal-mapper contract test on the
adapter path — tracked separately. Until then this class exists so the mapper
and the broker call are exercised by tests, not invented at go-live time.
"""

from __future__ import annotations

from quant.contracts.ports.broker import IBroker
from quant.decision.signal_builder import Signal as EngineSignal
from quant.execution.broker_mapper import to_broker_signal


class LiveOMS:
    """Submits engine Signals to a broker. Mirrors PaperOMS.submit's shape
    closely enough to swap in once the engine takes an injected OMS port."""

    def __init__(self, broker: IBroker, portfolio) -> None:
        self._broker = broker
        self._portfolio = portfolio

    def submit(self, signal: EngineSignal, quantity: float):
        broker_signal = to_broker_signal(signal)
        return self._broker.execute_order(broker_signal, self._portfolio, signal.symbol)

    def close(self, position, price: float, time: str, reason: str):
        raise NotImplementedError(
            "LiveOMS.close: IBroker has no close-position primitive yet — "
            "closing a live position requires an opposing order, not built. "
            "Fails loud on purpose; do not silently no-op a live exit."
        )
