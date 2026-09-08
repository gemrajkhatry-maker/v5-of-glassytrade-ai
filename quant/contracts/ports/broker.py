"""Broker-neutral execution port owned by the quant domain.

Infrastructure adapters implement this interface; the domain never imports a
broker implementation.
"""
from __future__ import annotations

from brokers.broker.ports import IBroker


__all__ = ["IBroker"]
