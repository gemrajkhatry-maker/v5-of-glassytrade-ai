# tests/quant/test_full_stack.py
"""Full-stack lifecycle: ticks -> bars -> AuctionState -> journal -> gates ->
signal -> OMS open -> exit engine -> OMS close -> risk record."""

from quant.bars import Bar
from quant.brokers.gateway import Tick
from tests.helpers.synthetic import SyntheticGateway
from quant.coordinator import AuctionCoordinator
from quant.decision.context import DecisionContext
from quant.decision.pipeline import GatePipeline
from quant.decision.signal_builder import SignalBuilder
from quant.execution.exits import ExitEngine
from quant.execution.oms import PaperOMS
from quant.execution.risk import SessionRisk


class _StubJournal:
    """In-test stub replacing the dead advisory.entry_journal module."""

    def __init__(self):
        self.entries = []

    def analyze(self, state, symbol):
        self.entries.append(type("Entry", (), {"decision": "LONG"})())


def _ticks():
    out = [Tick(f"t{i}", 100.0, 10, 6, 4) for i in range(300)]
    out.append(Tick("t300", 100.0, 500, 450, 50))
    # two bars of accumulation at POC so ABSORBING -> ACCUMULATING can fire
    out.append(Tick("t301", 100.0, 10, 6, 4))
    out.append(Tick("t302", 100.0, 10, 6, 4))
    for i in range(1, 9):
        out.append(Tick(f"t{302+i}", 100.0 + i * 0.2, 10, 6, 4))
    return out


def _bar(tick, spike=False):
    if spike:
        # zero-range bar AT price: single-bucket POC so near-POC accumulation
        # holds and AGGRESSION can fire on the breakout bar
        return Bar(time=tick.time, open=tick.price, high=tick.price,
                   low=tick.price, close=tick.price, volume=tick.volume,
                   buy_volume=tick.buy_volume, sell_volume=tick.sell_volume,
                   delta=tick.buy_volume - tick.sell_volume)
    return Bar(time=tick.time, open=tick.price, high=tick.price + 0.5,
               low=tick.price - 0.5, close=tick.price, volume=tick.volume,
               buy_volume=tick.buy_volume, sell_volume=tick.sell_volume,
               delta=tick.buy_volume - tick.sell_volume)


def test_full_stack_lifecycle():
    gw = SyntheticGateway(_ticks())
    gw.subscribe("SYM")
    coord = AuctionCoordinator()
    pipe = GatePipeline()
    sb = SignalBuilder()
    oms = PaperOMS()
    exits = ExitEngine(time_stop_bars=4)
    risk = SessionRisk()
    journal = _StubJournal()

    position = None
    entry_step = 0
    fills = []
    step = 0
    while True:
        tick = gw.next_tick()
        if tick is None:
            break
        step += 1
        bar = _bar(tick, spike=(tick.time == "t300"))
        state = coord.on_bar_close(bar)

        journal.analyze(state, "SYM")

        if position is not None:
            held = step - entry_step
            dec = exits.evaluate(position, state, bar_index=held)
            if dec.should_exit:
                fill = oms.close(position, dec.close_price, bar.time, dec.reason)
                fills.append(fill)
                risk.record_trade(fill.pnl)
                position = None
            continue

        ctx = DecisionContext(state=state, bar=bar, symbol="SYM",
                              agent_direction="LONG", agent_probability=0.7,
                              market_state="IMBALANCED",
                              session_open=True, warmup_complete=True,
                              position_open=False, cooldown_remaining_sec=0,
                              risk_halted=False)
        results = pipe.evaluate(ctx)
        if all(r.passed for r in results):
            sig = sb.build(ctx, results)
            if sig is not None:
                qty = risk.position_size(sig.entry, sig.sl)
                position = oms.submit(sig, qty)
                entry_step = step

    assert position is None
    assert len(fills) >= 1
    assert fills[0].position.size > 0
    assert fills[0].reason in {"SL", "TP", "TRAIL", "TIME", "CVD_KILL"}
    assert len(journal.entries) > 100
    assert all(e.decision == "LONG" for e in journal.entries)
    assert risk.state().daily_pnl != 0.0
