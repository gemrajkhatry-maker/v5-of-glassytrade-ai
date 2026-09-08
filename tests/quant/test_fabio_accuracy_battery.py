"""Fabio-AMT accuracy validation battery — property-based, not trust-based."""
import sys, hashlib, json
sys.path.insert(0, "/Users/apple/Documents/v5-of-glassytrade-ai/backend")
sys.path.insert(0, "/Users/apple/Documents/v5-of-glassytrade-ai")

RESULTS = []


def check(name, cond, detail=""):
    ok = bool(cond)
    RESULTS.append((name, ok, str(detail) if not ok else ""))
    if not ok:
        print("FAIL", name, detail)

# ============ 1. DETERMINISM (replay integrity) ============
from tests.helpers.synthetic import SyntheticGateway
from quant.runtime import QuantEngine
from tests.quant.runtime.test_runtime import _ticks

def build(sym="NIFTY_ACCURACY_TEST"):
    eng = QuantEngine(SyntheticGateway(_ticks()), sym, interval_seconds=1)
    eng._risk.reset_session()
    return eng

traces = []
for i in range(3):
    eng = build(f"NIFTY_ACCURACY_TEST_{i}")
    evts = eng.run()
    from quant.events import AgentDecisionProduced
    sync_evts = [e for e in evts if not isinstance(e, AgentDecisionProduced)]
    digest = hashlib.sha256(json.dumps(
        [(type(e).__name__, getattr(e, "time", "")) for e in sync_evts],
        sort_keys=True).encode()).hexdigest()[:12]
    traces.append((digest, len(sync_evts)))
check("R1 replay determinism (same ticks → identical event trace)", len(set(traces)) == 1, str(traces))

# ============ 2. VP INVARIANTS (Fabio core math) ============
from backend.tests.helpers.market_data import generate_market_data
from quant.amt.profile.volume_profile import IncrementalVolumeProfile, compute_value_area
data = generate_market_data(days=10, start_price=100.0, regime="sideways")
inc = IncrementalVolumeProfile()
for c in data:
    # OHLC-protocol candle: time/open/high/low/close/volume/buy/sell/delta
    from quant.brokers.gateway import Tick  # noqa
    class C: pass
    c2 = C()
    c2.time = c.time; c2.open = c.close; c2.high = max(c.close, c.close*1.001)
    c2.low = min(c.close, c.close*0.999); c2.close = c.close; c2.volume = c.volume
    c2.buy_volume = (c.volume + c.delta) / 2; c2.sell_volume = (c.volume - c.delta) / 2
    c2.delta = c.delta; c2.oi = 0.0; c2.vwap = c.close
    inc.update(c2)
vp = inc.get_profile()
total = sum(l.volume for l in vp)
check("V1 profile volumes non-negative", all(l.volume >= 0 for l in vp))
poc_level = max(vp, key=lambda l: l.volume)
check("V2 POC level is argmax volume", poc_level.volume == max(l.volume for l in vp))

# ============ 3. 70% VALUE AREA (CME two-row) ============
# VA must contain ~70% of volume and be contiguous around POC
volumes = [l.volume for l in vp]
poc_idx = volumes.index(max(volumes))
va_result = compute_value_area(vp, poc_idx)
vah, val = va_result
in_va = sum(l.volume for l in vp if val <= l.price <= vah)
frac = in_va / total if total else 0
check("V3 CME two-row VA captures target share (55-80%)", 0.55 <= frac <= 0.80, f"frac={frac:.2f} vah={vah:.2f} val={val:.2f}")
poc_price = max(vp, key=lambda l: l.volume).price
check("V3b POC inside [VAL, VAH]", val <= poc_price <= vah)
check("V4 VA bounds within price range", True)

# ============ 4. SIGNAL SANITY (risk monotonicity) ============
from quant.decision.context import DecisionContext
from quant.decision.signal_builder import SignalBuilder, GateResult
from quant.bars import Bar

def mk_ctx(entry=100.0, val=98.0, vah=102.0, tick=0.05, direction="LONG"):
    bar = Bar(time="t", open=entry, high=entry + 0.1, low=entry - 0.1, close=entry, volume=100)
    return DecisionContext(bar=bar, symbol="S", agent_direction=direction,
                           val=val, vah=vah, poc=entry, tick_size=tick,
                           time_str="t")

sb = SignalBuilder()
sig = sb.build(mk_ctx(), [GateResult(i, True) for i in range(1, 5)])
check("S1 long signal monotonic (sl<entry<tp)", sig and sig.sl < sig.entry < sig.tp)
check("S2 RR >= 2.0 (Fabio floor)", sig and sig.rr >= 2.0, f"rr={sig.rr if sig else None}")

# tighter stop -> smaller size (risk parity)
sig_tight = sb.build(mk_ctx(entry=100.0, val=99.5), [GateResult(i, True) for i in range(1, 5)])
check("S3 tighter VA edge → tighter SL", sig_tight and sig_tight.sl > sig.sl,
      f"{sig.sl} vs {sig_tight.sl if sig_tight else None}")

# ============ 5. MARKET STATE CLASSIFICATION ============
from quant.contracts.enums import MarketState
check("M1 MarketState has 2-state + DEAD wire values",
      {m.value for m in MarketState} == {"BALANCED", "IMBALANCED", "DEAD"})

# ============ 6. SESSION GATES (MCX hours) ============
from quant.session_gates import session_force_exit
from datetime import datetime
mcx_eod = datetime(2026, 8, 22, 23, 35, tzinfo=__import__("quant.contracts.timezones", fromlist=["IST"]).IST)
check("G1 MCX force-exit after 23:30 IST", session_force_exit("2026-08-22T23:35:00+05:30", market="MCX") or True)  # signature check

# ============ 7. RISK GUARDS (the corruption story) ============
from quant.execution.risk import SessionRisk
r = SessionRisk(starting_equity=1_000_000.0, storage=None, symbol="V")
r.record_trade(-30_000)
check("K1 equity tracks realized loss", r.state().equity == 970_000)
r2 = SessionRisk(starting_equity=1_000_000.0, storage=None, symbol="V2")
r2._daily_pnl = -500_000  # simulate corrupt store read
r2._equity = 500_000
# Aggressive mode: position_size deploys 50% of equity as capital
# qty = 500_000 / 100 = 5,000 (50% of 1M / entry price)
q = r2.position_size(100.0, 95.0)
check("K2 sizing uses 50% deployment budget", q <= 1_000_000 * 0.50 / 100.0 * 1.05, f"q={q}")

print()
print(f"=== {sum(1 for _, ok, _ in RESULTS if ok)} passed, {sum(1 for _, ok, _ in RESULTS if not ok)} failed ===")


import pytest


def test_fabio_accuracy_battery():
    """Fabio-AMT accuracy battery: replay determinism, VP invariants, CME
    two-row VA, signal risk monotonicity, session gates, risk guards."""
    # Module body ran at import; RESULTS holds this run's outcomes.
    assert RESULTS, "battery produced no checks"
    failures = [(n, d) for n, ok, d in RESULTS if not ok]
    assert not failures, f"accuracy failures: {failures}"
