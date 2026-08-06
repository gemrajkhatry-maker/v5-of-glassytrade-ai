"""Immutable per-bar analysis snapshot folding all six quant detectors."""

from __future__ import annotations

from dataclasses import dataclass

from quant.absorption import Absorption
from quant.location import LocationState
from quant.order_flow import OrderFlowState
from quant.volume_profile import VolumeProfile
from quant.vwap import VWAPState


@dataclass(frozen=True)
class AuctionState:
    time: str
    close: float
    volume_profile: VolumeProfile
    vwap: VWAPState
    order_flow: OrderFlowState
    absorption: Absorption | None
    location: LocationState
    triple_a_phase: str
    triple_a_signal: str | None
