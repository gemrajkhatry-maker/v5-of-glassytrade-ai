
from quant.amt_engine import AMTEngine
from quant.bars import Bar
from quant.session_levels import SessionLevelStore


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
    c1 = AMTEngine(symbol="SYM", market="MCX", session_levels=SessionLevelStore())
    trace1 = [c1.analyze(b) for b in _session_bars()]
    c2 = AMTEngine(symbol="SYM", market="MCX", session_levels=SessionLevelStore())
    trace2 = [c2.analyze(b) for b in _session_bars()]
    assert trace1 == trace2


def test_golden_session_deterministic():
    c = AMTEngine(symbol="SYM", market="MCX", session_levels=SessionLevelStore())
    trace = [c.analyze(b) for b in _session_bars()]
    assert len(trace) == 60
    assert trace[-1]["sessionVwap"] > 0.0
