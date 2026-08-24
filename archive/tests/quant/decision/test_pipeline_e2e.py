from quant.bars import Bar
from quant.coordinator import AuctionCoordinator
from quant.contracts.enums import SignalType
from quant.decision.context import DecisionContext
from quant.decision.pipeline import GatePipeline
from quant.decision.signal_builder import SignalBuilder


def _session():
    # 25 quiet bars -> absorption spike -> gentle rise just past VWAP upper
    # band (drives AGGRESSION LONG; close stays close to value so the R:R
    # gate's structural stop is within its max stop distance)
    out = [Bar(time=f"t{i}", open=100, high=101, low=99, close=100, volume=100)
           for i in range(25)]
    out.append(Bar(time="t25", open=100, high=100, low=100, close=100,
                   volume=500, buy_volume=450, sell_volume=50, delta=400))
    # absorption spike + two accumulation bars as zero-range bars AT the POC
    # bucket, so the profile peak is a single bucket and POC sits at 100
    out.append(Bar(time="t26", open=100, high=100, low=100, close=100,
                   volume=100, buy_volume=60, sell_volume=40))
    out.append(Bar(time="t27", open=100, high=100, low=100, close=100,
                   volume=100, buy_volume=60, sell_volume=40))
    for i in range(28, 32):
        close = 100.3 + (i - 28) * 0.1
        out.append(Bar(time=f"t{i}", open=close - 0.2, high=close + 0.2,
                       low=close - 0.2, close=close, volume=100))
    return out


def test_kernel_to_signal_flow():
    coord = AuctionCoordinator()
    pipe = GatePipeline()
    sb = SignalBuilder()
    last_state = None
    for b in _session():
        last_state = coord.on_bar_close(b)
        if last_state.triple_a_signal == "LONG":
            ctx = DecisionContext(state=last_state, bar=b, symbol="SYM",
                                  agent_direction="LONG", agent_probability=0.7,
                                  session_open=True, warmup_complete=True,
                                  position_open=False, cooldown_remaining_sec=0,
                                  risk_halted=False)
            results = pipe.evaluate(ctx)
            sig = sb.build(ctx, results)
            assert sig is not None and sig.type == SignalType.BUY
            return
    assert False, "LONG signal never fired through the full pipeline"
