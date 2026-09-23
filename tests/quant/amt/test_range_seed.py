"""Task 8 — OHLCV → range-bar synth seed + H_range helpers + seed evidence gate."""

from __future__ import annotations

import pytest

import quant.amt_engine as amt_eng
from quant.amt.range_seed import (
    h_range_from_ohlcs,
    quantize_h_range,
    synth_range_bars,
)
from quant.amt_engine import AMTEngine
from quant.bars import Bar
from quant.contracts.value_objects import FloatOHLC
from quant.session_levels import SessionLevelStore


@pytest.fixture(autouse=True)
def _isolate_seed_cache():
    """Do not leave NIFTY history in the process-wide seed cache for later tests."""
    amt_eng._SEED_CACHE.clear()
    yield
    amt_eng._SEED_CACHE.clear()


@pytest.fixture(autouse=True)
def _clear_seed_cache():
    # Module-global seed cache is keyed (symbol, interval); polluting it
    # leaks these recorded candles into other modules (e.g. test_spec4).
    amt_eng._SEED_CACHE.clear()
    yield
    amt_eng._SEED_CACHE.clear()


def _ohlc(t: str, o: float, h: float, lo: float, c: float, v: float) -> FloatOHLC:
    return FloatOHLC(
        time=t, open=o, high=h, low=lo, close=c, volume=v,
        taker_buy_volume=v * 0.5, delta=0.0,
    )


# ---------------------------------------------------------------------------
# synth_range_bars
# ---------------------------------------------------------------------------


def test_synth_range_bars_conserve_volume():
    ohlcs = [
        _ohlc("a", 100.0, 101.0, 99.0, 100.5, 10.0),
        _ohlc("b", 100.5, 104.0, 100.0, 103.0, 20.0),  # span 4 >= H=2 → split
        _ohlc("c", 103.0, 103.5, 102.0, 102.5, 30.0),
        _ohlc("d", 102.5, 102.5, 100.0, 100.0, 45.5),
    ]
    bars = synth_range_bars(ohlcs, h_range=2.0)
    assert abs(sum(b.volume for b in bars) - sum(c.volume for c in ohlcs)) < 1e-6
    assert abs(sum(b.buy_volume for b in bars) - sum(c.taker_buy_volume for c in ohlcs)) < 1e-6


def test_synth_range_bars_split_when_span_ge_h():
    ohlcs = [_ohlc("a", 100.0, 106.0, 100.0, 105.0, 100.0)]
    bars = synth_range_bars(ohlcs, h_range=2.0)
    assert len(bars) >= 2
    for b in bars:
        assert (b.high - b.low) <= 2.0 + 1e-9


def test_synth_range_bars_exact_h_span_still_splits():
    # open==low, close==high, span == H exactly → still >= 2 range bars
    ohlcs = [_ohlc("a", 100.0, 102.0, 100.0, 102.0, 10.0)]
    bars = synth_range_bars(ohlcs, h_range=2.0)
    assert len(bars) >= 2
    assert abs(sum(b.volume for b in bars) - 10.0) < 1e-6


def test_synth_range_bars_under_h_stays_single_bar():
    ohlcs = [_ohlc("a", 100.0, 101.0, 99.5, 100.5, 50.0)]
    bars = synth_range_bars(ohlcs, h_range=2.0)
    assert len(bars) == 1
    assert bars[0].volume == 50.0
    assert bars[0].close == 100.5
    # volume is assigned to the segment close (vwap == close for seed bars)
    assert bars[0].vwap == pytest.approx(100.5)


def test_synth_range_bars_rejects_nonpositive_h():
    with pytest.raises(ValueError):
        synth_range_bars([_ohlc("a", 100.0, 101.0, 99.0, 100.0, 1.0)], h_range=0.0)


# ---------------------------------------------------------------------------
# H_range quantization (ladder {5,10,25,50,100,200} / max(tick, ATR14) fallback)
# ---------------------------------------------------------------------------


def test_quantize_ladder_ceiling_fits_tick():
    # ATR 3 → smallest ladder rung >= 3 is 5; tick 0.05 divides 5 cleanly
    assert quantize_h_range(3.0, 0.05) == pytest.approx(5.0)
    assert quantize_h_range(7.0, 0.05) == pytest.approx(10.0)
    assert quantize_h_range(30.0, 1.0) == pytest.approx(50.0)


def test_quantize_atr_above_ladder_falls_back_to_atr():
    assert quantize_h_range(250.0, 0.05) == pytest.approx(250.0)


def test_quantize_zero_atr_falls_back_to_tick():
    assert quantize_h_range(0.0, 0.05) == pytest.approx(0.05)
    assert quantize_h_range(0.0, 1.0) == pytest.approx(1.0)


def test_quantize_ladder_not_on_tick_grid_falls_back_to_max_tick_atr():
    # tick 0.3 does not divide ladder rung 5 → no rung fits → max(tick, atr)
    assert quantize_h_range(3.0, 0.3) == pytest.approx(3.0)


