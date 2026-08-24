# Kill the Split Brain — Migrate the Entire Trading Brain into `quant/`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the whole trading brain — every analysis, decision, execution-logic, risk, probability, LLM-prompt, and RL module currently under `backend/app/domain/` — into the greenfield `quant/` package, leaving the backend as a thin **service + API layer** (orchestration, I/O adapters, HTTP/WS). The current "split brain" (legacy AMT engine in backend + parallel `quant.core` kernel) becomes ONE brain in `quant/`.

**Architecture:** Physical move of ~200 brain modules from `backend/app/domain/{fabio_ai,probability,services,trading/services,trading/models}` + `backend/app/shared/timezones.py` into `quant/`, under namespaces `quant/contracts/`, `quant/amt/`, `quant/decision/`, `quant/probability/`, `quant/execution/`, `quant/inference/`. Each move keeps a **re-export shim** at the legacy path so the backend keeps importing during the transition; differential parity tests prove the moved code behaves identically; then the backend's importers are switched to `quant.*` and the shims + legacy files are deleted. Backend keeps `api/`, `application/` (orchestration), `infrastructure/` (I/O adapters), `config/`, `core/`, `shared/`.

**Tech Stack:** Python 3.11 (env `amt_313`), pytest, dataclasses, FastAPI, existing `quant/` pure kernel, `git mv` for history-preserving moves.

## Global Constraints

