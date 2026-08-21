"""Attribute the 50k-tick memory growth to source lines (tracemalloc top stats)."""
import sys
import tracemalloc

sys.path.insert(0, "backend")
sys.path.insert(0, ".")

from quant.brokers.gateway import Tick
from quant.runtime import QuantEngine


class FakeGateway:
    def __init__(self, ticks):
        self._ticks = list(ticks)
        self._i = 0
    def subscribe(self, symbol): ...
    def next_tick(self):
        if self._i >= len(self._ticks):
            return None
        t = self._ticks[self._i]
        self._i += 1
        return t


ticks = [Tick(time=str(2_000_000 + i), price=100.0 + (i % 100) * 0.05,
              volume=1.0, buy_volume=0.6, sell_volume=0.4) for i in range(50_000)]
eng = QuantEngine(FakeGateway(ticks), "MEMTEST", interval_seconds=60)

tracemalloc.start(1)
eng.run()
snap = tracemalloc.take_snapshot()
cur, peak = tracemalloc.get_traced_memory()
print(f"current={cur/1e6:.1f}MB peak={peak/1e6:.1f}MB")
for stat in snap.statistics("lineno")[:15]:
    print(stat)

# Who retains the footprint dicts?
import gc
from quant.events import AmtUpdated
amt_events = [e for e in eng._trace if isinstance(e, AmtUpdated)]
print("AmtUpdated in trace:", len(amt_events))
sizes = [len(e.amt.get("footprints", {})) for e in amt_events[:5]]
print("footprints per event (sample):", sizes)
# non-trace retention?
for name in dir(eng._amt_engine):
    if name.startswith("_"):
        continue
    v = getattr(eng._amt_engine, name, None)
    if isinstance(v, (list, dict)) and len(v) > 500:
        print("engine._amt_engine." + name, type(v).__name__, len(v))
pm = getattr(eng, "_projector", None)
snap_state = pm._state if hasattr(pm, "_state") else None
if snap_state:
    for k, vs in list(snap_state.items())[:2]:
        for attr, val in vars(vs).items() if hasattr(vs, "__dict__") else []:
            if isinstance(val, (list, dict)) and len(val) > 1000:
                print("projector", k, attr, len(val))

# Deep-dive: sample one footprint level dict and walk referrers up 3 hops.
import gc as _gc
target = None
for e in amt_events:
    for fp in e.amt.get("footprints", {}).values():
        if fp["levels"]:
            target = fp["levels"][0]
            break
    if target:
        break
seen = set()
def walk(obj, path, depth):
    if depth > 4 or id(obj) in seen:
        return
    seen.add(id(obj))
    refs = _gc.get_referrers(obj)
    cnt = 0
    for r in refs:
        if isinstance(r, (list, dict, tuple)) or r.__class__.__name__ in ("frame", "function"):
            t = type(r).__name__
            if t == "frame":
                print(path, "-> <frame>", r.f_code.co_name)
            else:
                print(path, f"-> {t}[len={len(r)}]")
                walk(r, path + f"/{t}{len(r)}", depth + 1)
        cnt += 1
        if cnt > 3:
            break
walk(target, "level", 0)

total_levels = sum(
    len(lvl)
    for e in amt_events
    for fp in e.amt.get("footprints", {}).values()
    for lvl in [fp["levels"]]
)
print("TOTAL footprint level dicts retained in engine._trace:", total_levels)
per_event = [
    sum(len(fp["levels"]) for fp in e.amt.get("footprints", {}).values())
    for e in amt_events[-5:]
]
print("levels per AmtUpdated (last 5):", per_event)
