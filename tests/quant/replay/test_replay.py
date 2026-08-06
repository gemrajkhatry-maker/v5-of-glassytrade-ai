"""WS-REPLAY §5.2 determinism + drift-detection tests.

A deterministic 120-bar synthetic session (extending the ``_session_bars()``
shape from ``tests/quant/test_golden_file.py`` with absorption spikes, quiet
bars and VA-edge bars) is captured into a committed golden JSONL fixture. The
replay harness must reproduce it byte-for-byte with fresh analyzers, and a
mutated bar's volume must be caught by the drift gate.
"""

import pathlib

import pytest
from dataclasses import replace

from quant.bars import Bar
from quant.tools.replay import (
    FLOAT_ATOL,
    ReplayMismatch,
    assert_replay_equal,
    capture,
    replay,
    states_to_jsonl_bytes,
)

FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "replay" / "session_120.jsonl"
)


def _session_bars_120():
    """Deterministic 120-bar session, exercised through the whole machine.

      bars 0-24    quiet 1-tick range @100, vol 100                  -> WAITING
      bar  25      BUY absorption spike (flat, 5x vol, 90% buys)     -> ABSORBING
      bars 26-27   accumulation AT POC (100)                         -> ACCUMULATING
      bars 28-31   breakout 104..116                                 -> AGGRESSION LONG
      bars 32-41   quiet back @100                                   -> WAITING
      bar  42      SELL absorption spike (flat, 5x vol, 90% sells)   -> ABSORBING
      bars 43-44   accumulation AT POC (100)                         -> ACCUMULATING
      bars 45-48   breakdown 96..84                                  -> AGGRESSION SHORT
      bars 49-69   quiet back @100                                   -> WAITING
      bar  70      BUY absorption spike at POC (fresh rearm)         -> ABSORBING
      bars 71-72   accumulation AT POC                               -> ACCUMULATING
      bars 73-76   breakout to 116 -> close above vah               -> ABOVE_VA
      bars 77-91   quiet back @100                                   -> WAITING
      bar  92      SELL absorption spike at POC (fresh rearm)        -> ABSORBING
      bars 93-94   accumulation AT POC                               -> ACCUMULATING
      bars 95-98   breakdown to 84 -> close below val               -> BELOW_VA
      bars 99-119  quiet back @100                                   -> WAITING
    """
    out = []
    for i in range(25):
        out.append(Bar(time=f"t{i}", open=100, high=101, low=99, close=100, volume=100))
    out.append(Bar(time="t25", open=100, high=100, low=100, close=100,
                   volume=500, buy_volume=450, sell_volume=50))
    for i in range(26, 28):
        out.append(Bar(time=f"t{i}", open=100, high=100, low=100, close=100,
                       volume=100, buy_volume=60, sell_volume=40))
    for i in range(28, 32):
        close = 100 + (i - 27) * 4
        out.append(Bar(time=f"t{i}", open=close - 0.5, high=close + 1, low=close - 1,
                       close=close, volume=100))
    for i in range(32, 42):
        out.append(Bar(time=f"t{i}", open=100, high=101, low=99, close=100, volume=100))
    out.append(Bar(time="t42", open=100, high=100, low=100, close=100,
                   volume=500, buy_volume=50, sell_volume=450))
    for i in range(43, 45):
        out.append(Bar(time=f"t{i}", open=100, high=100, low=100, close=100,
                       volume=100, buy_volume=40, sell_volume=60))
    for i in range(45, 49):
        close = 100 - (i - 44) * 4
        out.append(Bar(time=f"t{i}", open=close + 0.5, high=close + 1, low=close - 1,
                       close=close, volume=100))
    for i in range(49, 70):
        out.append(Bar(time=f"t{i}", open=100, high=101, low=99, close=100, volume=100))
    out.append(Bar(time="t70", open=100, high=100, low=100, close=100,
                   volume=500, buy_volume=450, sell_volume=50))
    for i in range(71, 73):
        out.append(Bar(time=f"t{i}", open=100, high=100, low=100, close=100,
                       volume=100, buy_volume=60, sell_volume=40))
    for i in range(73, 77):
        close = 100 + (i - 72) * 4
        out.append(Bar(time=f"t{i}", open=close - 0.5, high=close + 1, low=close - 1,
                       close=close, volume=100))
    for i in range(77, 92):
        out.append(Bar(time=f"t{i}", open=100, high=101, low=99, close=100, volume=100))
    out.append(Bar(time="t92", open=100, high=100, low=100, close=100,
                   volume=500, buy_volume=50, sell_volume=450))
    for i in range(93, 95):
        out.append(Bar(time=f"t{i}", open=100, high=100, low=100, close=100,
                       volume=100, buy_volume=40, sell_volume=60))
    for i in range(95, 99):
        close = 100 - (i - 94) * 4
        out.append(Bar(time=f"t{i}", open=close + 0.5, high=close + 1, low=close - 1,
                       close=close, volume=100))
    for i in range(99, 120):
        out.append(Bar(time=f"t{i}", open=100, high=101, low=99, close=100, volume=100))
    assert len(out) == 120
    return out


def test_capture_matches_committed_golden(tmp_path):
    """(b) capture reproduces the committed golden JSONL byte-for-byte.

    This is the §5.2 drift gate on the capture side: if any of the six
    detectors change the AuctionState output, the captured bytes diverge.
    """
    bars = _session_bars_120()
    captured = tmp_path / "session_120.jsonl"
    states = capture(bars, golden_path=captured)
    assert len(states) == 120
    assert FIXTURE_PATH.is_file()
    assert captured.read_bytes() == FIXTURE_PATH.read_bytes()


def test_fixture_is_varied():
    """The fixture exercises the intended input variety."""
    states = replay(FIXTURE_PATH)
    phases = {s.triple_a_phase for s in states}
    zones = {s.location.zone for s in states}
    sides = {s.absorption.side for s in states if s.absorption is not None}
    assert phases == {"WAITING", "ABSORBING", "ACCUMULATING", "AGGRESSION"}
    assert {"ABOVE_VA", "BELOW_VA"} <= zones
    assert sides == {"BUY", "SELL"}


def test_replay_committed_golden_is_byte_identical():
    """(c) A fresh analyzer replays the golden file with no divergence."""
    assert_replay_equal(FIXTURE_PATH)


def test_replay_is_deterministic_across_fresh_analyzers():
    """(c) Two replays with fresh analyzers are byte-equal."""
    bars = _session_bars_120()
    r1 = replay(FIXTURE_PATH)
    r2 = replay(FIXTURE_PATH)  # fresh AuctionCoordinator per call
    assert r1 == r2
    assert states_to_jsonl_bytes(bars, r1) == states_to_jsonl_bytes(bars, r2)


def test_drift_detection_catches_mutated_bar_volume():
    """(d) Mutating one bar's volume must make the replay test FAIL.

    The mutated stream diverges from the golden states on the mutated bar
    onward (cumulative VWAP / volume profile / absorption all move), so the
    drift gate raises ReplayMismatch.
    """
    bars = _session_bars_120()
    mutated = [
        replace(b, volume=b.volume * 2) if b.time == "t60" else b for b in bars
    ]
    with pytest.raises(ReplayMismatch):
        assert_replay_equal(FIXTURE_PATH, bars=mutated)


def test_replay_mismatch_on_empty_golden(tmp_path):
    """A golden file with no bars can never replay equal to a 120-bar session."""
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    with pytest.raises(ReplayMismatch):
        assert_replay_equal(empty, bars=_session_bars_120())


def test_float_tolerance_is_strict():
    assert FLOAT_ATOL == 1e-9
