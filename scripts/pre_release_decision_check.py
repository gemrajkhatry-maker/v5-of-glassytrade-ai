#!/usr/bin/env python3
"""Pre-release decision-integrity check.

Companion to ``docs/PRE_RELEASE_DECISION_INTEGRITY_CHECKLIST.md``. Automates the
machine-checkable half of the checklist:

  A. Flow authority   — is there exactly one entry, gate, sizing and exit authority?
  B. Information flow — does the AMT DTO -> DecisionContext -> model contract hold?
  C. Behaviour        — do the canonical gates and exit sources actually fire?
  D. Suites           — do the decision/strategy/exit tests pass?

Usage:
    PYTHONPATH=. python scripts/pre_release_decision_check.py [--json out.json] [--skip-suites]

Exit code 0 = every FAIL-level check passed. WARN items are printed but do not
fail the run; each one is explained in the checklist doc.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUANT = ROOT / "quant"


@dataclass
class Result:
    section: str
    name: str
    ok: bool
    detail: str = ""
    warn: bool = False
    data: dict = field(default_factory=dict)


RESULTS: list[Result] = []


def _add(section: str, name: str, ok: bool, detail: str = "", warn: bool = False, **data):
    RESULTS.append(Result(section, name, ok, detail, warn, data))


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


# ---------------------------------------------------------------------------
# A. Flow authority (static)
# ---------------------------------------------------------------------------

def check_entry_authority():
    src = _read("quant/runtime.py")
    calls_should_enter = src.count("self._strategy.should_enter(")
    direct_service = re.findall(r"self\._decision_service\.evaluate\(", src)
    _add(
        "A. Flow authority", "single entry seam (strategy.should_enter)",
        calls_should_enter >= 2 and not direct_service,
        f"should_enter call sites={calls_should_enter}, direct DecisionService.evaluate={len(direct_service)}",
    )


def check_no_bare_absorption():
    bare = re.compile(r'absorption[a-z_]*\s*(?:==|!=)\s*"(BUY|SELL)"|in\s*\(\s*"(?:BUY|SELL)"\s*,\s*"(?:BUY|SELL)"\s*\)')
    offenders = []
    for path in QUANT.rglob("*.py"):
        if path.name.startswith("test_"):
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "absorption" in line.lower() and bare.search(line):
                offenders.append(f"{_rel(path)}:{i}")
    _add(
        "A. Flow authority", "no bare absorption string compares (canonical _ABSORBED)",
        not offenders,
        f"offenders: {offenders or 'none'}",
    )


def check_exit_source_stamp():
    src = _read("quant/position_manager.py")
    has_stamp = 'last_exit_source = f"DETERMINISTIC:{exit_dec.reason}"' in src
    _add(
        "A. Flow authority", "closes bypassing ExitEngine stamp an exit source",
        has_stamp,
        "central stamp in PositionManager._execute_full_close",
    )


def check_single_sizing_authority():
    rt = _read("quant/runtime.py")
    dead = list(QUANT.rglob("risk_sizer.py")) + list(QUANT.rglob("decision/intent.py"))
    ok = "self._risk.position_size(" in rt and "clamp_quantity(" in rt and not dead
    _add(
        "A. Flow authority", "one sizing authority (SessionRisk.position_size + clamp_quantity)",
        ok,
        f"runtime uses SessionRisk={('self._risk.position_size(' in rt)}, "
        f"clamp_quantity={('clamp_quantity(' in rt)}, dead scaffolding={[ _rel(p) for p in dead ] or 'none'}",
    )


# ---------------------------------------------------------------------------
# B. Information flow (contract coverage + shared-buffer integrity)
# ---------------------------------------------------------------------------

# Keys context_builder reads that the AMT DTO never emits. Each is a documented
# legacy fallback alias, not a live contract gap.
_KNOWN_FALLBACK_ALIASES = {"acceptance", "rejection", "legLvn", "data_quality", "optionGreekDelta"}


def check_dto_key_coverage():
    cb = _read("quant/decision/context_builder.py")
    consumed = set(re.findall(r'amt_dto\.get\(\s*"([^"]+)"', cb))
    consumed |= set(re.findall(r'amt_dto\[\s*"([^"]+)"\s*\]', cb))
    dto = _read("quant/amt/dto.py")
    produced = set(re.findall(r'^\s*"([A-Za-z_][A-Za-z0-9_]*)":', dto, re.M))
    missing = sorted(consumed - produced - _KNOWN_FALLBACK_ALIASES)
    _add(
        "B. Information flow", "every DecisionContext field has an AMT DTO producer",
        not missing,
        f"consumed={len(consumed)}, produced={len(produced)}, unexplained={missing or 'none'}",
    )


def check_add_context_idempotent():
    from quant.bars import Bar
    from quant.decision.context import DecisionContext
    from quant.decision.timesfm_engine import TimesFMEngine

    engine = TimesFMEngine(target_horizon=8)
    bar = Bar("2026-09-10T10:00:00", 100, 101, 99, 100.5, 1000, 100)
    ctx = DecisionContext(symbol="NIFTY", bar=bar, bar_index=7)
    engine.add_context(ctx)          # strategy consumer
    engine.add_context(ctx)          # advisor consumer, same bar
    depth = len(engine._price_buffers["NIFTY"])
    _add(
        "B. Information flow", "shared engine records a bar exactly once",
        depth == 1,
        f"buffer depth after 1 bar / 2 consumers = {depth}",
    )


# ---------------------------------------------------------------------------
# C. Decision behaviour (probes)
# ---------------------------------------------------------------------------

def _build_ctx(amt_dto: dict, symbol: str = "NIFTY", bar_index: int = 20):
    from types import SimpleNamespace
    from quant.decision.context_builder import DecisionContextBuilder

    bar = SimpleNamespace(
        close=100.0, open=99.5, high=101.0, low=99.0, volume=100,
        time="2026-09-10T10:00:00+05:30",
    )
    risk = SimpleNamespace(halted=False, consecutive_losses=0, equity=100_000.0,
                           risk_per_trade_pct=0.05)
    return DecisionContextBuilder().build(
        bar=bar, symbol=symbol, market="NSE", contract_expiry=None,
        tick_size=0.05, bar_index=bar_index, warm_bars=0,
        cooldown_remaining_sec=0.0, risk_state=risk, amt_dto=amt_dto,
    )


def check_dead_market_enum():
    from quant.contracts.enums import MarketState

    ctx = _build_ctx({"marketState": "DEAD"})
    _add(
        "C. Decision behaviour", "DEAD market maps to MarketState enum (VA-fade gate fires)",
        ctx.market_state is MarketState.DEAD,
        f"type={type(ctx.market_state).__name__}, value={ctx.market_state!r}",
    )


def check_data_quality_gate_reachable():
    from quant.decision.decision_service import DecisionService

    blocked = DecisionService().evaluate(_build_ctx({"dataQuality": "PRICE_DIRECTION_PROXY"}))
    allowed = DecisionService().evaluate(
        _build_ctx({"dataQuality": "TICK_EXACT", "marketState": "BALANCED"})
    )
    _add(
        "C. Decision behaviour", "inferred data quality blocks, exact quality does not",
        blocked.reason == "DATA_QUALITY_BLOCKED" and allowed.reason != "DATA_QUALITY_BLOCKED",
        f"inferred -> {blocked.reason}, exact -> {allowed.reason}",
    )


def check_scanner_absorption_direction():
    import numpy as np
    from quant.decision.timesfm_agents import TimesFMScanningAgent, TimesFMForecast

    def forecast():
        p50 = np.linspace(99.0, 103.0, 32, dtype=np.float32)
        return TimesFMForecast(
            horizon=32, p50_path=p50, p10_path=p50 - 1, p90_path=p50 + 1,
            q_spread=2.0, mean_forecast=float(p50[-1]), pct_change=0.02,
            forecast_steps=["LONG"] * 32, curr_price=100.0, lat_ms=1.0,
        )

    # SELL_ABSORBED (sellers absorbed) is bullish at VAL with positive CVD.
    ctx = _build_ctx({
        "marketState": "BALANCED", "valueAreaLow": 100.1, "valueAreaHigh": 106.0,
        "poc": 103.0, "cvdSlope": 2.0, "absorptionSide": "SELL_ABSORBED",
    })
    ctx = ctx.__class__(**{**ctx.__dict__, "warmup_complete": True, "session_open": True,
                           "session_phase": "PRIMARY"})
    res = TimesFMScanningAgent(target_horizon=32).evaluate(ctx, forecast())
    _add(
        "C. Decision behaviour", "scanner LONG keys on SELL_ABSORBED (canonical)",
        res.get("direction") == "LONG",
        f"setup={res.get('setup')}, direction={res.get('direction')}",
    )


def check_pyramid_close_routes_through_release_path():
    """No close may bypass PositionManager._execute_full_close.

    D-3 (2026-09-10 audit): runtime.force_close_position closed lingering
    pyramid add-ons with a direct ``pm._oms.close(...)`` loop, skipping the
    central exit_source stamp, the [POSITION CLOSED] log, the double-close
    guard and the id-validity check. The module documents
    _execute_full_close as the ONLY full-close release path.
    """
    src = _read("quant/runtime.py")
    # A direct OMS close outside position_manager is the bypass signature:
    # it skips the exit_source stamp, the [POSITION CLOSED] log, the
    # double-close guard and the id-validity check.
    direct = re.findall(r"\._oms\.close\(", src)
    _add(
        "A. Flow authority", "every full close routes through the single release path",
        not direct,
        f"direct _oms.close( ) call sites in runtime.py = {len(direct)} (must be 0)",
    )


def check_model_risk_failure_observable():
    """A raising TimesFMRiskAuthority must not silently disable all model exits.

    D-2 (2026-09-10 audit): the ~35-line model-exit block in
    ExitEngine.evaluate sits inside ``except Exception as exc: pass``. Any
    exception disables the dynamic VaR stop, the trajectory take-profit, the
    velocity-decay exit AND the quantile stop ratchet for that bar, with no
    log and an unused ``exc``.
    """
    src = _read("quant/execution/exits.py")
    # Locate the swallow that wraps the model-exit call.
    idx = src.find("self._timesfm_risk.evaluate_exit(")
    ok = False
    detail = "evaluate_exit call site not found"
    if idx > 0:
        tail = src[idx:idx + 2500]
        m = re.search(r"except Exception as exc:\s*\n\s*(#.*\n\s*)?pass", tail)
        if m:
            detail = "model-exit block swallowed with bare 'except Exception: pass'"
        else:
            # Acceptable: the handler logs (logger.*) or re-raises.
            if re.search(r"except Exception[^\n]*:\s*\n\s*(#.*\n\s*)*(logger\.|raise)", tail):
                ok = True
                detail = "model-risk failure is logged or re-raised"
            else:
                detail = "model-exit handler not recognised — inspect exits.py manually"
    _add(
        "A. Flow authority", "model-risk failure is observable, not swallowed",
        ok, detail,
    )


def check_engine_dedup_thread_safe():
    """Shared-engine per-bar dedup must survive concurrent consumers.

    D-10 (2026-09-10 audit): add_context() dedups with check-then-act and no
    lock. The advisor worker thread and the strategy engine thread share ONE
    TimesFMEngine in TIMESFM_END_TO_END, so both can pass the check and append
    -> the model window contains the bar twice (reproduced, twice).
    """
    import threading

    from quant.bars import Bar
    from quant.decision.context import DecisionContext
    from quant.decision.timesfm_engine import TimesFMEngine

    engine = TimesFMEngine(target_horizon=8)
    symbol = "NIFTY"
    bar = Bar("2026-09-10T10:00:00", 100, 101, 99, 100.5, 1000, 100)
    ctx = DecisionContext(symbol=symbol, bar=bar, bar_index=42)

    # Adversarial scheduler: both consumers clear the dedup check together.
    class _Rendezvous(dict):
        def __init__(self):
            super().__init__()
            self._barrier = threading.Barrier(2, timeout=5)

        def get(self, key, default=None):
            value = super().get(key, default)
            try:
                self._barrier.wait()
            except threading.BrokenBarrierError:
                pass
            return value

    engine._last_context_bar = _Rendezvous()

    def consumer():
        try:
            engine.add_context(ctx)
        except Exception:
            pass

    ts = [threading.Thread(target=consumer) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=10)

    depth = len(engine._price_buffers[symbol])
    _add(
        "B. Information flow", "shared engine dedup survives concurrent consumers",
        depth == 1,
        f"buffer depth after one bar / two concurrent consumers = {depth}",
    )


def check_no_va_fabrication_on_empty_profile():
    """An absent volume profile must not fabricate a tradeable setup.

    D-4 (2026-09-10 audit): with poc/vah/val all zero the scanner fell back to
    curr_price for vah and val, so the VA-fade conditions became trivially true
    and it emitted ENTER_LONG (reproduced end-to-end: approved, entry=100.0
    sl=99.45 tp=101.5). The deterministic path correctly returns NO_EDGE on the
    same context. A profile-less bar must never produce a directional action.
    """
    import numpy as np

    from quant.bars import Bar
    from quant.decision.context import DecisionContext
    from quant.decision.timesfm_agents import TimesFMForecast, TimesFMScanningAgent

    bar = Bar("2026-09-10T10:00:00", 100.0, 101.0, 99.0, 100.0, 100, 100)
    ctx = DecisionContext(
        symbol="NIFTY", bar=bar, bar_index=20, session_open=True,
        warmup_complete=True, session_phase="PRIMARY",
        poc=0.0, vah=0.0, val=0.0, cvd_slope=1.0, allow_reversion=True,
    )
    # Bullish model projection: the strongest case for a fabricated fade.
    p50 = np.linspace(100.0, 101.5, 32, dtype=np.float32)
    fc = TimesFMForecast(
        horizon=32, p50_path=p50, p10_path=p50 - 0.5, p90_path=p50 + 0.5,
        q_spread=1.0, mean_forecast=float(p50[-1]), pct_change=0.015,
        forecast_steps=["LONG"] * 32, curr_price=100.0, lat_ms=1.0,
    )
    res = TimesFMScanningAgent(target_horizon=32).evaluate(ctx, fc)
    action = res.get("action", "FLAT")
    _add(
        "C. Decision behaviour", "empty volume profile cannot fabricate an entry",
        action == "FLAT",
        f"action={action}, setup={res.get('setup')} (must be FLAT when vah/val are 0)",
    )


# ---------------------------------------------------------------------------
# D. Test suites
# ---------------------------------------------------------------------------

SUITES = [
    "tests/quant/decision/",
    "tests/quant/strategies/",
    "tests/quant/execution/test_exit_source.py",
    "tests/quant/execution/test_position_management_flow.py",
    "tests/quant/runtime/test_runtime.py",
]


def check_suites():
    cmd = [sys.executable, "-m", "pytest", *SUITES, "-q", "--no-header"]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    tail = (proc.stdout or "").strip().splitlines()
    summary = tail[-1] if tail else (proc.stderr or "")[-200:]
    _add(
        "D. Test suites", "decision + strategy + exit + runtime suites",
        proc.returncode == 0,
        summary,
        suites=SUITES,
    )


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write machine-readable results here")
    ap.add_argument("--skip-suites", action="store_true")
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT))

    for fn in (
        check_entry_authority,
        check_no_bare_absorption,
        check_exit_source_stamp,
        check_single_sizing_authority,
        check_dto_key_coverage,
        check_add_context_idempotent,
        check_dead_market_enum,
        check_data_quality_gate_reachable,
        check_scanner_absorption_direction,
        # 2026-09-10 audit additions — the blocking defects D-2, D-3, D-4, D-10.
        check_pyramid_close_routes_through_release_path,
        check_model_risk_failure_observable,
        check_engine_dedup_thread_safe,
        check_no_va_fabrication_on_empty_profile,
    ):
        try:
            fn()
        except Exception as exc:  # a probe that cannot run is a failure, not a crash
            _add("C. Decision behaviour", fn.__name__, False, f"probe raised: {exc!r}")

    if not args.skip_suites:
        try:
            check_suites()
        except Exception as exc:
            _add("D. Test suites", "suites", False, f"runner raised: {exc!r}")

    width = max(len(r.name) for r in RESULTS) + 2
    section = None
    for r in RESULTS:
        if r.section != section:
            section = r.section
            print(f"\n{section}")
        tag = "PASS" if r.ok else ("WARN" if r.warn else "FAIL")
        print(f"  [{tag}] {r.name:<{width}} {r.detail}")

    fails = [r for r in RESULTS if not r.ok and not r.warn]
    warns = [r for r in RESULTS if r.warn]
    print(f"\n{len(RESULTS) - len(fails) - len(warns)} passed, {len(warns)} warned, {len(fails)} failed")

    if args.json:
        Path(args.json).write_text(json.dumps(
            [r.__dict__ for r in RESULTS], indent=2), encoding="utf-8")
        print(f"wrote {args.json}")

    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
