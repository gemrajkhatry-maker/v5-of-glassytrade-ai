from types import SimpleNamespace

import pytest

from quant.aggregator import BarAggregator
from quant.amt_engine import AMTEngine
from quant.bars import Bar
from quant.brokers.gateway import Tick
from quant.engine.tick_handler import TickHandler
from quant.execution.seed_scheduler import HistorySeedScheduler
from quant.session_levels import SessionLevelStore


class RecordedHistory:
    """A fixed captured-session adapter exercising the production seed scheduler."""

    def __init__(self, candles):
        self._candles = candles

    def fetch_history(self, symbol, interval, limit):
        return list(self._candles)


def _candles(date="2026-09-21", count=4):
    rows = []
    for i in range(count):
        price = 100.0 + i
        rows.append(
            {
                "time": f"{date}T09:{15 + i * 5:02d}:00+05:30",
                "open": price,
                "high": price + 2.0,
                "low": price - 1.0,
                "close": price + 1.0,
                "volume": 100.0 * (i + 1),
                "taker_buy_volume": 0.0,
                "delta": float((i + 1) * 10),
            }
        )
    return rows


def _engine(store=None, history=None):
    store = store or SessionLevelStore()
    scheduler = (
        HistorySeedScheduler(
            history, min_interval_sec=0.0, max_retries=1, base_delay_sec=0.0
        )
        if history is not None
        else None
    )
    return AMTEngine(
        symbol="NIFTY",
        market="NSE",
        session_levels=store,
        history_source=history,
        seed_scheduler=scheduler,
        interval_seconds=300,
    )


def test_seed_replays_every_bar_into_cvd_vwap_and_ib():
    rows = _candles()
    eng = _engine(history=RecordedHistory(rows))

    eng.seed()

    analyzer = eng._amt_analyzer
    expected_vwap = sum(
        ((r["high"] + r["low"] + r["close"]) / 3.0) * r["volume"]
        for r in rows
    ) / sum(r["volume"] for r in rows)
    assert analyzer._cvd_tracker.value == pytest.approx(sum(r["delta"] for r in rows))
    assert analyzer._vwap.vwap_value == pytest.approx(expected_vwap)
    assert analyzer._ib_tracker.ib_high == max(r["high"] for r in rows)
    assert analyzer._ib_tracker.ib_low == min(r["low"] for r in rows)
    assert len(analyzer._ib_tracker._ib_candles) == len(rows)
    assert eng.last_amt_dto["time"] == rows[-1]["time"]


def test_rollover_persists_prior_levels_resets_session_and_updates_npoc():
    store = SessionLevelStore()
    eng = _engine(store=store)
    for row in _candles(count=5):
        eng.analyze(
            Bar(
                time=row["time"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                buy_volume=(row["volume"] + row["delta"]) / 2.0,
                sell_volume=(row["volume"] - row["delta"]) / 2.0,
                delta=row["delta"],
            )
        )
    prior = dict(eng.last_amt_dto)

    eng.analyze(
        Bar(
            time="2026-09-22T09:15:00+05:30",
            open=110.0,
            high=112.0,
            low=109.0,
            close=111.0,
            volume=500.0,
            buy_volume=300.0,
            sell_volume=200.0,
            delta=100.0,
        )
    )

    saved = store.load_levels("NIFTY")
    assert saved["date"] == "2026-09-21"
    assert saved["poc"] == pytest.approx(prior["poc"])
    assert saved["vah"] == pytest.approx(prior["valueAreaHigh"])
    assert saved["val"] == pytest.approx(prior["valueAreaLow"])
    assert eng._prior == saved
    assert len(eng._amt_candles) == 1
    active = store.get_active_npocs("NIFTY")
    assert any(item["session_date"] == "2026-09-21" for item in active)


def _decision_attempt(dto_time, micro_start):
    decisions = []
    eng = _engine()
    eng._last_amt_dto = {"time": dto_time, "poc": 100.0}
    handler = TickHandler(
        symbol="NIFTY",
        macro_aggregator=BarAggregator(interval_seconds=300),
        micro_aggregator=BarAggregator(interval_seconds=60),
        amt_engine=eng,
        state_getter=lambda: SimpleNamespace(position=None),
        manage_tick_exit_callback=lambda price, time: None,
        decide_callback=lambda *args: decisions.append(args),
        on_bar_closed_callback=lambda bar: None,
        manage_exit_callback=lambda dto, bar: None,
    )
    handler.process_tick(Tick(time=micro_start, price=100.0, volume=10.0))
    minute = int(micro_start[14:16]) + 1
    handler.process_tick(
        Tick(
            time=f"{micro_start[:14]}{minute:02d}{micro_start[16:]}",
            price=101.0,
            volume=10.0,
        )
    )
    return decisions


def test_micro_decision_accepts_macro_dto_at_one_interval_boundary():
    decisions = _decision_attempt(
        "2026-09-22T09:16:00+05:30", "2026-09-22T09:21:00+05:30"
    )
    assert len(decisions) == 1


@pytest.mark.parametrize("dto_time", ["", "2026-09-22T09:10:00+05:30"])
def test_micro_decision_rejects_missing_or_stale_macro_time(dto_time):
    decisions = _decision_attempt(dto_time, "2026-09-22T09:21:00+05:30")
    assert decisions == []
