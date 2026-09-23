"""Market Structure Classifier — pure domain service.

Classifies market structure into one of five states (BALANCE, IMBALANCE,
TRANSITION, EXPANSION, CHOP) using microstructure features derived from
OHLC candles, POC history, and VWAP history.

Implements hysteresis rules (dwell time, confidence gate, transition buffer,
cooldown) to prevent noisy state flipping.  GPU-accelerated via MLX on
Apple Silicon.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from quant.contracts.value_objects import OHLC
from quant.amt import compute as mc
from quant.contracts.constants import (
    STRUCTURE_DWELL_TICKS,
    STRUCTURE_COOLDOWN_TICKS,
    STRUCTURE_CONFIDENCE_GATE,
    STRUCTURE_BYPASS_CONFIDENCE,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------


@dataclass
class MarketStructure:
    """Result of market structure classification."""

    state: str  # "BALANCE" | "IMBALANCE" | "TRANSITION" | "EXPANSION" | "CHOP"
    confidence_score: int  # 0-100
    features: dict  # raw feature values for debugging


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STATES = ("BALANCE", "IMBALANCE", "TRANSITION", "EXPANSION", "CHOP")

# Hysteresis parameters (from constants — prevents BALANCE/CHOP flicker)
_DWELL_TICKS = (
    STRUCTURE_DWELL_TICKS  # new state must persist this many consecutive ticks
)
_CONFIDENCE_GATE = STRUCTURE_CONFIDENCE_GATE  # minimum confidence to accept a new state
_COOLDOWN_TICKS = (
    STRUCTURE_COOLDOWN_TICKS  # hold after a state change before allowing another
)
_BYPASS_CONFIDENCE = (
    STRUCTURE_BYPASS_CONFIDENCE  # skip TRANSITION buffer if confidence exceeds this
)


# ---------------------------------------------------------------------------
# Pure-Python math helpers
# ---------------------------------------------------------------------------


def _linreg_slope(ys: list[float]) -> float:
    """Ordinary least-squares slope for evenly-spaced y values (MLX-accelerated)."""
    return mc.linreg_slope(ys)


def _ema(values: list[float], period: int) -> float:
    """Exponential moving average of *values*, returning the final value."""
    return mc.ema(values, period)


def _atr(candles: list[OHLC], period: int = 14) -> float:
    """Average True Range over *period* candles (MLX-accelerated)."""
    if len(candles) < 2:
        return max(c.high - c.low for c in candles) if candles else 1.0
    return mc.atr(
        [c.high for c in candles],
        [c.low for c in candles],
        [c.close for c in candles],
        period,
    )


# ---------------------------------------------------------------------------
# Feature computation
# ---------------------------------------------------------------------------


def _range_atr_ratio(candles: list[OHLC], period: int = 14) -> float:
    """Range of last *period* candles divided by ATR(period)."""
    tail = candles[-period:]
    if not tail:
        return 1.0
    overall_high = max(c.high for c in tail)
    overall_low = min(c.low for c in tail)
    atr = _atr(candles, period)
    if atr == 0.0:
        return 1.0
    return (overall_high - overall_low) / atr


def _vwap_slope(vwap_history: list[float], atr: float, period: int = 14) -> float:
    """Linear regression slope of VWAP over last *period* points, normalized by ATR."""
    tail = vwap_history[-period:]
    if len(tail) < 2 or atr == 0.0:
        return 0.0
    return _linreg_slope(tail) / atr


def _candle_overlap_pct(candles: list[OHLC], period: int = 10) -> float:
    """Mean overlap percentage between consecutive candles (MLX-accelerated)."""
    if len(candles) < 2:
        return 100.0
    return mc.candle_overlap_pct(
        [c.high for c in candles],
        [c.low for c in candles],
        period,
    )


def _volume_acceleration(candles: list[OHLC]) -> float:
    """EMA(volume, 5) / EMA(volume, 20)."""
    vols = [c.volume for c in candles]
    if not vols:
        return 1.0
    ema_fast = _ema(vols, 5)
    ema_slow = _ema(vols, 20)
    if ema_slow == 0.0:
        return 1.0
    return ema_fast / ema_slow


def _poc_migration(poc_history: list[float], atr: float, period: int = 20) -> float:
    """Absolute linreg slope of POC over *period* points, normalized by ATR."""
    tail = poc_history[-period:]
    if len(tail) < 2 or atr == 0.0:
        return 0.0
    return abs(_linreg_slope(tail)) / atr


# ---------------------------------------------------------------------------
# Scoring helpers (each feature contributes 0-20 to confidence)
# ---------------------------------------------------------------------------


def _score_balance(ra: float, vs: float, ol: float, va: float, pm: float) -> int:
    """Score how well features fit BALANCE."""
    s = 0
    s += 20 if ra < 1.2 else max(0, 20 - int((ra - 1.2) * 25))
    s += 20 if abs(vs) < 0.1 else max(0, 20 - int((abs(vs) - 0.1) * 100))
    s += 20 if ol > 70 else max(0, int((ol - 40) / 30 * 20)) if ol > 40 else 0
    s += 20 if va < 1.1 else max(0, 20 - int((va - 1.1) * 100))
    s += 20 if pm < 0.05 else max(0, 20 - int((pm - 0.05) * 200))
    return max(0, min(100, s))


def _score_imbalance(ra: float, vs: float, ol: float, va: float, pm: float) -> int:
    """Score how well features fit IMBALANCE."""
    s = 0
    s += 20 if ra > 2.0 else max(0, int((ra - 1.2) / 0.8 * 20)) if ra > 1.2 else 0
    s += (
        20
        if abs(vs) > 0.3
        else max(0, int((abs(vs) - 0.1) / 0.2 * 20))
        if abs(vs) > 0.1
        else 0
    )
    s += 20 if ol < 40 else max(0, 20 - int((ol - 40) / 30 * 20)) if ol < 70 else 0
    s += 20 if va > 1.3 else max(0, int((va - 1.1) / 0.2 * 20)) if va > 1.1 else 0
    s += 20 if pm > 0.15 else max(0, int((pm - 0.05) / 0.1 * 20)) if pm > 0.05 else 0
    return max(0, min(100, s))


def _score_transition(ra: float, vs: float, ol: float, va: float, pm: float) -> int:
    """Score how well features fit TRANSITION (mid-range values)."""
    s = 0
    # range_atr best at 1.2-2.0
    if 1.2 <= ra <= 2.0:
        s += 20
    else:
        dist = min(abs(ra - 1.2), abs(ra - 2.0))
        s += max(0, 20 - int(dist * 25))
    # vwap_slope best at 0.1-0.3
    avs = abs(vs)
    if 0.1 <= avs <= 0.3:
        s += 20
    else:
        dist = min(abs(avs - 0.1), abs(avs - 0.3))
        s += max(0, 20 - int(dist * 100))
    # overlap best at 40-70%
    if 40 <= ol <= 70:
        s += 20
    else:
        dist = min(abs(ol - 40), abs(ol - 70))
        s += max(0, 20 - int(dist / 30 * 20))
    # vol_accel best at 1.1-1.3
    if 1.1 <= va <= 1.3:
        s += 20
    else:
        dist = min(abs(va - 1.1), abs(va - 1.3))
        s += max(0, 20 - int(dist * 100))
    # poc_mig best at 0.05-0.15
    if 0.05 <= pm <= 0.15:
        s += 20
    else:
        dist = min(abs(pm - 0.05), abs(pm - 0.15))
        s += max(0, 20 - int(dist * 200))
    return max(0, min(100, s))


def _score_expansion(ra: float, vs: float, ol: float, va: float, pm: float) -> int:
    """Score how well features fit EXPANSION (extreme trending)."""
    s = 0
    s += 20 if ra > 2.5 else max(0, int((ra - 1.5) / 1.0 * 20)) if ra > 1.5 else 0
    s += (
        20
        if abs(vs) > 0.4
        else max(0, int((abs(vs) - 0.2) / 0.2 * 20))
        if abs(vs) > 0.2
        else 0
    )
    s += 20 if ol < 30 else max(0, 20 - int((ol - 30) / 40 * 20)) if ol < 70 else 0
    s += 20 if va > 1.5 else max(0, int((va - 1.2) / 0.3 * 20)) if va > 1.2 else 0
    s += 20 if pm > 0.25 else max(0, int((pm - 0.1) / 0.15 * 20)) if pm > 0.1 else 0
    return max(0, min(100, s))


def _score_chop(ra: float, vs: float, ol: float, va: float, pm: float) -> int:
    """Score how well features fit CHOP (high volume, no direction).

    Differentiator from BALANCE: high vol_accel + high overlap.
    """
    s = 0
    s += 20 if ra < 1.5 else max(0, 20 - int((ra - 1.5) * 20))
    s += 20 if abs(vs) < 0.15 else max(0, 20 - int((abs(vs) - 0.15) * 80))
    s += 20 if ol > 50 else max(0, int((ol - 30) / 20 * 20)) if ol > 30 else 0
    # Chop requires elevated volume (differentiator from balance)
    s += 20 if va > 1.2 else max(0, int((va - 1.0) / 0.2 * 20)) if va > 1.0 else 0
    s += 20 if pm < 0.08 else max(0, 20 - int((pm - 0.08) * 170))
    return max(0, min(100, s))


_SCORERS = {
    "BALANCE": _score_balance,
    "IMBALANCE": _score_imbalance,
    "TRANSITION": _score_transition,
    "EXPANSION": _score_expansion,
    "CHOP": _score_chop,
}


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


class MarketStructureClassifier:
    """Classifies market structure with hysteresis to prevent noisy flipping.

    Hysteresis rules:
    1. Dwell time: new state must persist *_DWELL_TICKS* consecutive ticks.
    2. Confidence gate: new state needs confidence >= *_CONFIDENCE_GATE*.
    3. Transition buffer: BALANCE <-> IMBALANCE must pass through TRANSITION
       unless confidence > *_BYPASS_CONFIDENCE*.
    4. Cooldown: after a state change, hold *_COOLDOWN_TICKS* minimum.
    """

    def __init__(self) -> None:
        self._current_state: str = "BALANCE"
        self._current_confidence: int = 0
        self._pending_state: str | None = None
        self._pending_count: int = 0
        self._cooldown_remaining: int = 0

    # -- public API ---------------------------------------------------------

    def classify(
        self,
        candles: list[OHLC],
        poc_history: list[float],
        vwap_history: list[float],
    ) -> MarketStructure:
        """Classify market structure from the latest candle data.

        Args:
            candles: OHLC candle history (at least 20 recommended).
            poc_history: Point-of-Control price history.
            vwap_history: VWAP history (one per candle).

        Returns:
            MarketStructure with state, confidence, and raw features.
        """
        if not candles:
            return MarketStructure(
                state=self._current_state,
                confidence_score=0,
                features={},
            )

        # --- Compute features ------------------------------------------------
        atr = _atr(candles)
        ra = _range_atr_ratio(candles)
        vs = _vwap_slope(vwap_history, atr)
        ol = _candle_overlap_pct(candles)
        va = _volume_acceleration(candles)
        pm = _poc_migration(poc_history, atr)

        features = {
            "range_atr": round(ra, 4),
            "vwap_slope": round(vs, 4),
            "overlap_pct": round(ol, 2),
            "vol_accel": round(va, 4),
            "poc_migration": round(pm, 4),
            "atr": round(atr, 4),
        }

        # --- Score every state -----------------------------------------------
        scores: dict[str, int] = {}
        for state, scorer in _SCORERS.items():
            scores[state] = scorer(ra, vs, ol, va, pm)

        raw_best = max(scores, key=lambda s: scores[s])
        raw_confidence = scores[raw_best]

        logger.debug(
            "MSC scores: %s | raw_best=%s conf=%d | current=%s cooldown=%d",
            scores,
            raw_best,
            raw_confidence,
            self._current_state,
            self._cooldown_remaining,
        )

        # --- Apply hysteresis ------------------------------------------------
        new_state, new_conf = self._apply_hysteresis(
            raw_best,
            raw_confidence,
            scores,
        )

        return MarketStructure(
            state=new_state,
            confidence_score=new_conf,
            features=features,
        )

    # -- hysteresis logic ---------------------------------------------------

    def _apply_hysteresis(
        self,
        candidate: str,
        candidate_conf: int,
        scores: dict[str, int],
    ) -> tuple[str, int]:
        """Apply dwell-time, confidence gate, transition buffer, and cooldown.

        Returns the (state, confidence) to emit.
        """
        # Cooldown: decrement and hold current state
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1
            return self._current_state, scores.get(self._current_state, 0)

        # If candidate matches current state, reset pending and stay
        if candidate == self._current_state:
            self._pending_state = None
            self._pending_count = 0
            self._current_confidence = candidate_conf
            return self._current_state, candidate_conf

        # Confidence gate
        if candidate_conf < _CONFIDENCE_GATE:
            return self._current_state, scores.get(self._current_state, 0)

        # Transition buffer: BALANCE <-> IMBALANCE must go through TRANSITION
        if not self._transition_buffer_ok(candidate, candidate_conf):
            # Force candidate to TRANSITION instead
            candidate = "TRANSITION"
            candidate_conf = scores.get("TRANSITION", 0)

        # Dwell time: accumulate consecutive ticks for the same candidate
        if candidate == self._pending_state:
            self._pending_count += 1
        else:
            self._pending_state = candidate
            self._pending_count = 1

        if self._pending_count >= _DWELL_TICKS:
            # Accept the new state
            prev = self._current_state
            self._current_state = candidate
            self._current_confidence = candidate_conf
            self._pending_state = None
            self._pending_count = 0
            self._cooldown_remaining = _COOLDOWN_TICKS
            logger.info(
                "MSC state change: %s -> %s (confidence=%d)",
                prev,
                candidate,
                candidate_conf,
            )
            return candidate, candidate_conf

        # Still dwelling — keep current state
        return self._current_state, scores.get(self._current_state, 0)

    def _transition_buffer_ok(self, candidate: str, confidence: int) -> bool:
        """Check if a direct jump is allowed or must route through TRANSITION.

        BALANCE <-> IMBALANCE requires passing through TRANSITION unless
        confidence exceeds *_BYPASS_CONFIDENCE*.
        """
        if confidence > _BYPASS_CONFIDENCE:
            return True
        direct_jumps = {
            ("BALANCE", "IMBALANCE"),
            ("IMBALANCE", "BALANCE"),
        }
        return (self._current_state, candidate) not in direct_jumps
