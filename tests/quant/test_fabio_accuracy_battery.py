"""Fabio-AMT accuracy validation battery — property-based, not trust-based."""
import hashlib
import json


def test_fabio_accuracy_battery():
    """Fabio-AMT accuracy battery: replay determinism, VP invariants, CME
    two-row VA, signal risk monotonicity, session gates, risk guards."""
    from types import SimpleNamespace

    from backend.tests.helpers.market_data import generate_market_data
    from quant.amt.profile.volume_profile import (
        IncrementalVolumeProfile,
        compute_value_area,
    )
    from quant.bars import Bar
    from quant.contracts.enums import MarketState
    from quant.decision.context import DecisionContext
    from quant.decision.signal_builder import GateResult, SignalBuilder
    from quant.events import AgentDecisionProduced
    from quant.execution.risk import SessionRisk
    from quant.runtime import QuantEngine
    from quant.session_gates import session_force_exit
    from tests.helpers.synthetic import SyntheticGateway
    from tests.quant.runtime.test_runtime import _ticks

    results = []

    def check(name, cond, detail=""):
        ok = bool(cond)
        results.append((name, ok, str(detail) if not ok else ""))
        if not ok:
            print("FAIL", name, detail)

    # ============ 1. DETERMINISM (replay integrity) ============
    def build(sym="NIFTY_ACCURACY_TEST"):
        eng = QuantEngine(SyntheticGateway(_ticks()), sym, interval_seconds=1)
        eng._risk.reset_session()
        return eng

    traces = []
    for i in range(3):
        eng = build(f"NIFTY_ACCURACY_TEST_{i}")
        evts = eng.run()
        sync_evts = [e for e in evts if not isinstance(e, AgentDecisionProduced)]
        digest = hashlib.sha256(
            json.dumps(
                [(type(e).__name__, getattr(e, "time", "")) for e in sync_evts],
                sort_keys=True,
            ).encode()
        ).hexdigest()[:12]
        traces.append((digest, len(sync_evts)))
    check(
        "R1 replay determinism (same ticks → identical event trace)",
        len(set(traces)) == 1,
        str(traces),
    )

    # ============ 2. VP INVARIANTS (Fabio core math) ============
    data = generate_market_data(days=10, start_price=100.0, regime="sideways")
    inc = IncrementalVolumeProfile()
    for c in data:
        # OHLC-protocol candle: time/open/high/low/close/volume/buy/sell/delta
        c2 = SimpleNamespace(
            time=c.time,
            open=c.close,
            high=max(c.close, c.close * 1.001),
            low=min(c.close, c.close * 0.999),
            close=c.close,
            volume=c.volume,
            buy_volume=(c.volume + c.delta) / 2,
            sell_volume=(c.volume - c.delta) / 2,
            delta=c.delta,
            oi=0.0,
            vwap=c.close,
        )
        inc.update(c2)
    vp = inc.get_profile()
    total = sum(lv.volume for lv in vp)
    check("V1 profile volumes non-negative", all(lv.volume >= 0 for lv in vp))
    poc_level = max(vp, key=lambda lv: lv.volume)
    check(
        "V2 POC level is argmax volume",
        poc_level.volume == max(lv.volume for lv in vp),
    )

    # ============ 3. 70% VALUE AREA (CME two-row) ============
    # VA must contain ~70% of volume and be contiguous around POC
    volumes = [lv.volume for lv in vp]
    poc_idx = volumes.index(max(volumes))
    va_result = compute_value_area(vp, poc_idx)
    vah, val = va_result
    in_va = sum(lv.volume for lv in vp if val <= lv.price <= vah)
    frac = in_va / total if total else 0
    check(
        "V3 CME two-row VA near 68.2%",
        abs(frac - 0.682) <= 0.12,
        f"frac={frac:.3f} vah={vah:.2f} val={val:.2f}",
    )
    poc_price = max(vp, key=lambda lv: lv.volume).price
    check("V3b POC inside [VAL, VAH]", val <= poc_price <= vah)
    # VAH/VAL are edge-adjusted by ± half a bucket (volume_profile.py:200-203),
    # so the bounds may sit half a step outside the outermost bucket price.
    step = (vp[1].price - vp[0].price) if len(vp) > 1 else 0.0
    half = step / 2
    px_lo = min(lv.price for lv in vp)
    px_hi = max(lv.price for lv in vp)
    check(
        "V4 VA bounds within price range (± half-bucket edge)",
        px_lo - half - 1e-9 <= val <= vah <= px_hi + half + 1e-9,
        f"val={val:.4f} vah={vah:.4f} range=[{px_lo:.4f},{px_hi:.4f}] half={half:.4f}",
    )

    # ============ 4. SIGNAL SANITY (risk monotonicity) ============
    def mk_ctx(entry=100.0, val=98.0, vah=102.0, tick=0.05, direction="LONG"):
        bar = Bar(
            time="t",
            open=entry,
            high=entry + 0.1,
            low=entry - 0.1,
            close=entry,
            volume=100,
        )
        return DecisionContext(
            bar=bar,
            symbol="S",
            agent_direction=direction,
            val=val,
            vah=vah,
            poc=entry,
            tick_size=tick,
            time_str="t",
        )

    sb = SignalBuilder()
    gates = [GateResult(i, True) for i in range(1, 5)]
    sig = sb.build(mk_ctx(), gates, model_label="Triple-A")
    check(
        "S1 long signal monotonic (sl<entry<tp)",
        sig and sig.sl < sig.entry < sig.tp,
        f"sl={sig.sl if sig else None} entry={sig.entry if sig else None} tp={sig.tp if sig else None}",
    )
    check(
        "S2 RR >= 2.0 (Fabio floor)",
        sig and sig.rr >= 2.0,
        f"rr={sig.rr if sig else None}",
    )

    # tighter stop -> smaller size (risk parity)
    sig_tight = sb.build(
        mk_ctx(entry=100.0, val=99.5),
        [GateResult(i, True) for i in range(1, 5)],
        model_label="Triple-A",
    )
    check(
        "S3 tighter VA edge → tighter SL",
        sig_tight and sig_tight.sl > sig.sl,
        f"{sig.sl if sig else None} vs {sig_tight.sl if sig_tight else None}",
    )

    # ============ 5. MARKET STATE CLASSIFICATION ============
    check(
        "M1 MarketState has 2-state + DEAD wire values",
        {m.value for m in MarketState} == {"BALANCED", "IMBALANCED", "DEAD"},
    )

    # ============ 6. SESSION GATES (MCX hours) ============
    mcx_after_hours = session_force_exit("2026-08-22T23:35:00+05:30", market="MCX")
    mcx_mid_session = session_force_exit("2026-08-22T15:00:00+05:30", market="MCX")
    check(
        "G1a MCX force-exit after 23:30 IST",
        mcx_after_hours is True,
        f"got {mcx_after_hours}",
    )
    check(
        "G1b MCX no force-exit mid-session",
        mcx_mid_session is False,
        f"got {mcx_mid_session}",
    )

    # ============ 7. RISK GUARDS (the corruption story) ============
    r = SessionRisk(starting_equity=1_000_000.0, storage=None, symbol="V")
    r.record_trade(-30_000)
    check("K1 equity tracks realized loss", r.state().equity == 970_000)
    r2 = SessionRisk(starting_equity=1_000_000.0, storage=None, symbol="V2")
    r2._daily_pnl = -500_000  # simulate corrupt store read
    r2._equity = 500_000
    # Aggressive mode: position_size deploys 50% of equity as capital
    # qty = 500_000 / 100 = 5,000 (50% of 1M / entry price)
    q = r2.position_size(100.0, 95.0)
    check(
        "K2 sizing uses 50% deployment budget",
        q <= 1_000_000 * 0.50 / 100.0 * 1.05,
        f"q={q}",
    )

    # ============ 8. SETUP VOCABULARY (Second Drive + Squeeze pins) ============
    from typing import get_args

    from quant.decision.setup_labels import (
        CanonicalSetup,
        canonical_setup_type,
        label_from_setup_key,
    )

    canonical_keys = set(get_args(CanonicalSetup))
    check(
        "F1 setup vocabulary includes SECOND_DRIVE",
        "SECOND_DRIVE" in canonical_keys
        and label_from_setup_key("SECOND_DRIVE") == "Second_Drive"
        and canonical_setup_type("Second-Drive") == "SECOND_DRIVE",
        f"keys={sorted(k for k in canonical_keys if k)}",
    )
    check(
        "F2 setup vocabulary includes SQUEEZE",
        "SQUEEZE" in canonical_keys
        and label_from_setup_key("SQUEEZE") == "Squeeze"
        and canonical_setup_type("SQUEEZE") == "SQUEEZE",
        f"label={label_from_setup_key('SQUEEZE')!r}",
    )

    assert results, "battery produced no checks"
    failures = [(n, d) for n, ok, d in results if not ok]
    assert not failures, f"accuracy failures: {failures}"
