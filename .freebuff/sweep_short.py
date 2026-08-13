import sys
sys.path.insert(0, "/Users/apple/Documents/v5-of-glassytrade-ai")

from quant.brokers.gateway import Tick
from tests.helpers.synthetic import SyntheticGateway
from quant.runtime import QuantEngine
from quant.events import SignalApproved


def try_session(r, falls):
    out = [Tick(f"t{i}", 100.0 - r / 2 if i % 2 == 0 else 100.0 + r / 2, 10, 6, 4)
           for i in range(300)]
    out.append(Tick("t300", 100.0, 2000, 100, 1900))
    for i in range(1, 6):
        out.append(Tick(f"t{300 + i}", 100.0, 10, 6, 4))
    for i, price in enumerate(falls):
        out.append(Tick(f"t{306 + i}", price, 10, 6, 4))
    eng = QuantEngine(SyntheticGateway(out), "SYM", interval_seconds=1)
    trace = eng.run()
    sigs = [e for e in trace if isinstance(e, SignalApproved)]
    if sigs:
        s = sigs[0].signal
        return f"range={r} falls={falls} -> {s.type} entry={s.entry:.2f} sl={s.sl:.2f} tp={s.tp:.2f} rr={s.rr:.2f}"
    return f"range={r} falls={falls} -> no signal"


for r in (0.2, 0.4, 0.6, 0.8, 1.0, 1.2):
    print(try_session(r, [99.6, 99.4, 99.1, 98.8]))
print("--- bigger spike + steeper falls ---")
for r in (0.4, 0.6, 0.8, 1.0):
    print(try_session(r, [99.3, 98.8, 98.3, 97.8]))
