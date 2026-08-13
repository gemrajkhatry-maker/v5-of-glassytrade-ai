import sys
sys.path.insert(0, "/Users/apple/Documents/v5-of-glassytrade-ai")

from quant.brokers.gateway import Tick
from tests.helpers.synthetic import SyntheticGateway
from quant.runtime import QuantEngine
from quant.events import AuctionUpdated
from quant.decision.context import DecisionContext
from quant.decision.pipeline import GatePipeline
from quant.decision.signal_builder import SignalBuilder, is_stop_too_thin
from quant.runtime import _DETERMINISTIC_CONVICTION

out = [Tick(f"t{i}", 99.95 if i % 2 == 0 else 100.05, 10, 6, 4)
       for i in range(300)]
out.append(Tick("t300", 100.0, 500, 50, 450))
for i in range(1, 6):
    out.append(Tick(f"t{300 + i}", 100.0, 10, 6, 4))
for i, price in enumerate([99.7, 99.4, 99.1, 98.8]):
    out.append(Tick(f"t{306 + i}", price, 10, 6, 4))

eng = QuantEngine(SyntheticGateway(out), "SYM", interval_seconds=1)
trace = eng.run()

for e in trace:
    if isinstance(e, AuctionUpdated) and e.auction.triple_a_phase == "AGGRESSION":
        s = e.auction
        d = e.auction.triple_a_signal
        ctx = DecisionContext(
            state=s, bar=None, symbol="SYM", agent_direction=d,
            agent_probability=_DETERMINISTIC_CONVICTION, tick_size=0.05,
        )
        results = GatePipeline().evaluate(ctx)
        print(f"bar {e.time} dir={d} close={s.close:.4f} vah={s.volume_profile.vah:.4f} "
              f"val={s.volume_profile.val:.4f} poc={s.volume_profile.poc:.4f} "
              f"step={s.volume_profile.step:.4f} nearest={s.location.nearest_level} "
              f"gates={[(g.gate, g.passed, g.reason[:30]) for g in results]}")
        sig = SignalBuilder().build(ctx, results)
        if sig is None:
            print(f"  -> builder returned None")
        else:
            print(f"  -> signal {sig.type} entry={sig.entry} sl={sig.sl} tp={sig.tp} rr={sig.rr}")
        # manual stop-thin check
        vah = float(s.volume_profile.vah)
        step = float(s.volume_profile.step)
        anchor = vah if float(s.close) < vah else float(s.location.nearest_level)
        sl = anchor + step if step > 0 else anchor
        print(f"  -> manual SHORT sl={sl} thin={is_stop_too_thin(float(s.close), sl)}")