def test_h_range_from_ohlcs_uses_atr14():
    ohlcs = [
        _ohlc(f"t{i}", 100.0 + i, 102.0 + i, 99.0 + i, 101.0 + i, 100.0)
        for i in range(20)
    ]
    # every bar range = 3 (high-low); TR with no gaps = 3 → ATR14 = 3
    # → ladder rung 5
    assert h_range_from_ohlcs(ohlcs, 0.05) == pytest.approx(5.0)


def test_h_range_from_ohlcs_needs_bars():
    assert h_range_from_ohlcs([], 0.05) == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# Seed path: drive / hard absorption / Triple-A must not survive seed
# ---------------------------------------------------------------------------


class _RecordedHistory:
    def __init__(self, candles: list[dict]) -> None:
        self._candles = candles

    def fetch_history(self, symbol, interval, limit):
        return list(self._candles)


def _seed_rows(date: str = "2026-09-21", count: int = 30) -> list[dict]:
    """Session candles with one high-volume tight bar (absorption candidate)."""
    rows = []
    for i in range(count):
        price = 100.0 + i * 0.1
        if i == 20:
            # tight range + huge volume: absorption signature bait
            rows.append({
                "time": f"{date}T09:{15 + (i * 5) % 60:02d}:00+05:30" if i < 9 else
                        f"{date}T{10 + (i - 9) // 12:02d}:{(15 + i * 5) % 60:02d}:00+05:30",
                "open": price, "high": price + 0.1, "low": price - 0.1,
                "close": price, "volume": 50000.0, "taker_buy_volume": 25000.0,
                "delta": 0.0,
            })
        else:
            rows.append({
                "time": f"{date}T09:{15 + (i * 2) % 60:02d}:00+05:30" if i < 22 else
                        f"{date}T10:{(i - 22):02d}:00+05:30",
                "open": price, "high": price + 2.0, "low": price - 1.0,
                "close": price + 0.5, "volume": 1000.0,
                "taker_buy_volume": 500.0, "delta": 10.0,
            })
    # Stable increasing times so session_scope keeps one date and analyze sees order.
    for i, r in enumerate(rows):
        minute = 15 + i
        r["time"] = f"{date}T{9 + minute // 60:02d}:{minute % 60:02d}:00+05:30"
    return rows


def _amt_engine(range_bars_enabled: bool = False) -> AMTEngine:
    rows = _seed_rows()
    hist = _RecordedHistory(rows)
    return AMTEngine(
        symbol="NIFTY",
        market="NSE",
        session_levels=SessionLevelStore(),
        history_source=hist,
        interval_seconds=300,
        range_bars_enabled=range_bars_enabled,
        tick_size=0.05,
    )


def test_seed_leaves_no_drive_triple_a_or_absorption_evidence():
    eng = _amt_engine()
    eng.seed()

    an = eng._amt_analyzer
    # Drive tracker must not retain seed-time touches.
    assert an._drive_tracker._levels == {}
    # Triple-A must not have progressed from seed-only bars.
    assert an._triple_a.snapshot().phase == "WAITING"
    # No hard-absorption pending cluster may survive the seed.
    assert an._absorption_detector._pending_candle is None

    dto = eng.last_amt_dto
    assert dto is not None
    assert int(dto.get("driveNumber") or 0) == 0
    assert bool(dto.get("isSecondDrive")) is False
    assert bool(dto.get("driveEntryValid")) is False
    assert str(dto.get("absorptionSide") or "") == ""
    assert float(dto.get("absorptionClusterHigh") or 0.0) == 0.0
    assert float(dto.get("absorptionClusterLow") or 0.0) == 0.0
    assert str(dto.get("tripleAPhase") or "WAITING") == "WAITING"
    assert str(dto.get("tripleASignal") or "") == ""

    # Decision path reads the snapshot (re-derives DTO) — it must be clean too.
    snap = eng.last_snapshot
    assert snap is not None
    assert snap.result.drive_number == 0
    assert snap.result.drive_entry_valid is False
    assert snap.result.absorption_side == ""
    assert snap.result.triple_a_phase == "WAITING"
    assert snap.result.triple_a_signal == ""
    agg = dict(snap.result.aggression_components or {})
    assert bool(agg.get("absorption_detected")) is False


def test_seed_still_fills_profile_and_warmth_when_gated():
    eng = _amt_engine()
    eng.seed()
    # Profile/VA (intended seed use) and order-flow warmth stay intact.
    assert eng.last_amt_dto is not None
    assert float(eng.last_amt_dto.get("poc") or 0.0) > 0.0
    assert eng.warm_bars > 0
    assert eng._amt_candles


def test_range_mode_seed_converts_history_to_range_bars():
    eng = _amt_engine(range_bars_enabled=True)
    eng.seed()
    assert eng._amt_candles
    # Every synth segment's span must respect the H derived from the raw seed.
    from quant.amt_engine import to_float_ohlc  # noqa: F401  (path sanity)
    h = eng.last_range_h or 0.0
    assert h > 0.0
    for c in eng._amt_candles:
        assert (float(c.high) - float(c.low)) <= h + 1e-6
