"""AuctionCoordinator — folds all six quant detectors into one immutable
AuctionState snapshot per closed bar. Pure and deterministic: same bars in,
same states out."""

from __future__ import annotations

from quant.absorption import AbsorptionDetector
from quant.auction_state import AuctionState
from quant.bars import Bar
from quant.location import LocationBuilder
from quant.order_flow import OrderFlowBuilder
from quant.triple_a import TripleAStateMachine
from quant.volume_profile import VolumeProfileBuilder
from quant.vwap import VWAPBuilder


class AuctionCoordinator:
    def __init__(self) -> None:
        self._vp_builder = VolumeProfileBuilder()
        self._vwap_builder = VWAPBuilder()
        self._of_builder = OrderFlowBuilder()
        self._abs_detector = AbsorptionDetector()
        self._loc_builder = LocationBuilder()
        self._triple_a = TripleAStateMachine()

    def on_bar_close(self, bar: Bar) -> AuctionState:
        self._vp_builder.update(bar)
        self._vwap_builder.update(bar)
        self._of_builder.update(bar)
        self._abs_detector.update(bar)
        self._loc_builder.update(bar)

        vp = self._vp_builder.snapshot()
        vwap = self._vwap_builder.snapshot()
        of = self._of_builder.snapshot()
        absorption = self._abs_detector.snapshot()
        loc = self._loc_builder.snapshot(vp, bar.close)

        phase = self._triple_a.update(bar, vp, vwap, absorption)
        signal = self._triple_a.last_signal

        return AuctionState(
            time=bar.time,
            close=bar.close,
            volume_profile=vp,
            vwap=vwap,
            order_flow=of,
            absorption=absorption,
            location=loc,
            triple_a_phase=phase,
            triple_a_signal=signal,
        )
