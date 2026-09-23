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
    # The entry seam moved to DecisionLoop.evaluate() -> strategy.should_enter().
    # runtime.py must not call DecisionService.evaluate() directly (the strategy is
    # the only caller), and exactly one strategy implements should_enter.
    loop = _read("quant/engine/decision_loop.py")
    rt = _read("quant/runtime.py")
    calls_should_enter = loop.count("self._strategy.should_enter(")
    direct_service = re.findall(r"self\._decision_service\.evaluate\(", rt + loop)
    strategies = [
        p for p in QUANT.rglob("*.py")
        if "def should_enter(" in p.read_text(encoding="utf-8")
        and "quant/strategy.py" not in _rel(p) and "quant/strategies/" in _rel(p)
    ]
    _add(
        "A. Flow authority", "single entry seam (strategy.should_enter)",
        calls_should_enter >= 1 and not direct_service and len(strategies) == 1,
        f"should_enter call sites={calls_should_enter}, "
        f"direct DecisionService.evaluate={len(direct_service)}, "
        f"entry strategies={[_rel(p) for p in strategies]}",
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
    # Sizing is owned by SessionRisk; it is invoked at submission time
    # (engine/submission_handler.py), not in runtime.py directly.
    sh = _read("quant/engine/submission_handler.py")
    dead = list(QUANT.rglob("risk_sizer.py")) + list(QUANT.rglob("decision/intent.py"))
    uses_authority = "self._risk.position_size(" in sh
    clamps = "clamp_quantity(" in sh
    ok = uses_authority and clamps and not dead
    _add(
        "A. Flow authority", "one sizing authority (SessionRisk.position_size + clamp_quantity)",
        ok,
        f"submission uses SessionRisk={uses_authority}, "
        f"clamp_quantity={clamps}, dead scaffolding={[ _rel(p) for p in dead ] or 'none'}",
    )


# ---------------------------------------------------------------------------
# B. Information flow (contract coverage + shared-buffer integrity)
# ---------------------------------------------------------------------------

def check_dto_key_coverage():
    """Every key context_builder reads must be one the DTO producer emits.

    No fallback allowlist: the reads that used to need one (``acceptance``,
    ``rejection``, ``legLvn``, ``data_quality``, ``optionGreekDelta``) are gone.
    tests/architecture/test_amt_dto_contract.py enforces the same contract for
    every consumer — including attribute and typed-getter reads — at CI time.
    """
    cb = _read("quant/decision/context_builder.py")
    consumed = set(re.findall(r'amt_dto\.get\(\s*"([^"]+)"', cb))
    consumed |= set(re.findall(r'amt_dto\[\s*"([^"]+)"\s*\]', cb))
    dto = _read("quant/amt/dto.py")
    produced = set(re.findall(r'^\s*"([A-Za-z_][A-Za-z0-9_]*)":', dto, re.M))
    missing = sorted(consumed - produced)
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
    """DecisionLoop is the sole data-quality authority (v7 prune N3).

    DecisionService intentionally no longer pre-gates quality (gates 1-4 are
    quality-agnostic). Live OMS requires TICK_EXACT or PRICE_DIRECTION_PROXY;
    other grades are blocked with PROXY_FLOW_BLOCKED before OMS submission.
    """
    import dataclasses  # noqa: F401

    from quant.bars import Bar
    from quant.decision.context import DecisionContext
    from quant.decision.data_quality import DataQuality
    from quant.decision.decision_service import QuantDecision
    from quant.engine.decision_loop import DecisionLoop

    class _LiveOMS:
        is_live = True
        lot_size = 1

        def submit(self, signal, quantity):
            raise AssertionError("must not submit when quality blocked")

    class _Risk:
        class _State:
            trades_today = 0
            halted = False
            consecutive_losses = 0
            consecutive_wins = 0
            equity = 100000.0
            risk_per_trade_pct = 0.01

        def can_trade(self):
            return True, ""

        def state(self):
            return self._State()

        def position_size(self, *a, **k):
            return 1

    bar = Bar(time="2026-01-15T10:00:00+05:30", open=100, high=105, low=95, close=102, volume=1000)

    def _ctx(quality):
        return DecisionContext(
            bar=bar, symbol="SYM", data_quality=quality, agent_probability=0.7,
        )

    def _loop():
        from quant.decision.signal_builder import Signal

        decision = QuantDecision(
            True, Signal("LONG", "Triple-A", 100, 98, 106, 3, "Triple-A", "SYM", "t"),
            "Triple-A", "", (), model_label="Triple-A",
        )
        strategy = type("S", (), {"should_enter": lambda self, ctx: decision})()
        return DecisionLoop(
            config={"symbol": "SYM", "market": "NSE", "cooldown_bars": 0, "live_mode": True},
            deps={"risk": _Risk(), "oms": _LiveOMS(), "strategy": strategy,
                  "amt_engine": type("A", (), {"warm_bars": 20, "interval_seconds": 300, "last_amt_dto": {}})(),
                  "get_position_manager": lambda: None, "execution_enabled": True},
            state={"get_bar_index": lambda: 10, "get_entry_bar_index": lambda: 0,
                   "set_entry_bar_index": lambda v: None, "get_last_close_bar_index": lambda: -1,
                   "get_latch": lambda: {}, "set_latch": lambda k, v: None,
                   "clear_latch": lambda: None, "get_cert_records": lambda: [],
                   "get_last_depth": lambda: None, "get_recent_decisions": lambda: [],
                   "get_exposure_state": lambda: None},
            emit=lambda e: None,
        )

    loop = _loop()
    loop._build_context = lambda bar, amt_dto, cooldown: _ctx(DataQuality.CANDLE_DISTRIBUTED)
    dec_candle = loop.evaluate({}, bar)
    loop._build_context = lambda bar, amt_dto, cooldown: _ctx(DataQuality.TICK_EXACT)
    dec_exact = loop.evaluate({}, bar)

    blocked_ok = (
        dec_candle.approved is False and dec_candle.reason == "PROXY_FLOW_BLOCKED"
    )
    allowed_ok = dec_exact.reason != "PROXY_FLOW_BLOCKED"
    _add(
        "C. Decision behaviour", "inferred data quality blocks, exact quality does not",
        blocked_ok and allowed_ok,
        f"inferred -> {dec_candle.reason}, exact -> {dec_exact.reason}",
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
    # TimesFM risk authority was removed (prune Task 2): exits are deterministic.
    # Accept either (a) the old call site with an observable handler, or
    # (b) no evaluate_exit call site at all (authority gone — nothing to swallow),
    # as long as there is no bare swallow wrapping a model-exit block.
    idx = src.find("self._timesfm_risk.evaluate_exit(")
    if idx < 0 and "evaluate_exit(" not in src.replace("def evaluate(", ""):
        # No model-exit authority call remains — D-2 swallow is gone with it.
        # Still fail if a bare except-pass sits near model/timesfm exit code.
        model_block = re.search(
            r"(timesfm|model_risk|MODEL_RISK).*?except Exception as exc:\s*\n\s*(#.*\n\s*)?pass",
            src,
            re.S | re.I,
        )
        ok = model_block is None
        detail = (
            "model-exit authority removed; no bare model-risk swallow"
            if ok else "bare except Exception: pass still wraps model-risk block"
        )
    else:
        ok = False
        detail = "evaluate_exit call site not found"
        if idx > 0:
            tail = src[idx:idx + 2500]
            m = re.search(r"except Exception as exc:\s*\n\s*(#.*\n\s*)?pass", tail)
            if m:
                detail = "model-exit block swallowed with bare 'except Exception: pass'"
            elif re.search(r"except Exception[^\n]*:\s*\n\s*(#.*\n\s*)*(logger\.|raise)", tail):
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
    lock. The advisor worker thread and the forecast consumer share ONE
    TimesFMEngine, so both can pass the check and append
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
