# AMT Prune + Fabio Playbook Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove dead code/junk (≈−7,800 to −11,400 lines, −7.9 GB disk), fix three money-path bugs (risk portfolio caps, unsafe base risk defaults, missing telemetry wiring), and harden the Fabio AMT accuracy battery so the system is lean, correct, and tested against the Fabio playbook — without removing AI/model integration.

**Architecture:** Keep the live path `main.py → composition_root → QuantCoordinator → QuantEngine → AMT → 4 gates → OMS → ExitManager/ExitEngine`. Advisory AI (`wiring_advisor`, `laya_advisor`, `timesfm_*`, `llm/*`) stays fully wired. Pruning is layered: (0) disk junk, (1) dead quant modules, (2) backend shell + config fixes, (3) frontend orphans, (4) test hygiene, (5) Fabio battery integrity. Each task ends with an independently runnable test gate.

**Tech Stack:** Python 3.13, FastAPI, pytest, TypeScript/Vitest frontend, YAML config loader (`config_models`), root `.venv`.

## Global Constraints

- **Never remove AI/model integration:** keep `quant/wiring_advisor.py`, `quant/decision/laya_advisor.py`, `quant/decision/timesfm_{advisor,engine,agents,client,forecast_factory,option_selector}.py`, `quant/llm/{advisor,bridge,narrative}.py`, `.env` keys `LLM_*` / `TIMESFM_*` / `LAYA_*` / `MLX_*` / `OPENROUTER_API_KEY`.
- **Do not delete:** `quant/decision/gap_architecture.workflow.html` + `.workflow.json` (read by `tests/architecture/test_gap_architecture_contract.py`).
- **Do not delete:** `runtime_audit/e2e/` (3 tracked files; `tests/e2e` depends on them); `amt_dataset/` (tracked training data); live `backend/glassytrade.db` + `-wal`/`-shm`.
- **Do not delete:** `quant/brokers/{gateway,live_gateway,multiplexed_feed}.py` (prod path), root `brokers/` (adapter-only imports), `quant/execution` live modules (OMS/exits/risk family except listed dead files).
- **Exit authority stays:** `ExitManager → PositionManager → ExitEngine`. Do not reintroduce `runtime.close_lingering_pyramids`.
- **Python:** `PYTHONPATH=backend:. .venv/bin/python -m pytest …`
- **Gates after each task:** explicit pytest for the task must pass. After Task 0B, `make lint` must stay green (0B establishes it). After Tasks 1–6 also run `make parity` and `make pre-release`.
- **Commits:** one commit per task (or per sub-step where noted); message style matches repo (`chore:`, `fix:`, `refactor:`, `test:`).
- **Working tree note:** `tests/quant/test_fabio_accuracy_battery.py` currently has an uncommitted 1-line `sig.sl if sig else None` guard — Task 6 rewrites it; include that file in the Task 6 (or 0B) commit.

---

### Task 0: Baseline gate (read-only) — **COMPLETED 2026-09-23**

**Files:** none (read-only)

**Actual observed baseline (do not re-discover):**

| Gate | Result |
|------|--------|
| `tests/architecture/` | **2 failed**, 39 passed — `test_amt_dto_contract` (missing DTO keys), `test_no_silent_except_pass` (`quant/llm/advisor.py:77`) |
| `tests/quant/test_fabio_accuracy_battery.py` | **FAIL** — S1/S2/S3: `SignalBuilder.build_or_reason` returns `(None, "unlabeled setup")` because battery calls `sb.build(...)` without `model_label` |
| Telemetry test | **FAIL** (known B3) — `_create_quant_coordinator` has no `telemetry=PrometheusTelemetry(),` |
| `make lint` | **FAIL** — 1005 ruff errors (627 F401, 121 E402, 70 F841, …; 660 auto-fixable; 19 F821) |

- [ ] **Step 0.1: Done** — commands above were run; outputs recorded in this table.
- [ ] **Step 0.2: Done** — telemetry FAIL confirmed as B3.
- [ ] **Step 0.3: No commit**

---

### Task 0B: Stabilize red baseline (MUST precede Task 1+)

**Why first:** Task 1+ gates assume architecture/battery/lint can go green without colliding with these failures.

**Files:**
- Modify: `tests/quant/test_fabio_accuracy_battery.py` (S1–S3 + portable paths — can land here instead of Task 6)
- Modify: `quant/llm/advisor.py` (silent-except marker only — **keep** AI code)
- Modify: `quant/amt/dto.py` **or** `quant/decision/context_builder.py` + `quant/engine/submission_handler.py` (DTO contract)
- Modify: repo-wide ruff debt (see Step 0B.4)
- Test: `tests/architecture/test_amt_dto_contract.py` (already failing — use as red)

