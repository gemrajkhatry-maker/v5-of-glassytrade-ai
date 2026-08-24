import json
import pathlib

from quant.bars import Bar
from quant.coordinator import AuctionCoordinator


def _session_bars():
    # Deterministic 60-bar synthetic session, exercised through the whole machine:
    #
    #   bars 0-24   quiet 1-tick range at 100, vol 100     -> WAITING
    #   bar  25     volume spike 5x, zero range at 100, 90% buys -> BUY absorption
    #   bars 26-27  accumulation AT POC (100)               -> ABSORBING -> ACCUMULATING (bar 27)
    #   bars 28-31  breakout 104..116                       -> AGGRESSION (LONG at bar 28)
    #   bars 32-41  quiet back at 100, vol 100              -> WAITING (stale absorption ages out)
    #   bar  42     volume spike 5x, zero range at 100, 90% sells -> SELL absorption
    #   bars 43-44  accumulation AT POC (100)               -> ABSORBING -> ACCUMULATING (bar 44)
    #   bars 45-48  breakdown 96..84                        -> AGGRESSION (SHORT at bar 45)
    #   bars 49-59  quiet back at 100, vol 100              -> WAITING
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

    for i in range(49, 60):
        out.append(Bar(time=f"t{i}", open=100, high=101, low=99, close=100, volume=100))
    return out


def test_session_reproduces_identically():
    c1 = AuctionCoordinator()
    trace1 = [c1.on_bar_close(b) for b in _session_bars()]
    c2 = AuctionCoordinator()
    trace2 = [c2.on_bar_close(b) for b in _session_bars()]
    assert trace1 == trace2  # frozen dataclasses -> structural equality


def test_golden_file_matches():
    fp = pathlib.Path(__file__).parent / "fixtures" / "session_a.json"
    expected = json.loads(fp.read_text())
    c = AuctionCoordinator()
    trace = [c.on_bar_close(b) for b in _session_bars()]
    got = [{"time": t.time, "phase": t.triple_a_phase,
            "vwap": round(t.vwap.value, 4)} for t in trace]
    assert got == expected
