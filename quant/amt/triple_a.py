"""Triple-A state machine — WAITING → ABSORBING → ACCUMULATING → AGGRESSION.

Implements Fabio Valentini's full Triple-A methodology (spec §8):

  WAITING      → ABSORBING:   absorption signature detected (pending in AbsorptionDetector)
  ABSORBING   → ACCUMULATING: 2+ bars elapsed near POC/LVN with delta stabilizing
  ACCUMULATING → AGGRESSION:   full 1m candle CLOSE beyond cluster AND VWAP/CVD confirm

The machine tracks the absorption cluster bounds from the AbsorptionDetector's
pending candle so it can verify the breakout (close beyond cluster) and confirm
the accumulation dwell before declaring AGGRESSION.

Anti-stale: resets to WAITING after ``_STALE_BARS`` without progression.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

WAITING = "WAITING"
ABSORBING = "ABSORBING"
ACCUMULATING = "ACCUMULATING"
AGGRESSION = "AGGRESSION"

_ABSORBED_TO_SIGNAL = {"SELL_ABSORBED": "LONG", "BUY_ABSORBED": "SHORT"}

# Spec §8: accumulation requires 2+ bars of consolidation near POC/LVN.
_MIN_ACCUMULATION_BARS = 2
# Anti-stale timeout (bars) before resetting to WAITING.
_STALE_BARS = 15


@dataclass(frozen=True)
class TripleASnapshot:
    phase: str = WAITING
    signal: str = ""
    cluster_high: float = 0.0
    cluster_low: float = 0.0
    conviction: float = 0.0
    bars_in_phase: int = 0


class TripleAMachine:
    """Full Triple-A state machine: WAITING → ABSORBING → ACCUMULATING → AGGRESSION.

    Each ``update`` call processes one closed bar. The machine progresses through
    the phases based on:

    - ``absorption_side`` non-empty: the AbsorptionDetector confirmed a breakout
      (close beyond the absorption cluster). This is the AGGRESSION trigger.
    - ``absorption_active`` True: an absorption signature is pending (waiting for
      breakout). This is the ABSORBING state.
    - ``poc`` / ``tick_size``: used to verify the accumulation dwell (price
      consolidating near POC/LVN for 2+ bars).
    - ``vwap`` / ``cvd_slope``: used to confirm the aggression direction.

    Only one bar is spent in AGGRESSION before resetting to WAITING (prevents
    sticky-ENTRY on Gate 3).
    """

    def __init__(self) -> None:
        self._phase = WAITING
        self._signal = ""
        self._cluster_high = 0.0
        self._cluster_low = 0.0
        self._bars_in_phase = 0
        self._pending_side = ""

    def reset(self) -> None:
        self._phase = WAITING
        self._signal = ""
        self._cluster_high = 0.0
        self._cluster_low = 0.0
        self._bars_in_phase = 0
        self._pending_side = ""

    @staticmethod
    def _valid_cluster(cluster_high, cluster_low) -> bool:
        try:
            high = float(cluster_high)
            low = float(cluster_low)
        except (TypeError, ValueError, OverflowError):
            return False
        return math.isfinite(high) and math.isfinite(low) and 0.0 < low < high

    def snapshot(self) -> TripleASnapshot:
        return TripleASnapshot(
            phase=self._phase,
            signal=self._signal,
            cluster_high=self._cluster_high,
            cluster_low=self._cluster_low,
            conviction=1.0 if self._phase == AGGRESSION else 0.0,
            bars_in_phase=self._bars_in_phase,
        )

    def update(
        self,
        *,
        close: float,
        high: float,
        low: float,
        vwap: float = 0.0,
        cvd_slope: float = 0.0,
        absorption_side: str = "",
        absorption_active: bool = False,
        absorption_cluster_high: float = 0.0,
        absorption_cluster_low: float = 0.0,
        poc: float = 0.0,
        tick_size: float = 0.05,
    ) -> TripleASnapshot:
        """Process one closed bar through the Triple-A state machine.

        Args:
            close: Current bar close price.
            high: Current bar high.
            low: Current bar low.
            vwap: Session/recent VWAP value.
            cvd_slope: Current CVD slope.
            absorption_side: Non-empty ("SELL_ABSORBED"/"BUY_ABSORBED") when the
                AbsorptionDetector confirms a breakout beyond the cluster.
            absorption_active: True when an absorption signature is pending
                (ABSORBING state candidate).
            absorption_cluster_high: High of the absorption cluster (pending candle).
            absorption_cluster_low: Low of the absorption cluster (pending candle).
            poc: Current Point of Control (for accumulation proximity check).
            tick_size: Instrument tick size (for proximity tolerance).
        """
        # AGGRESSION is a one-shot: clear it on the next bar.
        if self._phase == AGGRESSION:
            self.reset()

        # --- Anti-stale: reset if stuck too long in any intermediate phase ---
        if self._phase in (ABSORBING, ACCUMULATING) and self._bars_in_phase >= _STALE_BARS:
            self.reset()

        # --- Update cluster bounds from the latest absorption reading ---
        if self._valid_cluster(absorption_cluster_high, absorption_cluster_low):
            self._cluster_high = float(absorption_cluster_high)
            self._cluster_low = float(absorption_cluster_low)
        else:
            self._cluster_high = 0.0
            self._cluster_low = 0.0

        # --- Track pending side from active (not yet broken out) absorption ---
        if absorption_active and not absorption_side and self._pending_side:
            # Keep the pending side from when the absorption was first detected.
            pass
        elif absorption_side:
            self._pending_side = absorption_side

        # --- State transitions ---
        if self._phase == WAITING:
            self._update_waiting(absorption_active=absorption_active)
        elif self._phase == ABSORBING:
            self._update_absorbing(
                close=close,
                vwap=vwap,
                cvd_slope=cvd_slope,
                absorption_side=absorption_side,
                absorption_active=absorption_active,
                poc=poc,
                tick_size=tick_size,
            )
        elif self._phase == ACCUMULATING:
            self._update_accumulating(
                close=close,
                vwap=vwap,
                cvd_slope=cvd_slope,
                absorption_side=absorption_side,
            )

        self._bars_in_phase += 1
        return self.snapshot()

    # ------------------------------------------------------------------
    # State handlers
    # ------------------------------------------------------------------

    def _update_waiting(self, *, absorption_active: bool) -> None:
        """WAITING → ABSORBING when an absorption signature appears."""
        if absorption_active:
            self._phase = ABSORBING
            self._bars_in_phase = 0

    def _update_absorbing(
        self,
        *,
        close: float,
        vwap: float,
        cvd_slope: float,
        absorption_side: str,
        absorption_active: bool,
        poc: float,
        tick_size: float,
    ) -> None:
        """ABSORBING: wait for accumulation dwell or direct breakout.

        If the detector fires (breakout confirmed) before accumulation completes,
        we still go to AGGRESSION — the breakout itself is the signal. But we
        prefer the spec path: 2+ bars consolidating near POC first.
        """
        # Direct breakout: detector fired while we were still absorbing.
        if absorption_side:
            signal = _ABSORBED_TO_SIGNAL.get(absorption_side)
            if signal and self._confirm_direction(signal, close, vwap, cvd_slope):
                self._enter_aggression(signal)
            else:
                # Breakout happened but VWAP/CVD don't confirm — reset.
                self.reset()
            return

        # Check if price is consolidating near POC (accumulation zone).
        if self._is_near_poc(close, poc, tick_size):
            if self._bars_in_phase + 1 >= _MIN_ACCUMULATION_BARS:
                # 2+ bars of consolidation → ACCUMULATING
                self._phase = ACCUMULATING
                self._bars_in_phase = 0
            # else: still accumulating bars in ABSORBING
        else:
            # Price wandered away from POC without breakout — reset accumulation
            # count but stay in ABSORBING (the absorption is still pending).
            self._bars_in_phase = 0

    def _update_accumulating(
        self,
        *,
        close: float,
        vwap: float,
        cvd_slope: float,
        absorption_side: str,
    ) -> None:
        """ACCUMULATING → AGGRESSION when the breakout is confirmed."""
        if absorption_side:
            signal = _ABSORBED_TO_SIGNAL.get(absorption_side)
            if signal and self._confirm_direction(signal, close, vwap, cvd_slope):
                self._enter_aggression(signal)
            else:
                self.reset()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _enter_aggression(self, signal: str) -> None:
        self._phase = AGGRESSION
        self._signal = signal
        self._bars_in_phase = 0

    def _confirm_direction(
        self, signal: str, close: float, vwap: float, cvd_slope: float
    ) -> bool:
        """Confirm the breakout bar agrees with VWAP and CVD (spec §8)."""
        try:
            price = float(close)
            vwap_value = float(vwap)
            slope = float(cvd_slope)
        except (TypeError, ValueError, OverflowError):
            return False
        if not all(math.isfinite(value) for value in (price, vwap_value, slope)):
            return False
        if (
            price <= 0
            or vwap_value <= 0
            or not self._valid_cluster(self._cluster_high, self._cluster_low)
        ):
            return False
        if signal == "LONG":
            return price > self._cluster_high and price > vwap_value and slope > 0
        if signal == "SHORT":
            return price < self._cluster_low and price < vwap_value and slope < 0
        return False

    def _is_near_poc(
        self, close: float, poc: float, tick_size: float
    ) -> bool:
        """Price is consolidating within 4 ticks of POC (spec: near POC/LVN)."""
        if poc <= 0:
            return False
        tolerance = max(tick_size * 4.0, 0.05)
        return abs(close - poc) <= tolerance