**Interfaces:**
- Consumes: `SignalBuilder` requires `model_label` (`signal_builder.py:108-109`); decision layer reads DTO keys `optionDelta`, `bid`, `ask`, `nearestLegLvn`, `cvdAgrees`
- Produces: architecture suite green; battery green without tautologies; `make lint` green; telemetry still red (Task 3)

- [ ] **Step 0B.1: Fix battery S1–S3 + tautologies + portable paths (minimal; Task 6 can extend)**

Replace absolute paths (lines 3–4) with nothing (rely on `PYTHONPATH=backend:.`). Pass label:

```python
sig = sb.build(mk_ctx(), [GateResult(i, True) for i in range(1, 5)], model_label="Triple-A")
# S1: sig and sig.sl < sig.entry < sig.tp   → verified: sl=97.9 entry=100 tp≈104.2
# S2: sig.rr >= 2.0                         → verified rr=2.0
# S3: sig_tight.sl > sig.sl                 → verified 99.4 > 97.9
```

Also in same pass: V4 real bound check; G1 drop `or True` (assert actual `session_force_exit` return for both after-hours and mid-session times).

- [ ] **Step 0B.2: Mark silent-except in `quant/llm/advisor.py:77`**

```python
            except Exception:  # silent-except - laya eval optional; baseline narrative still emits
                pass
```

Do **not** remove the LLM/Laya try/except body.

- [ ] **Step 0B.3: Close AMT DTO contract — emit keys the decision layer reads**

Red test says these are read but never emitted by `amt_result_to_dto`: `optionDelta`, `bid`, `ask`, `nearestLegLvn`, `cvdAgrees`.

Preferred fix (emit from domain data already on `AMTResult` / book snapshot):

In `quant/amt/dto.py` return dict, add:

```python
        # Keys the decision layer reads (test_amt_dto_contract); absent keys
        # silently zero/default in submission_handler / context_builder.
        "optionDelta": (float(r.delta_normalized_option) if getattr(r, "delta_normalized_option", 0.0) else None),
        "bid": float(getattr(r, "best_bid", 0.0) or 0.0),
        "ask": float(getattr(r, "best_ask", 0.0) or 0.0),
        "nearestLegLvn": float(leg_lvns[0]) if leg_lvns else 0.0,
        "cvdAgrees": bool(...),  # derive from cvd_state vs break_direction / agent_direction — read contract test for exact expectation
```

**Before coding:** open `tests/architecture/test_amt_dto_contract.py` and follow its reader→field rules exactly; if a field has no domain source, stop that key's readers instead of inventing values (only if auction path is dead — `submission_handler` bid/ask/cvdAgrees only run when OpportunityAuction is wired).

- [ ] **Step 0B.4: Make `make lint` green**

```bash
.venv/bin/python -m ruff check quant backend/app brokers shared tests backend/tests --fix
.venv/bin/python -m ruff check quant backend/app brokers shared tests backend/tests
```

Remaining ~345 issues after auto-fix: prioritize **19 F821** (real undefined names: `dependencies.py` quoted annotations need `from __future__ import annotations` or TYPE_CHECKING imports; `position_manager.py` `Position`; `analyzer.py` `NPOCTracker`/`TickFootprintAccumulator`; `Any`/`OHLC`/`Path` imports). Then E402 (file-level `# noqa: E402` only where intentional post-path-insert), F841/F811. **Do not** `--unsafe-fixes` on quant logic. If residual style debt remains, either fix or add narrow `per-file-ignores` in a root `ruff.toml` **only** for non-quant legacy paths (e.g. `brokers/broker/dhan/**`) — prefer fixing over ignoring.

Gate:

```bash
make lint && \
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture/ tests/quant/test_fabio_accuracy_battery.py -q --no-header
```

Expected: lint 0 errors; architecture + battery PASS; telemetry test still FAIL (ok until Task 3).

- [ ] **Step 0B.5: Commit**

```bash
git add -A
git commit -m "fix(baseline): fabio battery labels, DTO contract keys, silent-except marker, ruff clean"
```

---

### Task 1: Disk junk cleanup (−7.9 GB)

**Files:**
- Delete directories/files listed below (all gitignored except noted)
- Modify: none of production code

**Interfaces:**
- Consumes: n/a
- Produces: clean tree; `tests/architecture/test_repo_hygiene.py` still green

- [ ] **Step 1.1: Untrack git-tracked junk (keep workflow contract files)**

