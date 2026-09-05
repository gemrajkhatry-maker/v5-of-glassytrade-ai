"""Engine-side broker port — canonical definition lives in
brokers/broker/ports.py (single home for all broker ports; spec §8)."""
from brokers.broker.ports import IBroker

__all__ = ["IBroker"]
