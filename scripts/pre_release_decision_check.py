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


def check_model_entry_authority():
    """E2E mode: the TimesFM model is the central intelligence. Its entry
    decision is followed through — the canonical AMT GatePipeline must not be
    able to override it. The strategy calls the scanner directly and never
    constructs a GatePipeline for approval.
    """
    src = _read("quant/strategies/timesfm_strategy.py")
    calls_scanner_directly = "self.scanning_agent.evaluate(ctx, forecast)" in src
    overrides_with_pipeline = "GatePipeline" in src or "canonical = " in src
    _add(
        "A. Flow authority", "model entry decision is authoritative (no canonical override)",
        calls_scanner_directly and not overrides_with_pipeline,
        f"strategy calls scanner directly={calls_scanner_directly}, "
        f"canonical override present={overrides_with_pipeline}",
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


def check_forecast_cache_safety():
    src = _read("quant/strategies/timesfm_strategy.py")
    none_check = src.find("if forecast is None:")
    cache_write = src.find("self._latest_forecasts[str(ctx.symbol)] = forecast")
    fresh_stamp = src.find("forecast.asof_bar = int(")
    ok = 0 <= none_check < cache_write and fresh_stamp > 0
    _add(
        "A. Flow authority", "forecast cached only after success + freshness stamped",
        ok,
        f"None-check@{none_check}, cache-write@{cache_write}, asof-stamp@{fresh_stamp}",
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


def check_shared_engine_end_to_end():
    """Advisor analyze() + strategy should_enter() must not double-feed the model."""
    from unittest.mock import Mock

    import numpy as np
    from quant.bars import Bar
    from quant.decision.context import DecisionContext
    from quant.decision.timesfm_engine import TimesFMEngine
    from quant.strategies.timesfm_strategy import TimesFMTradingStrategy

    engine = TimesFMEngine(target_horizon=8)
    strategy = TimesFMTradingStrategy(target_horizon=8, engine=engine)
    bar = Bar("2026-09-10T10:00:00", 100, 101, 99, 100.5, 1000, 100)
    ctx = DecisionContext(symbol="NIFTY", bar=bar, bar_index=42, session_open=True,
                          warmup_complete=True, session_phase="PRIMARY")
    fake = Mock()
    fake.predict.return_value = Mock(quantiles=np.tile(np.linspace(99, 102, 9), (8, 1)))
    import quant.decision.timesfm_engine as eng_mod
    original = eng_mod.get_timesfm_model
    eng_mod.get_timesfm_model = lambda *a, **k: fake
    try:
        engine.analyze(ctx)
        strategy.should_enter(ctx)
    finally:
        eng_mod.get_timesfm_model = original
    depth = len(engine._price_buffers["NIFTY"])
    _add(
        "C. Decision behaviour", "advisor + strategy share one bar of context",
        depth == 1,
        f"buffer depth after both consumers = {depth}",
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
        check_model_entry_authority,
        check_no_bare_absorption,
        check_forecast_cache_safety,
        check_exit_source_stamp,
        check_single_sizing_authority,
        check_dto_key_coverage,
        check_add_context_idempotent,
        check_dead_market_enum,
        check_data_quality_gate_reachable,
        check_scanner_absorption_direction,
        check_shared_engine_end_to_end,
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