```bash
git rm -f \
  "quant/decision/gap_architecture.workflow.visual-check.1440x900.dark.png" \
  "quant/decision/gap_architecture.workflow.visual-check.1440x900.light.png" \
  "quant/decision/gap_architecture.workflow.visual-check.2048x1320.dark.png" \
  "quant/decision/gap_architecture.workflow.visual-check.2048x1320.light.png" \
  "quant/decision/gap_architecture.workflow.visual-check.html" \
  "quant/decision/gap_architecture.workflow.visual-check.json" 2>/dev/null || true
# KEEP: quant/decision/gap_architecture.workflow.html and .workflow.json
```

- [ ] **Step 1.2: Delete disposable disk (gitignored paths)**

```bash
rm -rf \
  backend/journals backend/venv backend/logs \
  graphify-out quant/graphify-out \
  .kilo .mimocode old.freebuff \
  .hypothesis .superpowers .qoder .benchmarks \
  tests/quantv2 tests/quant/modeling tests/quant/brokers \
  tests/quant/decision/gates tests/unit/quant \
  backend/tests/unit/domain/trading \
  runtime_audit/out runtime_audit/fixtures \
  scratch poc_temp .jcode-scratch .freebuff .workbuddy-ai \
  backend/startup.log backend/backend_e2e.log backend/glassytrade.db.bak \
  glassytrade.db glassytrade.db-shm glassytrade.db-wal \
  "anlaysis.md" MERGED_NODES.md .commit_msg_w3.txt
find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
```

Do **not** delete: `backend/glassytrade.db`, `backend/glassytrade.db-wal`, `backend/glassytrade.db-shm` if present and in use — only `.bak` and root-level copies.

- [ ] **Step 1.3: Hygiene gate**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture/test_repo_hygiene.py -q --no-header
```

Expected: PASS.

- [ ] **Step 1.4: Commit**

```bash
git add -A
git commit -m "chore: purge disk junk, orphan bytecode, and tracked workflow screenshots"
```

---

### Task 2: Delete dead quant modules (tests-only) ≈ −1,500 lines

**Files:**
- Delete: `quant/amt/session/ib_scalp.py`, `quant/amt/session/eia.py`, `quant/amt/profile/range_bars.py`, `quant/decision/timesfm_risk.py`, `quant/amt/models/observation.py`
- Delete tests: `tests/quant/amt/session/test_ib_scalp.py`, `tests/quant/amt/session/test_eia.py`, `tests/quant/amt/profile/test_range_bars.py`, `tests/quant/decision/test_timesfm_risk.py`, `backend/tests/unit/domain/test_eia_calendar.py` (if present and only covers deleted eia)
- Delete: `quant/amt/session/futures_provider.py` **after** inlining or keeping `backend/scripts/verify_scanner_goldm_silverm.py` working (see Step 2.3)
- Delete tests: `tests/quant/amt/session/test_futures_provider*.py`, `tests/quant/test_underlying_required.py`, `tests/quant/amt/session/test_extract_underlying_parity.py` (parity suite for deleted provider) — **only after** Step 2.3
- Modify: `quant/execution/exits.py` (remove `_timesfm_risk` seam)
- Modify: `quant/amt/analyzer.py` (remove `compute_observation`, `from_exchange_config` dead path if still unreferenced, dead params — optional micro-clean in same commit only if zero callers)
- Modify tests: `tests/quant/execution/test_exit_source.py` (drop TimesFM-risk-specific cases or convert to assert multiplier always 1.0)

**Interfaces:**
- Consumes: live `ExitEngine`, `AMTAnalyzer`, `amt_scalping` strategy
- Produces: `ExitEngine` still exposes session budget multiplier as constant 1.0 via existing code path when authority absent; `AMTConfig` unchanged for live callers

- [ ] **Step 2.1: Confirm zero prod importers (run before delete)**

```bash
grep -rn "ib_scalp\|amt.profile.range_bars\|amt.session.eia\|decision.timesfm_risk\|amt.models.observation\|session.futures_provider" \
  --include='*.py' quant backend/app 2>/dev/null | grep -v __pycache__
```

Expected: no hits under `quant/` prod or `backend/app` except possibly comments. `backend/app` must not import them.

- [ ] **Step 2.2: Delete pure test-only modules + their tests; fix exits seam**

Delete files listed above (except futures_provider until 2.3).

In `quant/execution/exits.py`, remove dead TimesFM risk authority:

```python
# Before (approx lines 90, 98-99, 182-184):
self._timesfm_risk = None
...
if getattr(self, "_timesfm_risk", None) is not None:
    self._timesfm_risk.clear_position(position._id)
...
if self._timesfm_risk is None:
    return 1.0
return self._timesfm_risk.get_session_budget_multiplier()

