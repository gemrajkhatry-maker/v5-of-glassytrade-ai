"""Engine-side broker port — canonical definition lives in
brokers/broker/ports.py (single home for all broker ports; spec §8).

Do NOT delete either port surface without migrating the DI composition root
(backend/app/application/di/composition_root.py wires PaperBrokerAdapter /
DhanBrokerAdapter through this re-export). Consumers of THIS module:
quant/execution/ports.py docstring contract, backend adapters, engine OMS."""
from brokers.broker.ports import IBroker

__all__ = ["IBroker"]