- Interpreter: `/Users/apple/miniconda3/envs/amt_313/bin/python`. Backend tests run from `backend/` with that interpreter; quant tests run from repo root with the same interpreter.
- **No behavior change while a flag is off.** Every ported module must reproduce identical outputs on identical inputs (parity within `1e-6` relative for floats, exact for ints/bool/str). The only sanctioned exception is fixing a module that is already buggy — and that fix must be a separate commit with its own test, never silent.
- **Shim rule:** the moment a module is moved, the legacy path becomes `from quant.<target> import *  # moved to quant — remove after importers switch`. Backend unit suite must stay green after every move (shims guarantee it).
- **Zero `backend/` imports inside `quant/`.** Moved modules that imported `app.shared`, `app.core`, `app.domain.ports` must be rewritten to `quant.contracts.*`. If a module needs something that is I/O (e.g. `core.async_boundary`), move the tiny helper into `quant/contracts/` or pass a callable — do not import backend.
- **No placeholder code.** Every port task either moves real code, ports a real test, or writes a real parity test.
- Do NOT touch: `frontend/`, broker/paper-broker live behavior, the WS endpoint wire contract, `quant/core/`'s WS contract (`auction` DTO keys).
- Commit style: `refactor(quant): move <module> from backend brain` per module; `feat(quant): ...` for new harness code.
- Branch: work on `stable_4` (existing plans' convention) or the team's active branch — confirm before starting.

## Target File Tree

```
quant/
├── contracts/                  # shared types (moved Phase 0) — the single source of truth
│   ├── enums.py  value_objects.py  entities.py  aggregates.py  constants.py
│   ├── initial_balance.py  volume_profile_models.py  vwap_bands.py  cvd.py
│   ├── trading_context.py  events.py  event_store.py
│   ├── timezones.py  decimal_utils.py  tick_utils.py  market_data_utils.py  candle_metrics.py
│   └── ports/                  # storage, llm_inference, probability_inference, npoc,
│                               # delta_profile, broker, market_data, config_port,
│                               # exchange_strategy, notifications
├── core/                       # KEEP — current deterministic kernel (AuctionState → `auction` WS)
├── amt/                        # NEW — the full AMT engine (from backend domain/fabio_ai + services)
│   ├── analyzer.py             # AMTAnalyzer (hub — ported after its deps)
│   ├── compute.py              # mlx_compute
│   ├── models/                 # observation.py, predictions.py
│   ├── profile/                # volume_profile, delta_profile, lvn, factory, classifier
│   ├── market/                 # state_engine, structure, opening, regime, displacement,
│   │                           # break, lvn_play, acceptance_rejection, squeeze
│   ├── orderflow/              # cvd, detectors, aggression, service, footprint,
│   │                           # tick_delta, aggressive_prints, drive, drive_decay
│   ├── session/                # context, context_factory, npoc, eia, scanner, selector,
│   │                           # futures_provider, symbol_registry, ib_engine, one_min_bar
│   └── strategy/               # protocols, setup_detector, fabio_detectors
├── decision/                   # EXTEND — current kernel + moved backend gates
│   ├── gates/                  # gate_runner, three_align, confirmation_bundle,
│   │                           # signal_builder, grading, scalp, short, legacy_gate_pipeline
│   ├── sizer.py  signal_coordinator.py  trade_thesis.py  vwap_breakout.py
│   └── (existing) context.py  pipeline.py  gates_*.py  result.py  va_fade.py
│                               # decision_service.py  signal_builder.py
├── probability/                # NEW — from backend domain/probability
│   ├── agent_pipeline.py  features.py  playbook.py  regime.py
│   ├── regime_hysteresis.py  direction_timing.py  sizing.py  labels.py
├── execution/                  # EXTEND — current OMS/exits/risk + moved backend exit/risk
│   ├── exit_engine.py  exit_rules.py  exit_signal.py  trail.py  scale.py
│   ├── pyramid.py  partition.py  loss_tracker.py  session_risk_manager.py
│   ├── risk_manager.py  kill_switch.py  signal_validator.py  circuit_breakers.py
│   ├── risk_sizing.py  risk_tier.py  trade_costs.py
│   └── (existing) oms.py  order.py  exits.py  risk.py
├── inference/                  # NEW — from backend fabio_ai prediction/LLM/RL
│   ├── generative_ai.py  prompt_builder.py  llm_contract.py
│   ├── prediction.py  learning_engine.py
│   └── rl/  valentini_env.py  trainer.py  reward_shaper.py  data_loader.py
└── (existing) advisory/  bars.py  aggregator.py  coordinator.py  events.py  ...  ws_adapter.py
```

Backend after migration keeps: `app/api/`, `app/application/`, `app/infrastructure/`, `app/config*/`, `app/core/`, `app/shared/`, `app/main.py`; `app/domain/` is reduced to `app/domain/ops/` (reconciliation, self-healing, mobile_alerts, gate_rejection_tracker, latency_tracker) plus nothing else brain-related.

## Migration Strategy

**Move-with-shim + parity test.** Per module cluster:

```
git mv backend/app/domain/fabio_ai/services/vwap_breakout.py quant/decision/vwap_breakout.py
# rewrite intra-imports to quant.* absolute
# legacy path becomes a shim: backend/app/domain/fabio_ai/services/vwap_breakout.py
#     from quant.decision.vwap_breakout import *   # moved to quant
# write a parity test comparing legacy output vs quant output on fixed inputs
# port the module's existing backend unit tests into tests/quant/<tree>/
# run backend suite + quant suite -> green -> commit
```

Dependency rule for parallel agents: a module may be moved when its **dependencies** have either (a) already been moved (import `quant.*`), or (b) not yet been moved (import the legacy path — it still exists). Re-export shims make this a DAG that different agents can walk concurrently. Phase 0 lands the shared contracts first because everything imports them.

## Phase Structure & Dependency Graph

```
Phase 0 (sequential, one team)  — contracts + harness + reference pattern
  T0.1 quant/contracts scaffolding     T0.2 move shared models + ports
  T0.3 differential parity harness     T0.4 reference port pattern (vwap_breakout)
Phase 1 (parallel, 9 tracks)  — port brain module clusters, each green on its own
  A1 profile/structure | A2 market state | A3 order flow | A4 session/options
  B decision/gates | C probability | D execution/risk | E inference/RL
  A5 amt_analyzer hub (starts after A1–A4 merged; may run partially in parallel using shims)
Phase 2 (parallel)  — backend consumers switch imports to quant.*
  P2.1 application services   P2.2 handlers   P2.3 coordinators/routers
  P2.4 API routers            P2.5 infrastructure adapters   P2.6 DI composition root
  P2.7 split-brain unification (quant.core vs quant.amt analysis reconciliation)
Phase 3 (parallel)  — delete legacy brain + shims + superseded duplicates
Phase 4 (validation)  — full suites + golden replay + paper smoke + perf
```

**File-ownership rule:** no two parallel tasks touch the same physical file. Track tables below assign disjoint legacy files; Phase 2 assigns disjoint consumer files. The only shared files are `quant/contracts/__init__.py` (Phase 0, then read-only) and the parity harness (Phase 0, then read-only).

---

## Phase 0 — Contracts, Harness, Reference Pattern

### Task 0.1: Scaffold `quant/contracts/` package

**Files:**
- Create: `quant/contracts/__init__.py`
- Create: `quant/contracts/__init__` imports to be added incrementally by T0.2

**Interfaces:**
- Produces: importable `quant.contracts` package that Phase 0.2 populates.

- [ ] **Step 1: Create the package**
```bash
mkdir -p quant/contracts/ports
printf '"""Shared contracts — single source of truth for brain types."""\n' > quant/contracts/__init__.py
printf '"""Ports (interfaces) the brain consumes; implemented by backend I/O adapters."""\n' > quant/contracts/ports/__init__.py
```
- [ ] **Step 2: Verify**
`/Users/apple/miniconda3/envs/amt_313/bin/python -c "import quant.contracts, quant.contracts.ports"`
- [ ] **Step 3: Commit** `feat(quant): scaffold quant.contracts package`

---

### Task 0.2: Move shared models + ports into `quant/contracts/`

This is the highest-risk task (everything imports these). Do it in **one commit per file**, running the full backend unit suite after each.

**Files (each moved with a shim left at legacy path):**
- Move: `backend/app/domain/trading/models/enums.py` → `quant/contracts/enums.py`
- Move: `backend/app/domain/trading/models/value_objects.py` → `quant/contracts/value_objects.py`
- Move: `backend/app/domain/trading/models/entities.py` → `quant/contracts/entities.py`
- Move: `backend/app/domain/trading/models/aggregates.py` → `quant/contracts/aggregates.py`
- Move: `backend/app/domain/trading/models/{initial_balance.py, volume_profile.py, vwap_bands.py, cvd.py, trading_context.py}` → `quant/contracts/`
- Move: `backend/app/domain/trading/models/utils.py` → `quant/contracts/utils.py`
- Move: `backend/app/domain/trading/events.py` → `quant/contracts/events.py`
- Move: `backend/app/domain/trading/event_store.py` → `quant/contracts/event_store.py`
- Move: `backend/app/domain/constants.py` → `quant/contracts/constants.py`
- Move: every file in `backend/app/domain/ports/*.py` → `quant/contracts/ports/<same name>.py`
- Move: `backend/app/shared/timezones.py` → `quant/contracts/timezones.py`
- Move: `backend/app/domain/services/{decimal_utils,tick_utils,market_data_utils,candle_metrics}.py` → `quant/contracts/`
- Move: `backend/app/domain/models/exchange_config.py` → `quant/contracts/exchange_config.py` (needed by `quant/contracts/ports/exchange_strategy.py`)
- **Early move (plan amendment):** `fabio_ai/services/exit_signal.py` → `quant/execution/exit_signal.py` and `fabio_ai/services/exit_rules.py` → `quant/execution/exit_rules.py` happen here, because `quant/contracts/entities.py` and `aggregates.py` import `exit_rules.classify_exit/ExitReason` — the contract move is blocked until they are in quant. Track D therefore skips these two modules.

**Interfaces:**
- Produces (all later tasks import these): `quant.contracts.enums.Side/SignalType/Source/SetupType/MarketState/...`, `quant.contracts.value_objects.OHLC/OrderBook/AMTResult/...`, `quant.contracts.entities.Signal/Position`, `quant.contracts.aggregates.Portfolio/PortfolioConfig`, `quant.contracts.ports.{IStorage,ILLMInference,IProbabilityInference,INPOC,IDeltaProfile,IBroker,IMarketData,IConfig,...}`, `quant.contracts.timezones.IST`.

- [ ] **Step 1: Write the move script** (one file at a time — do NOT script the whole batch blindly; inspect imports after each)
```bash
git mv backend/app/domain/trading/models/enums.py quant/contracts/enums.py
```
- [ ] **Step 2: Rewrite imports inside the moved file** from `app.domain.trading.models.*` to `quant.contracts.*` (only intra-model imports exist in the moved file; verify with `grep -n "app\." quant/contracts/enums.py` → must be empty).
- [ ] **Step 3: Add the shim at the legacy path**
```python
# backend/app/domain/trading/models/enums.py
"""Re-export shim — moved to quant/contracts/enums.py. Delete after importers switch (Phase 3)."""
from quant.contracts.enums import *  # noqa: F401,F403
from quant.contracts.enums import __all__  # if defined
```
- [ ] **Step 4: Fix downstream consumers** — files that did `from app.domain.trading.models.enums import X` still work via the shim. Files that imported the *module* (`import app.domain.trading.models.enums`) still work. No consumer changes needed yet. If a moved file had a relative import from a sibling model, rewrite to `quant.contracts.<sibling>`.
- [ ] **Step 5: Port tests** — copy `backend/tests/unit/domain/trading/models/test_*.py` (and any `test_entities.py`, `test_aggregates.py`) to `tests/quant/contracts/`, changing imports to `quant.contracts.*`. Delete the originals ONLY if no backend test still needs them (shim keeps them working; keep originals until Phase 3 to be safe — instead ADD the copies now).
- [ ] **Step 6: Verify** (from `backend/`): `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short -x` then (from root): `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q`.
- [ ] **Step 7: Commit** `refactor(quant): move trading models + ports into quant/contracts`
- [ ] **Step 8: Repeat Steps 1–7 for each remaining file** in the list. For `ports/`, move each `*_port.py`/interface file; `quant/contracts/ports/__init__.py` re-exports them. For `app/shared/timezones.py`, leave a shim at `app/shared/timezones.py` (`from quant.contracts.timezones import *`). For the four `services` utils, leave shims at `app/domain/services/`.

---

### Task 0.3: Differential parity harness

**Files:**
- Create: `tests/quant/parity.py`
- Create: `tests/quant/conftest.py` (if not present)

**Interfaces:**
- Produces (every Phase 1 port task uses these):
```python
# tests/quant/parity.py
def assert_parity(legacy_fn, quant_fn, *args, tol: float = 1e-6, **kwargs) -> None:
    """Run both fns on identical args; assert equal outputs.
    Floats compared with relative tolerance `tol`; ints/bool/str/None exact;
    dataclasses compared field-by-field recursively; tuples/lists element-wise;
    dicts key-wise. Raises AssertionError with a diff on mismatch."""
```

- [ ] **Step 1: Write failing test** `tests/quant/parity/test_parity.py` — build a tiny example (e.g. two functions `f_legacy`/`f_quant` that return `{"x": 1.0}` and `{"x": 1.0000001}`) and assert `assert_parity` passes for the near-equal case and raises for a mismatched case. RED (function missing).
- [ ] **Step 2: Implement** `tests/quant/parity.py` — recursive comparison:
```python
import math
from dataclasses import fields, is_dataclass

def _eq(a, b, tol, path=""):
    if isinstance(a, float) and isinstance(b, float):
        assert math.isclose(a, b, rel_tol=tol, abs_tol=tol), f"{path}: {a} != {b}"
        return
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        assert len(a) == len(b), f"{path}: len {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            _eq(x, y, tol, f"{path}[{i}]")
        return
    if isinstance(a, dict) and isinstance(b, dict):
        assert set(a) == set(b), f"{path}: keys {set(a)^set(b)}"
        for k in a:
            _eq(a[k], b[k], tol, f"{path}.{k}")
        return
    if is_dataclass(a) and is_dataclass(b):
        assert type(a) is type(b) or type(a).__name__ == type(b).__name__, f"{path}: {type(a)} != {type(b)}"
        for f in fields(a):
            _eq(getattr(a, f.name), getattr(b, f.name), tol, f"{path}.{f.name}")
        return
    assert a == b, f"{path}: {a!r} != {b!r}"

def assert_parity(legacy_fn, quant_fn, *args, tol=1e-6, **kwargs):
    _eq(legacy_fn(*args, **kwargs), quant_fn(*args, **kwargs), tol, "root")
```
- [ ] **Step 3: Verify PASS** — `cd /Users/apple/Documents/v5-of-glassytrade-ai && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant/parity -q`
- [ ] **Step 4: Commit** `feat(quant): differential parity harness for brain migration`

---

### Task 0.4: Reference port pattern — `vwap_breakout.py` (worked example)

Every Phase 1 task follows this exact recipe. This task is the template; the tracks below only list module mappings + special cases.

**Files:**
- Move: `backend/app/domain/fabio_ai/services/vwap_breakout.py` → `quant/decision/vwap_breakout.py`
- Create shim: `backend/app/domain/fabio_ai/services/vwap_breakout.py`
- Create: `tests/quant/decision/test_vwap_breakout_parity.py`
- Create: `tests/quant/decision/test_vwap_breakout.py` (ported from any existing backend test)

**Interfaces:**
- Consumes: nothing (zero deps — that's why it's the template).
- Produces: `quant.decision.vwap_breakout.detect_vwap_breakout(vwap: float, std: float, price: float, volume: float, avg_volume: float) -> str | None`.

- [ ] **Step 1: Check for existing tests** — `grep -rn "detect_vwap_breakout" backend/tests` ; port whatever exists.
- [ ] **Step 2: Move + rewrite**
```bash
git mv backend/app/domain/fabio_ai/services/vwap_breakout.py quant/decision/vwap_breakout.py
grep -n "app\." quant/decision/vwap_breakout.py   # must be empty (module is pure)
```
- [ ] **Step 3: Add shim**
```python
# backend/app/domain/fabio_ai/services/vwap_breakout.py
"""Re-export shim — moved to quant/decision/vwap_breakout.py. Delete in Phase 3."""
from quant.decision.vwap_breakout import *  # noqa: F401,F403
```
- [ ] **Step 4: Write parity test**
```python
# tests/quant/decision/test_vwap_breakout_parity.py
from quant.decision.vwap_breakout import detect_vwap_breakout as new
from app.domain.fabio_ai.services.vwap_breakout import detect_vwap_breakout as legacy
from tests.quant.parity import assert_parity

def test_parity():
    cases = [
        dict(vwap=100.0, std=1.0, price=102.0, volume=500, avg_volume=100),  # LONG
        dict(vwap=100.0, std=1.0, price=98.0, volume=500, avg_volume=100),   # SHORT
        dict(vwap=100.0, std=1.0, price=100.5, volume=50, avg_volume=100),   # None
        dict(vwap=100.0, std=0.0, price=100.0, volume=0, avg_volume=0),      # degenerate
    ]
    for kw in cases:
        assert_parity(legacy, new, **kw)
```
- [ ] **Step 5: Run, verify PASS** — `cd /Users/apple/Documents/v5-of-glassytrade-ai && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant/decision/test_vwap_breakout_parity.py -q` and the backend unit suite from `backend/` (shim keeps `session_event_router` etc. green).
- [ ] **Step 6: Commit** `refactor(quant): move vwap_breakout from backend brain`

---

## Phase 1 — Parallel Brain Porting (9 tracks)

Each track below is one agent's disjoint workstream. A track may be split into multiple commits — one per module cluster — but every commit must leave both test suites green (shims). Order modules within a track from leaf (fewest deps) to root.

**Shared recipe (apply to every module in every track; T0.4 is the worked example):**
0. **Test-packaging prerequisite (landed in T0.4):** repo-root `conftest.py` (appends `backend/` to sys.path) and `tests/__init__.py` + `tests/quant/__init__.py` already exist so `app.*` is importable from repo root and `tests.quant` resolves under pytest. Every track assumes these.
1. `git mv` legacy → target; 2. rewrite intra-imports to `quant.*` absolute (and `app.domain.trading.models.*`/`app.shared` → `quant.contracts.*`); 3. leave shim at legacy path; 4. port existing backend unit tests into `tests/quant/<tree>/`; 5. add `assert_parity` test using the module's existing backend test fixtures (plus 2–3 synthetic edge cases); 6. run quant suite + backend unit suite; 7. commit.

**Import-rewrite map (memorize; applies everywhere):**
| Legacy | → quant |
|---|---|
| `app.domain.trading.models.enums` | `quant.contracts.enums` |
| `app.domain.trading.models.value_objects` | `quant.contracts.value_objects` |
| `app.domain.trading.models.entities` | `quant.contracts.entities` |
| `app.domain.trading.models.aggregates` | `quant.contracts.aggregates` |
| `app.domain.trading.models.<x>` | `quant.contracts.<x>` |
| `app.domain.trading.event_store` / `events` | `quant.contracts.event_store` / `events` |
| `app.domain.ports.<x>` | `quant.contracts.ports.<x>` |
| `app.domain.constants` | `quant.contracts.constants` |
| `app.shared.timezones` | `quant.contracts.timezones` |
| `app.domain.services.decimal_utils` / `tick_utils` / `market_data_utils` / `candle_metrics` | `quant.contracts.<same>` |
| `app.domain.services.volume_profile` | `quant.amt.profile.volume_profile` |
| `app.domain.services.lvn_detector` | `quant.amt.profile.lvn` |
| `app.domain.services.delta_profile` | `quant.amt.profile.delta_profile` |
| `app.domain.fabio_ai.services.<x>` | `quant.amt.<track>/<x>` (see tables) |
| `app.domain.probability.<x>` | `quant.probability.<x>` |

**Dependency-safe rule:** if a needed module has not been moved yet, import its **legacy path** (it still exists). Add a `# TODO(migration): switch to quant.* once <module> moves` comment. A final sweep in Phase 2 removes these.

---

### Track A1 — Profile & structure (agent 1)
**Targets:** `quant/amt/profile/`
| Move from | → to |
|---|---|
| `domain/services/volume_profile.py` | `quant/amt/profile/volume_profile.py` |
| `domain/services/delta_profile.py` | `quant/amt/profile/delta_profile.py` |
| `domain/services/lvn_detector.py` | `quant/amt/profile/lvn.py` |
| `fabio_ai/services/profile_factory.py` | `quant/amt/profile/factory.py` |
| `fabio_ai/services/profile_classifier.py` | `quant/amt/profile/classifier.py` |
| `fabio_ai/ports/three_align.py` (input protocol) | `quant/amt/profile/three_align_input.py` |

Deps: `quant/contracts.*` only. Existing tests: `backend/tests/unit/domain/services/test_volume_profile*.py`, `.../test_delta_profile*.py`, `.../test_lvn_detector*.py`, `backend/tests/unit/domain/fabio_ai/test_profile_classifier*.py`, `test_profile_factory*.py`. Note `profile_factory.py` currently does `from amt_analyzer import IncrementalVolumeProfile` (re-export) — after A5 moves `amt_analyzer`, change that import to `quant.amt.analyzer`. Until then keep `IncrementalVolumeProfile` importable from `quant.amt.profile.volume_profile`.

**Acceptance:** parity tests for `create_profile`, `compute_poc`, `compute_value_area`, `find_lvns`, `find_hvns`, `classify_shape`, `detect_high_delta_zones` on: empty input, single candle, 60-bar synthetic session (reuse `tests/quant/test_golden_file.py::_session_bars` style), and one real recorded day (Phase 0 recording — see Task 0.5 below; until it exists, use the largest synthetic fixture).

### Track A2 — Market state & structure (agent 2)
**Targets:** `quant/amt/market/`
| Move from | → to |
|---|---|
| `fabio_ai/services/market_state_engine.py` | `quant/amt/market/state_engine.py` |
| `fabio_ai/services/market_structure_classifier.py` | `quant/amt/market/structure.py` |
| `fabio_ai/services/opening_classifier.py` | `quant/amt/market/opening.py` |
| `fabio_ai/services/regime_detector.py` | `quant/amt/market/regime.py` |
| `domain/services/displacement_detector.py` | `quant/amt/market/displacement.py` |
| `domain/services/break_detector.py` | `quant/amt/market/break_detector.py` (`break` is a keyword — cannot be a module name) |
| `domain/services/lvn_play_detector.py` | `quant/amt/market/lvn_play.py` |
| `domain/services/acceptance_rejection.py` | `quant/amt/market/acceptance_rejection.py` |
| `fabio_ai/strategy/squeeze_detector.py` | `quant/amt/market/squeeze.py` |

Deps: A1 (`profile`), contracts. Existing tests: `test_market_state_engine*.py`, `test_market_structure_classifier*.py`, `test_opening_classifier*.py`, `test_regime_detector*.py`, `test_displacement_detector*.py`, `test_break_detector*.py`, `test_lvn_play_detector*.py`, `test_acceptance_rejection*.py`, `test_squeeze_detector*.py` (search `backend/tests` for each name; port all hits).

### Track A3 — Order flow (agent 3)
**Targets:** `quant/amt/orderflow/`
| Move from | → to |
|---|---|
| `fabio_ai/services/cvd_tracker.py` | `quant/amt/orderflow/cvd.py` |
| `fabio_ai/services/orderflow_detectors.py` | `quant/amt/orderflow/detectors.py` |
| `fabio_ai/services/aggression_scorer.py` | `quant/amt/orderflow/aggression.py` |
| `fabio_ai/services/order_flow_service.py` | `quant/amt/orderflow/service.py` |
| `fabio_ai/services/footprint_analyzer.py` | `quant/amt/orderflow/footprint.py` |
| `fabio_ai/services/drive_tracker.py` | `quant/amt/orderflow/drive.py` |
| `fabio_ai/services/drive_decay.py` | `quant/amt/orderflow/drive_decay.py` |
| `domain/services/tick_delta.py` | `quant/amt/orderflow/tick_delta.py` |
| `domain/services/aggressive_prints.py` | `quant/amt/orderflow/aggressive_prints.py` |
| `fabio_ai/services/mlx_compute.py` | `quant/amt/compute.py` |

Special cases: `mlx_compute.py` — keep the MLX-acceleration guarded so the pure numpy fallback works in quant (it already falls back; verify). `tick_delta.py` has no `app.core` deps (verify); if `candle_delta_proxy` imports something app-only, move that helper into `quant/contracts/`. Existing tests: `test_cvd_tracker*.py`, `test_orderflow_detectors*.py`, `test_aggression_scorer*.py`, `test_order_flow_service*.py`, `test_footprint_analyzer*.py`, `test_drive_tracker*.py`, `test_tick_delta*.py`, `test_aggressive_prints*.py`, `test_mlx_compute*.py`.

### Track A4 — Session & options (agent 4)
**Targets:** `quant/amt/session/`
| Move from | → to |
|---|---|
| `fabio_ai/services/session_context.py` | `quant/amt/session/context.py` |
| `fabio_ai/services/session_context_factory.py` | `quant/amt/session/context_factory.py` |
| `fabio_ai/services/npoc_tracker.py` | `quant/amt/session/npoc.py` |
| `fabio_ai/services/eia_calendar.py` | `quant/amt/session/eia.py` |
| `fabio_ai/services/option_scanner.py` | `quant/amt/session/scanner.py` |
| `fabio_ai/services/option_selector.py` | `quant/amt/session/selector.py` |
| `domain/services/underlying_futures_provider.py` | `quant/amt/session/futures_provider.py` |
| `domain/services/symbol_registry.py` | `quant/amt/session/symbol_registry.py` |
| `domain/services/initial_balance_engine.py` | `quant/amt/session/ib_engine.py` |
| `domain/services/ib_breakout_scalp.py` | `quant/amt/session/ib_scalp.py` |
| `domain/services/one_min_bar_engine.py` | `quant/amt/session/one_min_bar.py` |

Special cases: `session_context.py` imports `app.core.async_boundary` and `app.shared.timezones` — rewrite to `quant.contracts.timezones` and pass a storage callable / use `quant.contracts.ports.IStorage` (never import `app.core`). `underlying_futures_provider.py` loads `config/instruments.json` — keep the file path configurable (`InstrumentConfigProvider(Path)`); the backend passes the path. `option_scanner.py` calls broker async methods (`core.async_boundary`) — the scanner is a *scheduler/orchestration* concern; **move only its pure scoring/selection logic** (`_score_contract`, `_detect_momentum`, `ContractSwitchGuard`) into `quant/amt/session/scanner_core.py` and leave the async scanner shell in `backend/app/application/services/option_scanner_service.py` (new), or keep the whole file in quant with an injected `fetch` callable. Prefer: pure core in quant, async shell in backend. Existing tests: `test_session_context*.py`, `test_session_context_factory*.py`, `test_npoc_tracker*.py`, `test_option_scanner*.py`, `test_option_selector*.py`, `test_underlying_futures_provider*.py`, `test_initial_balance*.py`, `test_ib_breakout_scalp*.py`, `test_one_min_bar_engine*.py`.

### Track B — Decision & gates (agent 5)
**Targets:** `quant/decision/` (extend) + `quant/decision/gates/`
| Move from | → to |
|---|---|
| `fabio_ai/services/gate_pipeline.py` | `quant/decision/gates/legacy_gate_pipeline.py` (rename: keep the module-level API `GatePipeline/GateContext/GateResult/GateType/GateReason`) |
| `fabio_ai/services/entry_gates/gate_runner.py` | `quant/decision/gates/gate_runner.py` |
| `fabio_ai/services/entry_gates/three_align.py` | `quant/decision/gates/three_align.py` |
| `fabio_ai/services/entry_gates/confirmation_bundle.py` | `quant/decision/gates/confirmation_bundle.py` |
| `fabio_ai/services/entry_gates/signal_builder.py` | `quant/decision/gates/signal_builder.py` |
| `fabio_ai/services/entry_gates/grading.py` | `quant/decision/gates/grading.py` |
| `fabio_ai/services/position_sizer.py` | `quant/decision/sizer.py` |
| `fabio_ai/services/signal_coordinator.py` | `quant/decision/signal_coordinator.py` |
| `fabio_ai/services/trade_thesis.py` | `quant/decision/trade_thesis.py` |
| `domain/services/scalp_gate_pipeline.py` | `quant/decision/gates/scalp.py` |
| `domain/services/short_signal_gates.py` | `quant/decision/gates/short.py` |

Special cases: `gate_pipeline.py` in `domain/fabio_ai` is the DI-wired one; `domain/services/gate_pipeline.py` is a 417-byte re-export shim (delete it — dead). The existing `quant/decision/signal_builder.py` (greenfield) is DIFFERENT from `entry_gates/signal_builder.py` — the moved one keeps its name `build_entry_signal`; do not merge the two. Existing tests: `backend/tests/unit/domain/fabio_ai/test_gate_pipeline*.py`, `.../entry_gates/test_gate_runner*.py`, `test_three_align*.py`, `test_confirmation_bundle*.py`, `test_entry_gate_signal_builder*.py`, `test_grading*.py`, `.../services/test_scalp_gate_pipeline*.py`, `test_short_signal_gates*.py`, `.../test_position_sizer*.py`, `test_signal_coordinator*.py`, `test_trade_thesis*.py`.

### Track C — Probability (agent 6)
**Targets:** `quant/probability/`
| Move from | → to |
|---|---|
| `domain/probability/agent_pipeline.py` | `quant/probability/agent_pipeline.py` |
| `domain/probability/features.py` | `quant/probability/features.py` |
| `domain/probability/playbook.py` | `quant/probability/playbook.py` |
| `domain/probability/regime_classifier.py` | `quant/probability/regime.py` |
| `domain/probability/regime_hysteresis_store.py` | `quant/probability/regime_hysteresis.py` |
| `domain/probability/direction_timing.py` | `quant/probability/direction_timing.py` |
| `domain/probability/sizing.py` | `quant/probability/sizing.py` |
| `domain/probability/labels.py` | `quant/probability/labels.py` |

Special cases: `agent_pipeline.py` imports `entry_gates.three_align.three_align_check` and `entry_gates.gate_runner.run_gate_pipeline` (Track B) and `probability.features` — import from `quant.decision.gates.*` / `quant.probability.features`. `features.py` exports `FEATURE_NAMES`, `PROBABILITY_FEATURE_SCHEMA_VERSION`, `ACTIVE_FEATURE_NAMES` — these constants are read by `health.py`/`lgbm_probability_adapter.py` via the shim; keep exact values. Existing tests: `backend/tests/unit/domain/probability/*` (port all).

### Track D — Execution & risk (agent 7)
**Targets:** `quant/execution/` (extend)
| Move from | → to |
|---|---|
| `fabio_ai/services/exit_engine.py` | `quant/execution/exit_engine.py` |
| `fabio_ai/services/exit_rules.py` | `quant/execution/exit_rules.py` |
| `fabio_ai/services/exit_signal.py` | `quant/execution/exit_signal.py` |
| `fabio_ai/services/trail_engine.py` | `quant/execution/trail.py` |
| `fabio_ai/services/scale_manager.py` | `quant/execution/scale.py` |
| `fabio_ai/services/pyramid_manager.py` | `quant/execution/pyramid.py` |
| `fabio_ai/services/partition_exit_manager.py` | `quant/execution/partition.py` |
| `fabio_ai/services/loss_tracker.py` | `quant/execution/loss_tracker.py` |
| `fabio_ai/services/session_risk_manager.py` | `quant/execution/session_risk_manager.py` |
| `domain/trading/services/risk_manager.py` | `quant/execution/risk_manager.py` |
| `domain/trading/services/kill_switch.py` | `quant/execution/kill_switch.py` |
| `domain/trading/services/signal_validator.py` | `quant/execution/signal_validator.py` |
| `domain/services/circuit_breakers.py` | `quant/execution/circuit_breakers.py` |
| `domain/services/risk_sizing_engine.py` | `quant/execution/risk_sizing.py` |
| `domain/services/risk_tier_engine.py` | `quant/execution/risk_tier.py` |
| `domain/services/trade_costs.py` | `quant/execution/trade_costs.py` |

Special cases: `exit_engine.py` mutates `quant/contracts/entities.Position` — the contract must keep the exact fields (`cushion_state`, `initial_stop`, `peak_profit`, `mae`, `mfe`, scale-in fields, etc.); do NOT slim the dataclass during migration. `loss_tracker.py` imports `app.core.async_boundary` + `ports.storage` — rewrite to `quant.contracts.ports.IKeyValueStorage` and replace the async-boundary wrapper with a direct call (the storage impl is sync). The existing greenfield `quant/execution/exits.py`/`risk.py` are a DIFFERENT lightweight engine — keep them for the deterministic `QuantEngine` path; the moved `ExitEngine`/`RiskManager` are the production brain. Do not merge now; Phase 2.7 unification decides the canonical exit path. Existing tests: `test_exit_engine*.py`, `test_exit_rules*.py`, `test_trail_engine*.py`, `test_scale_manager*.py`, `test_pyramid_manager*.py`, `test_partition_exit_manager*.py`, `test_loss_tracker*.py`, `test_session_risk_manager*.py`, `test_risk_manager*.py`, `test_kill_switch*.py`, `test_signal_validator*.py`, `test_circuit_breakers*.py`, `test_risk_sizing_engine*.py`, `test_risk_tier_engine*.py`, `test_trade_costs*.py`.

### Track E — Inference & RL (agent 8)
**Targets:** `quant/inference/`
| Move from | → to |
|---|---|
| `fabio_ai/services/generative_ai_service.py` | `quant/inference/generative_ai.py` |
| `fabio_ai/services/prompt_builder.py` | `quant/inference/prompt_builder.py` |
| `fabio_ai/services/llm_contract.py` | `quant/inference/llm_contract.py` |
| `fabio_ai/services/prediction_engine.py` | `quant/inference/prediction.py` |
| `fabio_ai/services/learning_engine.py` | `quant/inference/learning_engine.py` |
| `fabio_ai/models/predictions.py` | `quant/amt/models/predictions.py` (or `quant/inference/models.py` — pick one, keep imports consistent) |
| `fabio_ai/rl/valentini_env.py` | `quant/inference/rl/valentini_env.py` |
| `fabio_ai/rl/trainer.py` | `quant/inference/rl/trainer.py` |
| `fabio_ai/rl/reward_shaper.py` | `quant/inference/rl/reward_shaper.py` |
| `fabio_ai/rl/data_loader.py` | `quant/inference/rl/data_loader.py` |

Special cases: `generative_ai_service.py` depends only on `ports.llm_inference` + `prompt_builder` — rewrite to `quant.contracts.ports.ILLMInference`. The MLX/GGUF/LGBM **adapters stay in backend** (I/O) and implement `quant.contracts.ports.*`. `prompt_builder.py` is 904 lines of pure string rendering — high-value, low-risk move; port `OverseerAction` (pydantic BaseModel) as a plain dataclass with the same field names (keep the pydantic import only if `pydantic` is acceptable inside quant — check `quant/requirements`; if none, prefer dataclass). `rl/trainer.py` imports `sb3_contrib`/`gymnasium` optionally — keep the graceful-degradation guards. Existing tests: `test_generative_ai_service*.py`, `test_prompt_builder*.py`, `test_prediction_engine*.py`, `test_learning_engine*.py`, `backend/tests/unit/domain/fabio_ai/rl/*` (or `test_valentini_*.py`).

### Track A5 — AMT analyzer hub (agent 9, may start after A1–A4 merge or run concurrently using shims)
**Targets:** `quant/amt/analyzer.py`
| Move from | → to |
|---|---|
| `fabio_ai/services/amt_analyzer.py` (1383 lines — the hub) | `quant/amt/analyzer.py` |

Deps: A1–A4, `quant.contracts.*`, `quant.amt.compute`, `quant/amt/models/`. Because it imports ~15 other brain modules, use the dependency-safe rule: import `quant.amt.*` where moved, legacy path otherwise (add `# TODO(migration)`). Rewrite `services/volume_profile.create_profile` refs → `quant.amt.profile.volume_profile`. Keep `AMTAnalyzer`, `AMTConfig`, `IncrementalVolumeProfile` re-exported from `quant/amt/analyzer.py` (consumers import `IncrementalVolumeProfile` from `amt_analyzer`). Existing tests: `backend/tests/unit/domain/fabio_ai/test_amt_analyzer*.py` (large — port the full file set), plus `backend/tests/validation/*` that exercise the analyzer.

**Acceptance for Track A5:** the backend `AMTService` (application layer) continues to produce identical `AMTResult` DTOs on the same candle stream (guaranteed by shim + parity tests on `AMTAnalyzer.analyze` output fields: `poc`, `value_area_high/low`, `market_state`, `cvd_slope`, `aggression`, `lvns`, `hvns`, `ib_high/low`, `profile_shape`).

---

## Task 0.5 (prerequisite for real-data parity, can run in parallel with Phase 1): Capture recorded sessions

**Files:**
- Create: `backend/scripts/record_brain_session.py`
- Create: `tests/fixtures/sessions/*.jsonl`

**Interfaces:**
- Produces: 2–3 JSONL files, each one line per bar `{time, open, high, low, close, volume, buy_volume, delta, order_book}` captured from a real/paper run, plus a `tests/quant/parity/test_session_replay.py` that replays a file through both `AMTAnalyzer` (legacy shim) and `quant.amt.analyzer` and `assert_parity`es the `AMTResult`.

- [ ] **Step 1: Write the recorder** — hook into `AMTService.run_analysis` (temporarily, behind env `QUANT_RECORD_SESSION=1`): append each `amt_data[-1]` OHLC + order book to a JSONL file per symbol/date. Keep it a small, separate script that does not change the default path.
- [ ] **Step 2: Capture** — run paper mode for a day (or replay `backend/tests` synthetic sessions if a live day is unavailable) and commit 2 files (one NSE-style, one MCX-style synthetic but realistic).
- [ ] **Step 3: Commit** `feat(quant): recorded brain sessions for parity replay`

---

## Phase 2 — Backend Consumers Switch to `quant.*` (parallel)

After Phase 1, every brain symbol is importable from `quant.*` and from its legacy shim. These tasks flip the backend importers to `quant.*` so Phase 3 can delete the legacy files. Each task is one agent; file ownership is disjoint.

| Task | Files to flip (imports → `quant.*`) |
|---|---|
| **P2.1** application services | `application/services/amt_service.py`, `analysis_service.py`, `entry_coordinator.py`, `exit_coordinator.py`, `session_event_router.py`, `session_phase_manager.py`, `session_risk_coordinator.py`, `session_state_manager.py`, `phase_manager.py`, `trading_session.py`, `state_snapshot_builder.py`, `startup_contracts.py`, `engine_lifecycle.py`, `experiment_context.py`, `quant_bridge.py` (already quant) |
| **P2.2** handlers | `application/handlers/amt_handler.py`, `llm_entry_handler.py`, `llm_overseer_handler.py`, `trade_lifecycle_handler.py`, `pre_candle_advisor.py`, `post_trade_analyst.py`, `rl_handler.py`, `entry_gate_coordinator.py` |
| **P2.3** coordinators/engine | `application/engine.py`, `candle_aggregator.py`, `watchdog_manager.py`, `session_orchestrator.py`, `session_runtime_contracts.py`, `trading_query_service.py`, `ai_command_service.py` |
| **P2.4** API routers | `api/routers/{health,ai,analysis,rl,metrics}.py`, `api/websocket/gameloop.py`, `api/dependencies.py` |
| **P2.5** infrastructure adapters | `infrastructure/adapters/{delta_profile_adapter,npoc_adapter,lgbm_probability_adapter,mlx_inference_adapter,gguf_inference_adapter,paper_broker,dhan_adapter}.py`, `infrastructure/serialization/schemas.py`, `infrastructure/metrics.py` |
| **P2.6** DI + config | `application/di/composition_root.py`, `application/di/container.py`, `config_models/settings_adapter.py` (keep reading `quant.contracts` config objects) |

**Shared recipe per task:**
- [ ] **Step 1:** For each file, `grep -n "app.domain" <file>` and replace with the `quant.*` import per the import-rewrite map. For symbols only available through shims, resolve to the real quant path.
- [ ] **Step 2:** Remove `# TODO(migration)` legacy imports introduced in Phase 1 tracks.
- [ ] **Step 3:** Verify — `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest backend/tests/unit -q --tb=short` from `backend/` (3 env-broken suites ignored) plus the integration suite that covers that consumer.
- [ ] **Step 4:** Commit `refactor(backend): <layer> imports brain from quant.*`

**P2.7 — Split-brain unification (agent 7):**
- [ ] **Step 1:** Write `tests/quant/unification/test_auction_vs_amt.py`: feed the recorded sessions (Task 0.5) through BOTH `quant/core` AuctionCoordinator AND `quant/amt/analyzer`; compare the overlapping fields (`poc`, `vah`, `val`, `vwap`, `cvd`, `delta`) and the WS `auction` DTO.
- [ ] **Step 2:** Decide the canonical analysis path. Default decision (recommended): keep `quant/core` as the real-time `auction`-contract producer (already verified byte-compatible with the frontend WS contract), and treat `quant/amt` as the full-featured engine used by gates/decision. If the diff is within tolerance → document the divergence budget and keep both but make `quant/core` consume `quant/amt`'s profile/VWAP primitives where they overlap (deleting the duplicate implementations in `quant/core` that are subsumed, e.g. `volume_profile.py`, `vwap.py` primitives). If the diff is NOT within tolerance → investigate and fix the loser, then delete the loser's overlapping implementation. Record the decision in `docs/AMT_UNIFICATION.md`.
- [ ] **Step 3:** After deletion of subsumed `quant/core` files, delete their `tests/quant/test_volume_profile.py`/`test_vwap.py` ONLY if parity with the AMT primitives is proven; otherwise keep both.
- [ ] **Step 4:** Commit `refactor(quant): unify analysis primitives — single source of truth in quant.amt`

---

## Phase 3 — Deletion & Cleanup (parallel after Phase 2 green)

| Task | Deletes |
|---|---|
| **P3.1** | `backend/app/domain/fabio_ai/` (entire tree — shims gone after P2), `backend/app/domain/probability/` |
| **P3.2** | `backend/app/domain/services/` brain files (analysis + execution + decision files moved in Phase 1); keep only ops files → relocate them to `backend/app/domain/ops/` (`position_reconciliation.py`, `startup_reconciliation.py`, `self_healing.py`, `mobile_alerts.py`, `gate_rejection_tracker.py`, `latency_tracker.py`) |
| **P3.3** | `backend/app/domain/trading/services/` (risk_manager, kill_switch, signal_validator — moved), `backend/app/domain/trading/models/` shims + `events.py`/`event_store.py` shims |
| **P3.4** | all `backend/app/domain/fabio_ai/services/` and `entry_gates/` re-export shims; `backend/app/shared/timezones.py` shim → point backend imports at `quant.contracts.timezones`; `app/domain/services/gate_pipeline.py` dead shim |
| **P3.5** | Superseded `quant/core` duplicates (after P2.7), stale `docs/` notes, `Makefile`/`start_*.sh`/`conftest.py` path updates |

**Recipe per task:**
- [ ] **Step 1:** `grep -rn "from app.domain.<deleted tree>" backend/ --include=*.py` → must be empty (or only ops). Fix stragglers.
- [ ] **Step 2:** `git rm -r` the tree; if a file was a shim, `git rm` it too.
- [ ] **Step 3:** Update `backend/start.sh`, `start_preflight.sh` (syntax-check lists), `pytest.ini`, and any import-linter config (`.importlinter`) to the new layout.
- [ ] **Step 4:** Run full backend suite + quant suite + `tests/system`. Commit `refactor(backend): delete legacy brain — backend is service+API only`.

---

## Phase 4 — Validation & Acceptance (one owner, not parallel)

- [ ] **Step 1: Full suites** — `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest backend/tests/unit -q --tb=short`, `... tests/integration -q`, `... tests/validation -q`; `cd /Users/apple/Documents/v5-of-glassytrade-ai && ... -m pytest tests/quant tests/system -q`.
- [ ] **Step 2: Import-lint** — `/Users/apple/miniconda3/envs/amt_313/bin/python -c "import app.main; import quant"` and verify `quant/` contains zero `backend/` imports: `grep -rn "import app\.\|from app\." quant/ --include=*.py` → empty.
- [ ] **Step 3: Golden replay** — replay the recorded sessions (Task 0.5) through the migrated brain; assert identical `AMTResult`/`AuctionState` vs the pre-migration capture (commit the capture as golden JSONL if not already).
- [ ] **Step 4: Paper smoke** — run `start.sh` in paper mode for one session; confirm no import errors, WS `auction`/`quantDecision` fields render, no new logs errors.
- [ ] **Step 5: Performance** — compare tick-to-analysis latency before/after (target: no regression > 10%; `mlx_compute` must still use MLX when available).
- [ ] **Step 6: Update docs** — `docs/AMT_ARCHITECTURE_PROPOSAL.md` "greenfield" note now matches reality: backend = service + API + I/O; quant = brain. Commit.

---

## Definition of Done

1. `backend/app/domain/` contains only `app/domain/ops/` (reconciliation/self-healing/alerts/metrics support). No `fabio_ai`, no `probability`, no brain `services`, no `trading/models`, no `trading/services`.
2. `quant/` contains the entire brain and imports zero `app.*` modules.
3. All backend imports resolve through `quant.*`; no shims remain.
4. Both test suites (backend + quant/system) pass; parity tests cover every moved module.
5. The recorded-session golden replay reproduces identical analysis output.
6. WS contract to the frontend is unchanged (verified by `tests/system/test_quant_runtime_e2e.py`).
7. Paper run boots clean.

## Rollback

Every Phase 1/2/3 commit is a `git mv`-based refactor on a branch. To roll back a module: `git checkout <commit-before> -- <legacy> <quant>` restores both. Never delete a legacy file before the backend importers for it are flipped (Phase 2 gate). Keep the `stable_4` branch as the rollback baseline.

## Known Risks & Mitigations

- **Circular imports during move** (`profile_factory` ↔ `amt_analyzer`): mitigate by keeping `IncrementalVolumeProfile` importable from `quant.amt.profile.volume_profile` and re-exported from `quant.amt.analyzer`; the `# TODO(migration)` comment rule lets any module import any other from either location during Phase 1.
- **`exit_engine` mutates `Position`**: contracts must be moved intact (Task 0.2) before Track D; never slim `Position` in Phase 1.
- **Behavior drift in floats**: every ported module gets a parity test; `mlx_compute` MLX-vs-numpy divergence is guarded by a fixed tolerance test.
- **Two exit engines / two VP implementations coexist temporarily**: this is the intended "split brain" reduction sequence — P2.7 makes the final call with a written record, not a silent merge.
- **`option_scanner`/`session_context` touch async/app-core**: split pure logic into quant, keep async shell in backend; never let quant block on broker I/O.

---

# AUDIT ADOPTION (2026-08-06 — AUDIT_FULLSTACK.md, AUDIT_FULL_SYSTEM.md, AUDIT_FRONTEND.md)

The three audits validate this migration and surface findings to fold in. The audits observed the post-Phase-0/1 state (shims already present from Tracks A1–A4); their central complaint — **two parallel engines, one executes, 60+ shims obscure the graph** — is precisely what this plan resolves. The audit's own "remediation plan" (FULL_SYSTEM §9: delete shims → wire greenfield → kill legacy → migrate to QuantEngine → fix training data) maps onto Phases 2/3/4 of this plan. Adopted findings, each mapped to a workstream below.

## Adopted findings → workstreams

| Audit ID | Finding | Adoption (workstream / phase) |
|---|---|---|
| B-31/32/33 (FULL_SYSTEM) | 60+ shims: broken tracebacks, star imports, test-surface inflation | **Minimize the shim window.** Phase 3 (delete shims + legacy) is now P0. **NOTE (parallel-safe deviation):** Phase 2 tracks swap consumer imports to `quant.*` but do NOT delete shims (a shim may be shared by consumers in different tracks — deleting early breaks a parallel track). Phase 3 deletes ALL shims at once after a repo-wide grep confirms zero `app.domain` references remain. |
| B-22 / B-12 | `QUANT_DECISION_ENABLED` defaults off; quant decisions never execute | **NEW WS-EXEC** (Phase 2.1): after the brain lands in quant, flip `QUANT_DECISION_ENABLED=true` behind A/B: `QUANT_EXECUTION_MODE=quant|legacy|shadow`. Quant path executes via existing `quant_signal_mapper` → `EntryCoordinator`; legacy stays as fallback. |
| B-20 (FULLSTACK) | `AMTAnalyzer.analyze` calls `_update_session_vwap()` twice — VWAP double-accumulates (Critical) | **NEW WS-BUGFIX** (runs after Track A5 lands): fix in `quant/amt/analyzer.py`, one commit, parity+golden pinned. Also fix Track-A3-flagged `drive_decay` UnboundLocalError + `drive` undefined `tick_size`. |
| B-18/B-06 | AMTAnalyzer not thread-safe; per-tick `asyncio.to_thread` | Keep the existing per-symbol lock in the orchestrator (application layer) — documented, not fixed in Phase 1. Defer hot-path queue rewrite to Phase 4. |
| B-01 | Option scanner blocks startup 2 min | **Phase 3 cleanup**: move scanner call off the lifespan critical path (async task + readiness poll). |
| B-13 | AMT failure → zero-valued sentinel flows downstream | **Phase 3**: `run_analysis` failure must abort entry evaluation (only exits/overseer continue), never feed sentinel to gates/agents. |
| B-39/B-40 | SQLite no WAL; no index on `ticks(symbol,time)` | **Phase 4**: enable WAL + add index (2 small tasks, parallel-safe). |
| B-13 (audit) | Signal TTL 10 min too long | **Phase 4**: reduce `AGENT_DECISION_THRESHOLD`/stale threshold to 60 s for scalps. |
| F-05/F-03 (FRONTEND) | Frontend gap-filling fabricates zero-volume candles → false LVN | **NEW WS-FRONTEND (Phase 4)**: remove `mergeCandleData` forward-fill + `gap_fill` branch; render gaps. Also F-20 (AIAnalysisPanel 1,525-line god component) decomposition, F-13 (IST offset constant), F-58 (delete unused `useInstrumentsStore`). Enforce "no fabricated data" as a frontend rule too. |
| F-07 (FRONTEND) | 3 analysis types side-by-side, no authority | **Phase 4**: make `quantDecision`/`auction` the primary decision card; gray out legacy `amtAnalysis`; then delete `amtAnalysis` when legacy path is removed. |
| FULL_SYSTEM §7 | Training data (key-value) vs live prompt (prose) mismatch | **NEW WS-DATA (Phase 4)**: verify `amt_dataset/nifty_amt_data_livefmt/` matches current `prompt_builder.py` output; add format validation test; retrain on livefmt. |
| Q-02 / Appendix C | Dual Portfolio (Decimal quant vs float backend) | Resolved by Phase 0.2 (single `quant/contracts/aggregates.py`). Confirm `trade_aggregate.py` is deleted in Phase 3 (it is a duplicate). |
| Appendix B | 2-line stub modules listed as dead | NOTE: many "2-line stubs" the audit lists were already the REAL modules being moved (audit snapshot lag). Trust `git`/tests, not the audit's dead-code list, for individual files. |

## New parallel workstreams (added to Phase 2/3/4)

- **WS-EXEC — Wire quant decisions to execution (Phase 2.1):** flip the flag + A/B routing (above). Files: `session_event_router.py` (routing), `config_models/settings_adapter.py` + `feature_flags.yaml` (`QUANT_EXECUTION_MODE`), `quant_bridge.py` (default on). E2E test: legacy-vs-quant outcome journal on a recorded session.
- **WS-BUGFIX — Brain bugfix track (after Track A5):** double-VWAP (B-20), `drive_decay` UnboundLocalError, `drive` undefined `tick_size`, `break_detector` dead-code tail. One fix per commit, each with a regression test.
- **WS-FRONTEND — Frontend honesty + decomposition (Phase 4):** remove fabrication (F-03/F-05), collapse to one decision card (F-07), decompose AIAnalysisPanel (F-20), centralize IST offset (F-13), delete `useInstrumentsStore` (F-58).
- **WS-DATA — Training-data format parity (Phase 4):** align `amt_dataset/livefmt` with `prompt_builder.py`, add format guard test.

## Parallel execution protocol (how the multi-agent team runs)

1. **Worktrees, not a shared tree.** Before dispatching, create one isolated worktree per remaining track:
   ```bash
   cd /Users/apple/Documents/v5-of-glassytrade-ai
   git worktree add ../wt-track-B -b migration/track-B
   ```
   Each agent works ONLY inside its worktree, commits on its branch, never touches `stable_4` until merged. Disjoint file ownership (the module tables above) makes merges trivial fast-forwards.
2. **Dispatch N implementers in parallel** (one per track): B, C, D, E, A5 (all independent now that A1–A4 are in `stable_4`). Each gets its brief + the worktree path. Same review gate per track (task reviewer on the branch range), then:
   ```bash
   git worktree remove ../wt-track-B --force
   git checkout stable_4 && git merge migration/track-B --ff-only
   git branch -d migration/track-B
   ```
3. **Serialization points:** Phase 2 (consumer import-swap) tracks may run in parallel with each other but AFTER Phase 1 lands. WS-EXEC and WS-BUGFIX run after A5. Phase 3 (delete) runs after Phase 2. Phase 4 validation is single-owner.
4. **Merge-order rule:** merge branches in any order (disjoint files), but re-run the full suite after each merge before the next dispatch wave.

---

# PONYTAIL AUDIT ADOPTION (over-engineering removal)

## Findings ADOPTED (safe deletions, dispatched as parallel workstreams)
- **WS-PT-BROKERS** — delete dead demo/broker-library weight in `brokers/`: `scripts/`, `broker/bulk_historical.py`, `broker/http_client_sync.py`, `broker/symbol_matcher.py` (dup of `utils/symbol.py`), `broker/mcx_futures.py`, dead `DhanConfig` fields (`retry_delay`, `rate_limit_per_second`, `circuit_breaker_threshold`, `circuit_breaker_timeout`), `TOTPGenerator` → `pyotp.TOTP`, and never-imported deps (torch/transformers/peft/accelerate) from `brokers/requirements.txt`. **GUARD:** `brokers/broker/` core (`types`, `entities`, `dhan` broker) is a LIVE backend dependency (`dhan_adapter.py`, `dhan_broker_adapter.py` import `DhanBroker`/`Exchange`/`Instrument`). Do NOT delete `DhanFacade` or `BrokerFactory`/`BrokerGateway`/`CircuitBreakerWrapper` without confirming live coupling; if live, keep + report. Verify the full backend + brokers test suites after.
- **WS-PT-DI** — remove dead DI registrations + their adapters ONLY if unreferenced: `INotification→NullNotificationAdapter`, `IDeltaProfile→delta_profile_adapter`, `INPOC→npoc_adapter`, `IExchangeStrategy→{mcx,nse}_strategy`; delete `core/events.py` EventStore (test-only), `application/events/` package (zero callers), `core/circuit_breaker.py` delegation shim; delete dead feature flags (`duckdb_storage`, `initial_balance_engine`, `correlation_guard`, `iv_vix_features`, `shap_feature_pruning`, `llm_entry_gate`). Guard: grep-first; keep anything referenced.
- **WS-PT-DUP** — dedup: make `core/async_boundary.py` re-export `quant.contracts.sync_boundary` (byte-identical helpers); replace `LLMCircuitBreaker` with `shared.resilience.CircuitBreaker`; replace hand-rolled OrderedDict+hashlib cache in `quant/inference/generative_ai.py` with `functools.lru_cache`; keep `core/metrics.py` (prometheus_client swap only if the dep is available; else report).
- **WS-PT-CONFIG** — collapse the triple config stack (`config/consolidated.py` pydantic + `settings_adapter` + `config_models.SystemConfig`) to ONE canonical source; keep env override + feature_flags.yaml; verify all config consumers still resolve.

## Findings REJECTED (with evidence — do NOT delete)
- **`quant/amt/compute.py` "test-only"** — REJECTED: imported by production `quant/amt/{analyzer, orderflow/footprint, orderflow/cvd, profile/classifier, market/structure}`. Deleting breaks the brain.
- **Greenfield `quant/` engine (`runtime.py`, `state.py`, `events.py`, `ws_adapter.py`, `persistence.py`, `aggregator.py`, `advisory/`, `tools/replay.py`, `execution/{exits,oms,risk}.py`, `triple_a.py`) "test-only"** — REJECTED: `quant_bridge.py` (production) uses `AuctionCoordinator` for the WS `auction` field; `QuantEngine`+PaperOMS drive the §5.5 paper protocol (WS-SMOKE test) and the architecture proposal's required determinism/replay story. This is the documented P2.7 "KEEP BOTH" outcome.
- **Gate/risk duplication collapse (2 SignalBuilders, 3 gate pipelines, 2 ExitEngines, 2 risk stacks)** — DEFERRED: this is the P2.7 KEEP-BOTH architecture (greenfield deterministic engine vs production AMT engine). Consolidating is a deliberate design decision with real risk; schedule as its own review, not a mechanical deletion.

## Net expected: ~8-10k lines removed (mostly `brokers/scripts/` + broker dead-weight + dead DI/config).