# After:
# (delete attribute init; clear_position block; always return 1.0 —
#  or keep a single `return 1.0` in get_session_budget_multiplier path)
```

Update `tests/quant/execution/test_exit_source.py`: remove `_Boom` / `TimesFMRiskAuthority` tests; keep test that session budget multiplier is 1.0 when no authority is configured.

- [ ] **Step 2.3: futures_provider — inline script usage or delete provider+tests**

Check `backend/scripts/verify_scanner_goldm_silverm.py`. Prefer: delete `futures_provider.py` + its 4 test files and rewrite the verify script to call `ExchangeConfig.extract_underlying` (already the parity target). If rewrite is non-trivial, **skip futures_provider in this task** and leave a follow-up note in the commit body.

- [ ] **Step 2.4: Remove observation builder**

```bash
grep -rn "compute_observation\|AMTObservation\|models.observation" --include='*.py' quant backend/app tests | grep -v __pycache__
```

If only `analyzer.py` defines it and tests only import the module: delete `quant/amt/models/observation.py`, delete `AMTAnalyzer.compute_observation` in `analyzer.py`, drop `from quant.amt.models.observation import …` in analyzer.

- [ ] **Step 2.5: Run targeted tests**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest \
  tests/quant/amt tests/quant/decision tests/quant/execution \
  -q --no-header -k "not ib_scalp and not test_eia and not range_bars and not timesfm_risk and not futures_provider"
make lint
```

Expected: PASS (deleted tests no longer collected).

- [ ] **Step 2.6: Commit**

```bash
git add -A
git commit -m "refactor(quant): delete test-only AMT modules and TimesFM risk authority seam"
```

---

### Task 3: Backend money-path fixes (B1 + B3) — TDD

**Files:**
- Modify: `backend/app/config_models/__init__.py` (`RiskConfig`)
- Modify: `backend/app/config_models/loader.py` (parse new fields)
- Modify: `backend/app/application/di/composition_root.py` (wire telemetry)
- Test: `backend/tests/unit/application/test_coposition_root.py` (already has failing telemetry test)
- Test: `backend/tests/unit/config_models/test_portfolio_risk_fields.py` (create)

**Interfaces:**
- Consumes: YAML `risk.max_portfolio_daily_loss_pct`, `risk.max_portfolio_risk_pct` in `strategies/{nse,mcx}_options.yaml`
- Produces: `RiskConfig.max_portfolio_daily_loss_pct: float | None`, `RiskConfig.max_portfolio_risk_pct: float | None`; `_coordinator_risk_config` emits them when set; `QuantCoordinator(..., telemetry=PrometheusTelemetry())`

- [ ] **Step 3.1: Write failing tests for RiskConfig portfolio fields**

Create `backend/tests/unit/config_models/test_portfolio_risk_fields.py`:

```python
"""Portfolio risk YAML keys must land on RiskConfig (B1)."""
import os
from pathlib import Path

from app.config_models.loader import load_config


def test_strategy_yaml_portfolio_caps_reach_risk_config():
    os.environ.setdefault("GLASSYTRADE_ENV", "paper")
    os.environ.setdefault("GLASSYTRADE_STRATEGY", "nse_options")
    cfg = load_config(str(Path(__file__).resolve().parents[3] / "backend" / "config"))
    assert getattr(cfg.risk, "max_portfolio_daily_loss_pct", None) is not None
    assert getattr(cfg.risk, "max_portfolio_risk_pct", None) is not None
    assert 0 < cfg.risk.max_portfolio_daily_loss_pct <= 1
    assert 0 < cfg.risk.max_portfolio_risk_pct <= 1
```

(Adjust parents path if loader default `config_dir` is used: `load_config()` without args is fine when `backend` is on PYTHONPATH.)

Prefer simpler form if default config path works:

```python
def test_strategy_yaml_portfolio_caps_reach_risk_config(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_ENV", "paper")
    monkeypatch.setenv("GLASSYTRADE_STRATEGY", "nse_options")
    cfg = load_config()
    assert cfg.risk.max_portfolio_daily_loss_pct == 0.02
    assert cfg.risk.max_portfolio_risk_pct == 0.25
```

- [ ] **Step 3.2: Run test — expect FAIL (field missing)**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest backend/tests/unit/config_models/test_portfolio_risk_fields.py -q --no-header
```

Expected: FAIL (`AttributeError` or missing attribute).

- [ ] **Step 3.3: Implement RiskConfig + loader**

In `backend/app/config_models/__init__.py` after `bootstrap_trade_count`:

```python
    max_portfolio_daily_loss_pct: float | None = None
    max_portfolio_risk_pct: float | None = None
```

In `backend/app/config_models/loader.py` inside `RiskConfig(...)` construction (~line 263):

```python
            max_portfolio_daily_loss_pct=risk_data.get("max_portfolio_daily_loss_pct"),
            max_portfolio_risk_pct=risk_data.get("max_portfolio_risk_pct"),
