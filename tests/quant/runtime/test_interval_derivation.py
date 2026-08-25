"""F2 (block0): QuantEngine bar-count knobs are DERIVED from wall-clock
minutes, not raw bar counts, so moving the interval 1m -> 5m must not
silently multiply the time-stop / cooldown durations by 5.

DEFAULT_INTERVAL_SEC moved to 300 while ``time_stop_bars=60`` and
``_cooldown_bars=5`` were tuned as MINUTES on 1m bars — on 300s bars they
meant a 5-hour time-stop and a 25-minute cooldown. The engine now takes
minutes and derives bars: bars = max(1, minutes * 60 // interval_seconds).
"""

from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway
from tests.quant.runtime.test_runtime import _ticks


def _engine(interval_seconds: int, ticks=None, **kwargs) -> QuantEngine:
    return QuantEngine(
        SyntheticGateway(_ticks() if ticks is None else ticks),
        "SYM",
        interval_seconds=interval_seconds,
        **kwargs,
    )


def test_5m_interval_derives_bars_from_wall_clock_minutes():
    """60-minute time stop on 300s bars == 12 bars; 5-minute cooldown == 1."""
    eng = _engine(300)
    assert eng._exits.time_stop_bars == 12
    assert eng._cooldown_bars == 1


def test_1m_interval_keeps_original_minute_semantics():
    """On 60s bars the derivation reproduces the historically tuned values."""
    eng = _engine(60)
    assert eng._exits.time_stop_bars == 60
    assert eng._cooldown_bars == 5


def test_exit_engine_receives_the_derived_value():
    """ExitEngine is constructed with the derived bar count, not the literal."""
    eng = _engine(300, time_stop_minutes=90)
    assert eng._exits.time_stop_bars == 18  # 90 * 60 // 300


def test_legacy_explicit_time_stop_bars_override_is_honoured():
    """Callers that pass an explicit bar count keep exact legacy behaviour."""
    eng = _engine(300, time_stop_bars=7)
    assert eng._exits.time_stop_bars == 7


def test_derivation_clamps_to_at_least_one_bar():
    """Coarse intervals never produce zero-bar stops/cooldowns."""
    eng = _engine(3600)  # 1h bars: 60min -> 1 bar, 5min would floor to 0
    assert eng._exits.time_stop_bars >= 1
    assert eng._cooldown_bars >= 1
