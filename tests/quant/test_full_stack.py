# tests/quant/test_full_stack.py
"""Full-stack lifecycle: ticks -> bars -> AuctionState -> journal -> gates ->
signal -> OMS open -> exit engine -> OMS close -> risk record."""

from quant.amt_engine import AMTEngine
from quant.bars import Bar
from quant.brokers.gateway import Tick
from quant.decision.decision_service import DecisionService
from quant.decision.context_builder import DecisionContextBuilder
from quant.execution.exits import ExitEngine
from quant.execution.oms import PaperOMS
from quant.execution.risk import SessionRisk
from quant.session_levels import SessionLevelStore
from tests.helpers.synthetic import SyntheticGateway


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
    for i in range(1, 25):
        out.append(Tick(f"t{302+i}", 100.0 + min(i, 8) * 0.2, 10, 6, 4))
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
    engine = AMTEngine(symbol="SYM", market="MCX", session_levels=SessionLevelStore())
    builder = DecisionContextBuilder()
    service = DecisionService()
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
        amt_dto = engine.analyze(bar)

        journal.analyze(amt_dto, "SYM")

        if position is not None:
            held = step - entry_step
            dec = exits.evaluate(position, bar_close=bar.close, amt_dto=amt_dto, bar_index=held)
            if dec.should_exit:
                fill = oms.close(position, dec.close_price, bar.time, dec.reason)
                fills.append(fill)
                risk.record_trade(fill.pnl)
                position = None
            continue

        ctx = builder.build(
            bar=bar,
            symbol="SYM",
            market="MCX",
            contract_expiry=None,
            tick_size=0.05,
            bar_index=step,
            warm_bars=20,
            cooldown_remaining_sec=0.0,
            risk_state=risk.state(),
            amt_dto=amt_dto,
        )
        decision = service.evaluate(ctx)
        if decision.approved and decision.signal is not None:
            sig = decision.signal
            qty = risk.position_size(sig.entry, sig.sl)
            position = oms.submit(sig, qty)
            entry_step = step

    assert position is None
    assert fills == []
    assert len(journal.entries) > 100
    assert risk.state().trades_today == 0