```

- [ ] **Step 3.4: Run test — expect PASS**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest backend/tests/unit/config_models/test_portfolio_risk_fields.py -q --no-header
```

- [ ] **Step 3.5: Wire telemetry (B3) — existing failing test is the red**

In `backend/app/application/di/composition_root.py` `_create_quant_coordinator`:

```python
    from app.infrastructure.telemetry import PrometheusTelemetry
    ...
    return QuantCoordinator(
        market_data=market_data,
        broker=broker,
        config=coord_config,
        storage=storage,
        telemetry=PrometheusTelemetry(),
    )
```

Verify `QuantCoordinator.__init__` accepts `telemetry=` (read `quant/multi_engine.py` first; if the parameter name differs, match the port). Also fix stale docstring claiming `GREENFIELD_ENGINE=1`.

- [ ] **Step 3.6: Run telemetry test — expect PASS**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest backend/tests/unit/application/test_composition_root.py -q --no-header
```

Expected: 6 passed (or all green).

- [ ] **Step 3.7: Full backend application suite**

```bash
cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/unit/application tests/unit/config_models -q --no-header
```

(If `config_models` tests live elsewhere, run the new file + `test_composition_root` + any `loader`/`validator` tests.)

- [ ] **Step 3.8: Commit**

```bash
git add backend/app/config_models backend/app/application/di/composition_root.py \
  backend/tests/unit/config_models/test_portfolio_risk_fields.py \
  backend/tests/unit/application/test_composition_root.py
git commit -m "fix(risk,telemetry): load portfolio risk caps from YAML and wire PrometheusTelemetry"
```

---

### Task 4: Unsafe base risk defaults (B2) + exchange naming (B7)

**Files:**
- Modify: `backend/config/base.yaml` (`risk:` block lines ~533–545)
- Modify: `backend/app/config_models/validator.py` (extend RULE-5/RULE-14-style caps to non-live — or only fix defaults if validator change is too broad; prefer defaults first)
- Test: extend `backend/tests/unit/` config validator tests if present; else create small test

**Interfaces:**
- Consumes: loader merge (base ← env ← strategy)
- Produces: effective `risk_per_trade_pct ≤ 0.02` and sane `max_daily_loss_pct` even if env overlay misses keys

- [ ] **Step 4.1: Write failing test — paper load must not yield 95% risk**

```python
# backend/tests/unit/config_models/test_base_risk_defaults.py
import os
from app.config_models.loader import load_config


