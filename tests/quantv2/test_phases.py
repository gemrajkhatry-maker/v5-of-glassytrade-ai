"""Session phase tests — AMT §10 (plan Task 9, doc-pinned).

Pins: TRAP pre-open (zero entries), DISCOVERY first 30m SQUEEZE-only,
EXHAUSTION no new entries (13:00 IST pinned in plan), CLOSE >= force-exit
(15:20 IST, quantv2 SessionClock), MIDDAY trend setups gated by trend
regime, warmup >= 15 bars, half-trend-lite regime UP/DOWN/RANGE.
"""
from datetime import datetime, timedelta, timezone

from quantv2.phases import PhaseRules

IST = timezone(timedelta(hours=5, minutes=30))


def _ts(h, m, s=0):
    return datetime(2026, 9, 4, h, m, s, tzinfo=IST).timestamp()


def test_phases_and_permissions():
    p = PhaseRules()
    def ts(h, m): return datetime(2026, 9, 4, h, m, tzinfo=IST).timestamp()
    assert p.phase(ts(9, 5)) == "TRAP"
    assert p.phase(ts(9, 25)) == "DISCOVERY"
    assert p.phase(ts(12, 0)) == "MIDDAY"
    assert p.phase(ts(13, 0)) == "EXHAUSTION"
    assert p.allow("SQUEEZE", "DISCOVERY") is True
    assert p.allow("TRIPLE_A", "DISCOVERY") is False
    assert p.allow("TRIPLE_A", "EXHAUSTION") is False
    assert p.allow("TRIPLE_A", "MIDDAY") is True
    assert p.warmup_ok(15) is True and p.warmup_ok(5) is False


def test_phase_boundaries():
    p = PhaseRules()
    assert p.phase(_ts(9, 14, 59)) == "TRAP"
    assert p.phase(_ts(9, 15)) == "DISCOVERY"
    assert p.phase(_ts(9, 44, 59)) == "DISCOVERY"
    assert p.phase(_ts(9, 45)) == "MIDDAY"
    assert p.phase(_ts(12, 29, 59)) == "MIDDAY"
    assert p.phase(_ts(12, 30)) == "EXHAUSTION"
    assert p.phase(_ts(15, 19, 59)) == "EXHAUSTION"
    assert p.phase(_ts(15, 20)) == "CLOSE"
    assert p.phase(_ts(15, 31)) == "CLOSE"
    assert p.phase(_ts(3, 0)) == "TRAP"


def test_allow_matrix():
    p = PhaseRules()
    assert p.allow("SQUEEZE", "TRAP") is False
    assert p.allow("SQUEEZE", "EXHAUSTION") is False
    assert p.allow("SQUEEZE", "CLOSE") is False
    assert p.allow("SQUEEZE", "MIDDAY") is True
    assert p.allow("VA_FADE", "DISCOVERY") is False
    assert p.allow("SECOND_DRIVE", "MIDDAY") is False
    assert p.allow("SECOND_DRIVE", "MIDDAY", "RANGE") is False
    assert p.allow("SECOND_DRIVE", "MIDDAY", "UP") is True
    assert p.allow("SECOND_DRIVE", "MIDDAY", "DOWN") is True
    assert p.allow("SECOND_DRIVE", "MIDDAY", "NONSENSE") is False
    assert p.allow("TRIPLE_A", "NONSENSE_PHASE") is False


def test_trend_regime():
    p = PhaseRules()
    up = [100.0 + i for i in range(20)]
    assert p.trend_regime(up) == "UP"
    assert p.trend_regime(list(reversed(up))) == "DOWN"
    osc = [100.0 + (2.0 if i % 2 == 0 else -2.0) for i in range(20)]
    assert p.trend_regime(osc) == "RANGE"
    assert p.trend_regime([100.0] * 20) == "RANGE"
    assert p.trend_regime([100.0, 101.0, 102.0]) == "RANGE"


def test_custom_config():
    p = PhaseRules(exhaustion_hm=(11, 30), force_exit_hm=(15, 25))
    assert p.phase(_ts(11, 0)) == "MIDDAY"
    assert p.phase(_ts(11, 30)) == "EXHAUSTION"
    assert p.phase(_ts(15, 24, 59)) == "EXHAUSTION"
    assert p.phase(_ts(15, 25)) == "CLOSE"
