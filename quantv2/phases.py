"""Session phases + setup permissions — AMT §10 session timing & anti-whipsaw.

Doc anchor: docs/amt/AMT_INSTITUTIONAL_SCALPER_ALGORITHM.md §10 (Pre-Market
Trap Lock, Discovery Window, Session Exhaustion, max 3-4h trade window, no
overnight holding). Translated from quant/amt/market/opening.py (discovery
window), quant/amt/market/regime.py (trend/contraction regime concept) and
v1 session gates (quant/amt/session/context.py phase table +
quant/decision/gates_session_position.py setup families) — v1 frozen, READ
for math, NEVER imported.

Phases (NSE IST, doc's NY windows adapted to the 09:15 open):

  TRAP        pre-open (doc: 09:10-09:30 trap zone; trap_minutes=15 marks
              the nominal lock window before the 09:15 open — everything
              pre-open is TRAP, fail-closed: zero new entries).
  DISCOVERY   09:15 + discovery_minutes (09:45) — SQUEEZE-only.
  MIDDAY      09:45 - exhaustion_hm — trend setups allowed only if the
              trend regime confirms (doc: prime window directional
              expansion; plan pins 12:00 MIDDAY, 13:00 EXHAUSTION).
  EXHAUSTION  exhaustion_hm - force-exit (15:20) — tighten stops, no new
              entries (doc: 11:30-13:00 NY exhaustion; NSE adaptation
              defaults 12:30 IST, straddled by the pinned 12:00/13:00).
  CLOSE       >= force-exit (15:20 IST, matches quantv2 SessionClock) —
              flatten only; no overnight holding.

Setup families (v1 gates_session_position): SQUEEZE is the discovery
catalyst; the trend-continuation family {SECOND_DRIVE, LVN_SNIPER} needs a
non-RANGE trend regime at MIDDAY; everything else (TRIPLE_A, VA_FADE, ...)
is phase-permissive at MIDDAY. All unknown phases/setups fail closed.

trend_regime is half-trend-lite: drift of the second half of the window
against the first (v1 regime lookback 20), dead zone = 10% of window
range; fewer bars than the window -> RANGE (never claim trend on partial
data).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
OPEN_HM = (9, 15)          # NSE cash open (doc §10 NY 09:30 -> IST 09:15)
FORCE_EXIT_HM = (15, 20)   # EOD square-off start (quantv2 SessionClock)
WARMUP_BARS = 15
DISCOVERY_SETUP = "SQUEEZE"
TREND_SETUPS = frozenset({"SECOND_DRIVE", "LVN_SNIPER"})
REGIME_WINDOW = 20
REGIME_DRIFT_FRACTION = 0.1

_PHASES = ("TRAP", "DISCOVERY", "MIDDAY", "EXHAUSTION", "CLOSE")


def _hm_min(hm: tuple[int, int]) -> int:
    return hm[0] * 60 + hm[1]


class PhaseRules:
    """Phase-of-day classifier + per-phase setup permission table."""

    def __init__(
        self,
        trap_minutes: int = 15,
        discovery_minutes: int = 30,
        exhaustion_hm: tuple[int, int] = (12, 30),
        force_exit_hm: tuple[int, int] = FORCE_EXIT_HM,
    ) -> None:
        self.trap_minutes = max(0, int(trap_minutes))
        self.discovery_minutes = max(0, int(discovery_minutes))
        self.exhaustion_hm = (int(exhaustion_hm[0]), int(exhaustion_hm[1]))
        self.force_exit_hm = (int(force_exit_hm[0]), int(force_exit_hm[1]))
        self._open_min = _hm_min(OPEN_HM)
        self._trap_start_min = self._open_min - self.trap_minutes
        self._discovery_end_min = self._open_min + self.discovery_minutes
        self._exhaustion_min = _hm_min(self.exhaustion_hm)
        self._force_exit_min = _hm_min(self.force_exit_hm)

    def phase(self, ts: float) -> str:
        """Classify an epoch timestamp (IST wall clock) into a §10 phase."""
        t = datetime.fromtimestamp(ts, tz=IST)
        m = t.hour * 60 + t.minute
        if m < self._open_min:
            return "TRAP"
        if m < self._discovery_end_min:
            return "DISCOVERY"
        if m < self._exhaustion_min:
            return "MIDDAY"
        if m < self._force_exit_min:
            return "EXHAUSTION"
        return "CLOSE"

    def allow(self, setup: str, phase: str, regime: str | None = None) -> bool:
        """May `setup` open a new position in `phase` (regime = trend_regime)?"""
        if phase == "DISCOVERY":
            return setup == DISCOVERY_SETUP
        if phase == "MIDDAY":
            if setup in TREND_SETUPS:
                return regime in ("UP", "DOWN")
            return True
        return False

    def trend_regime(self, closes: list) -> str:
        """Half-trend-lite regime: "UP" / "DOWN" / "RANGE"."""
        vals = [float(c) for c in closes]
        if len(vals) < REGIME_WINDOW:
            return "RANGE"
        window = vals[-REGIME_WINDOW:]
        half = REGIME_WINDOW // 2
        first = sum(window[:half]) / half
        second = sum(window[half:]) / (REGIME_WINDOW - half)
        span = max(window) - min(window)
        if span <= 0.0:
            return "RANGE"
        band = span * REGIME_DRIFT_FRACTION
        drift = second - first
        if drift > band:
            return "UP"
        if drift < -band:
            return "DOWN"
        return "RANGE"

    def warmup_ok(self, bar_count: int) -> bool:
        """Session needs >= WARMUP_BARS before any entry."""
        return int(bar_count) >= WARMUP_BARS