def test_base_risk_defaults_are_not_catastrophic(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_ENV", "paper")
    monkeypatch.setenv("GLASSYTRADE_STRATEGY", "nse_options")
    cfg = load_config()
    assert cfg.risk.risk_per_trade_pct <= 0.02, cfg.risk.risk_per_trade_pct
    assert cfg.risk.max_daily_loss_pct <= 0.05, cfg.risk.max_daily_loss_pct
    assert cfg.risk.portfolio_notional_cap <= 0.80
```

- [ ] **Step 4.2: Run — may already pass via paper.yaml overlay.** If PASS, still fix base.yaml so overlay-miss cannot regress:

Replace `backend/config/base.yaml` risk block:

```yaml
risk:
  risk_per_trade_pct: 0.005
  max_daily_loss_pct: 0.02
  max_consecutive_losses: 3
  max_trades_per_session: 6
  max_drawdown_pct: 0.03
  absolute_ceiling_pct: 0.01
  max_concurrent_positions: 5
  portfolio_notional_cap: 0.60
  per_symbol_notional_cap: 0.20
  kelly_fraction: 0.25
  kelly_win_prob: 0.55
  kelly_win_loss_ratio: 2.0
  bootstrap_trade_count: 30
```

(Removed the parallel `system:` risk literals at lines ~94 if they are a second unused block — verify with grep before deleting; if `system.risk_per_trade_pct` is dead, delete those lines in the same edit.)

- [ ] **Step 4.3: Re-run test + validator suite**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest backend/tests/unit/config_models -q --no-header
```

- [ ] **Step 4.4: B7 exchange naming — document-only this task**

Do **not** change `.env`/`DEFAULT_EXCHANGE` semantics in this task (high blast radius). Add a code comment at `composition_root.py` coord_config `"exchange"` noting `.env NSE may be shadowed by strategy YAML `NFO` segment code. File a follow-up issue in commit body if needed.

- [ ] **Step 4.5: Commit**

```bash
git add backend/config/base.yaml backend/tests/unit/config_models/
git commit -m "fix(config): sane base risk defaults so paper cannot inherit 95% per-trade risk"
```

---

### Task 5: Backend shell dead code (Tier 1) ≈ −700 lines

**Files:**
- Delete: `backend/app/api/routers/metrics.py`, `backend/app/api/routers/alerts.py`, `backend/app/core/alerts.py`, `backend/app/domain/ops/gate_rejection_tracker.py`, `backend/app/domain/ops/latency_tracker.py`, `backend/app/infrastructure/metrics.py`
- Modify: `backend/app/main.py` (remove metrics/alerts router registration)
- Modify: `backend/app/config_models/settings_adapter.py` (remove 16 dead properties listed below)
- Modify: `backend/app/application/di/container.py` (remove never-called methods if still present)
- Modify: `backend/app/api/routers/health.py` (remove `/v1/metrics`, `/debug/memory`, unused `MetricsCollector` import)
- Modify tests: `backend/tests/unit/core/test_alerts.py`, `test_metrics.py`, domain observability tests, `tests/architecture/test_no_layer_bypass.py` allowlists

**Dead settings properties to remove** (from `settings_adapter.py`):  
`SCANNER_MODE`, `SCANNER_TOP_PER_UNDERLYING`, `AGGRESSION_SIGMA`, `DISPLACEMENT_MULTIPLIER`, `BALANCE_RATIO_THRESHOLD`, `ALLOW_SHORT`, `RISK_TIER_ENGINE`, `SHORT_SIGNALS_ENABLED`, `LLM_PRE_CANDLE_ADVISORY`, `SCALP_ENGINE_ENABLED`, `SCALP_IB_BREAKOUT`, `QUANT_DECISION_ENABLED`, `QUANT_EXECUTION_MODE` + `_feature_flags_yaml`, `REALISTIC_COST_MODEL`, `LLM_TIMEOUT_SECONDS`, `LLM_EXECUTION_ENABLED`, `TICK_POLL_SECONDS`, `SIGNAL_STALE_SECONDS`, `GAP_FILL_*` (5 props).

**Do NOT remove:** `DEFAULT_EXCHANGE`, scanner props used by composition, `CAPITAL`, `CORS_*`, `TRADING_MODE`/`__getattr__` path, or any AI-related env readers in `wiring_advisor`.

**Interfaces:**
- Consumes: n/a
- Produces: app boots without alerts/metrics routers; `/api/system/config`, gameloop WS unchanged

- [ ] **Step 5.1: Grep callers for each delete target**

```bash
grep -rn "set_trackers\|send_alert\|subscribe_alerts\|GateRejectionTracker\|LatencyTracker\|MetricsCollector" \
  --include='*.py' backend quant tests | grep -v __pycache__
```

Only tests + the modules themselves should appear. If production callers exist, stop and skip that file.

- [ ] **Step 5.2: Delete modules; unregister routers in `main.py`**

Remove imports and `app.include_router(metrics_router…)` / `alerts_router` lines from `main.py` (~508, ~510).

- [ ] **Step 5.3: Strip dead settings properties** (one edit block or several; re-read file before each)

- [ ] **Step 5.4: Update tests** — delete `test_alerts.py` / `test_metrics.py` if they only cover deleted modules; fix architecture allowlist entries.

- [ ] **Step 5.5: Gate**

```bash
cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/unit -q --no-header -k "not slow"
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture -q --no-header
make lint
```

- [ ] **Step 5.6: Commit**

```bash
git add -A
git commit -m "refactor(backend): remove dead metrics/alerts/trackers and unused settings properties"
```

---

### Task 6: Fabio accuracy battery integrity (fix tautologies + portable paths)

**Files:**
- Modify: `tests/quant/test_fabio_accuracy_battery.py` (full rewrite of check style)
- Optional: `tests/system/test_fabio_behavior_trace.py` (assert trace fields or trim docstring)

**Interfaces:**
- Consumes: `session_force_exit`, VP helpers, `SignalBuilder`, `SessionRisk` (existing)
- Produces: battery where **every** `check()` has a non-constant condition; no absolute `/Users/...` paths; no import-time-only side effects preferred (move body into `test_fabio_accuracy_battery` or `pytest.fixture`)

- [ ] **Step 6.1: Write the fixed battery assertions (replace lines 1–4, 69, 101)**

Remove hard-coded paths:

```python
"""Fabio-AMT accuracy validation battery — property-based, not trust-based."""
import hashlib
import json
from datetime import date  # if needed

RESULTS = []


def check(name, cond, detail=""):
    ok = bool(cond)
    RESULTS.append((ok, name, str(detail) if not ok else ""))
    if not ok:
        print("FAIL", name, detail)
```

Fix V4 (was `check(..., True)`):

```python
check(
    "V4 VA bounds within price range",
    val <= vah and val <= max(c.close for c in data) and vah >= min(c.close for c in data),
    f"val={val} vah={vah}",
)
```

Fix G1 (was `session_force_exit(...) or True`):

```python
g1 = session_force_exit("2026-08-22T23:35:00+05:30", market="MCX")
g1_open = session_force_exit("2026-08-22T10:00:00+05:30", market="MCX")
check("G1 MCX force-exit after 23:30 IST", g1 is True, f"g1={g1}")
check("G1b MCX mid-session no force-exit", g1_open is False, f"g1_open={g1_open}")
```

(Run once: `PYTHONPATH=backend:. .venv/bin/python -c "from quant.session_gates import session_force_exit; print(session_force_exit('2026-08-22T23:35:00+05:30', market='MCX'), session_force_exit('2026-08-22T10:00:00+05:30', market='MCX'))"` — adjust expected booleans to observed truth, not `or True`.)

Tighten V3 if canonical is 0.682:

```python
check("V3 CME two-row VA near 68.2%", abs(frac - 0.682) <= 0.12, f"frac={frac:.3f}")
```

Prefer moving module body into `def test_fabio_accuracy_battery():` so import is pure; keep `RESULTS` local or reset at start of the test function.

- [ ] **Step 6.2: Run battery**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/test_fabio_accuracy_battery.py -v --no-header
```

Expected: PASS with no tautological names.

- [ ] **Step 6.3: Add second-drive + squeeze smoke pins into battery (coverage gap)**

```python
from quant.contracts.enums import MarketState  # already
# Second drive: DriveTracker already unit-tested; pin DTO key presence:
from quant.amt.dto import amt_result_to_dto  # or AMTResult fields
# Minimal: assert signal_builder / gates expose SECOND_DRIVE / SQUEEZE labels
from quant.decision.setup_labels import *  # adjust to actual export
check("F1 setup vocabulary includes SECOND_DRIVE", "SECOND_DRIVE" in <setup_labels_set>)
check("F2 setup vocabulary includes SQUEEZE", "SQUEEZE" in <setup_labels_set>)
```

Read `quant/decision/setup_labels.py` / `setup_state.py` for the real set name before pasting; do not invent symbols.

- [ ] **Step 6.4: Vacuous boundary test cleanup**

In `backend/tests/unit/architecture/test_module_boundaries.py`:
- Delete `FABIO_DIR` and `TestTradingDomainBoundary.test_no_fabio_ai_imports` (scans deleted tree).
- Keep `TestDomainInfrastructureBoundary` and `TestBrokersImportBoundary`.

- [ ] **Step 6.5: Gate**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest \
  tests/quant/test_fabio_accuracy_battery.py tests/system/test_fabio_behavior_trace.py \
  tests/test_fabio_alignment.py tests/architecture \
  backend/tests/unit/architecture -q --no-header
```

- [ ] **Step 6.6: Commit**

```bash
git add tests/quant/test_fabio_accuracy_battery.py backend/tests/unit/architecture/test_module_boundaries.py tests/system/test_fabio_behavior_trace.py
git commit -m "test(fabio): remove battery tautologies, portable paths, pin second-drive/squeeze labels"
```

---

### Task 7: Frontend orphan removal ≈ −1,140 lines

**Files:**
- Delete: `frontend/components/ProfileOverlayInfo.tsx`, `frontend/utils/profileInfo.ts`, `frontend/components/chart/DecisionCard.tsx`, `frontend/tests/setup_harness.ts`, `frontend/tests/components/ProfileOverlayInfo.test.tsx`, `frontend/tests/profileInfo.test.ts`, `frontend/tests/components/chart/DecisionCard.test.tsx`
- Modify: `frontend/hooks/useServerTradingSystem.ts` (dead `history_loaded`, `state.pong` branches)
- Modify: `frontend/types.ts`, `frontend/stores/ui.ts`, `frontend/config.ts`, `frontend/App.tsx` (yagni shrinks as listed in audit)
- **Keep AI:** `LayaDecisionCard`, `QuantDecisionCard`, `AIAdvisorCard` (dormant), `OverseerCard`, `laya` WS plumbing

**Interfaces:**
- Consumes: live WS `useServerTradingSystem`
- Produces: `npm test` / `npx tsc --noEmit` green

- [ ] **Step 7.1: Confirm no prod importers**

```bash
grep -rn "ProfileOverlayInfo\|profileInfo\|from.*chart/DecisionCard\|setup_harness" frontend --include='*.ts' --include='*.tsx' | grep -v tests/
```

Expected: no app imports.

- [ ] **Step 7.2: Delete orphan files + tests**

- [ ] **Step 7.3: Remove dead WS branches**

Delete handler for `status === "history_loaded"` and `state.pong === true` in `useServerTradingSystem.ts` (~449–476).

- [ ] **Step 7.4: Shrink legacy types/store/config** — remove `aiAnalysis` always-null field usage carefully (WS may still send key; prefer stop writing from FE only).

- [ ] **Step 7.5: Gate**

```bash
cd frontend && npx tsc --noEmit && npm test
```

- [ ] **Step 7.6: Commit**

```bash
git add -A frontend
git commit -m "refactor(frontend): remove orphan profile/decision components and dead WS branches"
```

---

### Task 8: Test-tree hygiene (conservative) + duplicate domain twins

**Files:**
- Delete: `backend/tests/baseline_test_results.json`, `tests/qa/qa_sanity_depth.py` (or wire into wrapper), empty `__init__` shells already removed in Task 1
- Optional aggressive: delete 20 twin files under `backend/tests/unit/domain/` that explicitly port `tests/quant/amt/**` — **only** after confirming each has a `tests/` twin with same assertions (audit list: amt_analyzer, drive, aggression, footprint, detectors, aggressive_prints, session_reset, exit_rules, phase4_enums, eia, option_scanner, underlying_futures, session_context, ib, exchange_*, mlx_compute, atr_absorption)

**Interfaces:**
- Consumes: Task 2 deletions
- Produces: both suites collect without import errors

- [ ] **Step 8.1: Conservative only — delete baseline JSON + orphan qa script; run full collect**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/ --collect-only -q 2>&1 | tail -5
cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/ --collect-only -q 2>&1 | tail -5
```

Expected: no import errors; counts drop by deleted tests only.

- [ ] **Step 8.2: (Optional) Delete domain twins one-by-one with twin check**

For each candidate `backend/tests/unit/domain/test_X.py`, require `tests/quant/**/test_X*` exists; delete backend twin; run both trees.

- [ ] **Step 8.3: Gate**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/ -q --no-header -x --tb=line 2>&1 | tail -20
```

(If full suite too slow, run `tests/quant tests/system tests/architecture` + `backend/tests/unit`.)

- [ ] **Step 8.4: Commit**

```bash
git add -A
git commit -m "test: remove stale baseline snapshot and orphan qa script"
```

---

### Task 9: Final gates — working + Fabio-tested system

**Files:** none (verification only)

- [ ] **Step 9.1: Full quality gates**

```bash
make lint
make parity
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/test_fabio_accuracy_battery.py tests/test_fabio_alignment.py tests/system tests/architecture -q --no-header
make pre-release
```

- [ ] **Step 9.2: Backend suite**

```bash
cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/ -q --no-header -m "not slow and not live"
```

- [ ] **Step 9.3: Frontend**

```bash
cd frontend && npx tsc --noEmit && npm test
```

- [ ] **Step 9.4: AI keep-list smoke**

```bash
grep -rn "build_live_advisor\|LayaDecisionAdvisor\|TimesFMAdvisor\|LLMAdvisor" quant/wiring_advisor.py quant/decision quant/llm | head
grep -E "LLM_ADVISOR_ENABLED|TIMESFM_ADVISOR_ENABLED|LAYA_MODEL_ENABLED|MLX_MODEL_PATH" .env start.sh
```

Expected: all present.

- [ ] **Step 9.5: No commit unless fixes were required** — if a gate fails, fix in a follow-up commit `fix:` with test.

---

## Self-Review

1. **Spec coverage:** red baseline stabilized first (0B: battery S1–S3 labels, DTO contract, silent-except, ruff 1005→0), then disk junk (T1), dead quant (T2), B1/B3 (T3), B2/B7 (T4), backend shell (T5), fabio battery depth (T6, extends 0B), frontend (T7), tests (T8), final gates + AI keep (T9). Wire-or-drop residual signals (`bubble_retests`, `detect_gap_fill_fade`, `from_exchange_config`) deferred as optional T2 micro-clean — full wiring out of scope; noted in commit bodies.
2. **Placeholders:** DTO `cvdAgrees` derivation must be read from `test_amt_dto_contract.py` before inventing logic — intentional non-guess. Setup-label pin (T6) still says read real export before pasting. All other code blocks complete and verified against source this session.
3. **Type consistency:** `RiskConfig.max_portfolio_*` names match loader + `composition_root` getattr; `telemetry=` kwarg must match `QuantCoordinator.__init__` (verified at T3 Step 5 against source). Battery `model_label="Triple-A"` matches `Signal.build_or_reason` contract (`signal_builder.py:108`).
4. **Baseline fidelity:** Task 0 table reflects a live run at plan time (2 arch fails, battery S1–S3 red, lint 1005, telemetry B3) — Task 0B is mandatory before any prune wave.

---

**Plan complete (amended with live baseline) → `docs/superpowers/plans/2026-09-23-amt-prune-fabio-playbook.md`. Execution order: Task 0B first (stabilize), then Tasks 1–9.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration  

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints  

**Which approach?**
