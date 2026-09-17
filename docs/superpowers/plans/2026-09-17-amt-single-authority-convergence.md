# AMT Single-Authority Convergence & Prune Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the deterministic Fabio AMT gate pipeline the single entry authority, make the Trend/Mean-Reversion model transition real and enforced in one place, correct the mean-reversion (VA reclaim) semantics, and delete the dead second decision path plus all stale scaffolding — so the AMT strategy system is simple, correct, and actually the thing that trades.

**Architecture:** Today two entry engines exist. Production runs the **TimesFM E2E** path (`start.sh:41` and `.env:78` set `TIMESFM_END_TO_END=true`), which bypasses the entire Fabio gate stack (`pipeline.py`, `gates_edge.py`, `va_fade.py`, `DecisionService`). This plan inverts that: `AmtScalpingStrategy → DecisionService → GatePipeline` becomes the only entry authority; TimesFM is demoted to a forecast provider that feeds exits/UI/journal but never decides an entry. A single `model_router` selects TREND vs MEAN_REVERSION from `market_state`, with certified evidence allowed to override a lagging VA label; Gate 3 paths are tagged with their model and the router is enforced once, in `DecisionService`.

**Tech Stack:** Python 3.13, pytest, no new external dependencies.

## Global Constraints

- Base branch: `architecture/design-level-refactoring` (current HEAD `7b3dfecc`).
- Tests run with the repo venv: `PYTHONPATH=backend:. .venv/bin/python -m pytest`.
- Every task ends with passing targeted tests + a commit. No task may leave the tree red.
- Golden-tape determinism (`tests/determinism/`, `tests/quant/runtime/golden/`) must be re-golded only with an explicit before/after justification in the commit message.
- Certification traces under `tests/quant/certification/golden/` may move ONLY in WS-F, only with the human-readable before/after diff attached.
- Do NOT trust audit docs as current truth; every claim below was verified against source on 2026-09-17. Re-verify a line before editing it.
- `docs/reviews/2026-09-16-test-integrity-ledger.md` is the failure baseline: fail count must be identical-or-better at every PR gate.
- Every new constant gets a `# ponytail:` comment naming the playbook/methodology source.
- Worktrees have no `.venv`; use the absolute interpreter: `/Users/apple/Documents/v5-of-glassytrade-ai/.venv/bin/python`.

---

## Decisions Register (locked 2026-09-17 by product owner)

| # | Decision | Value |
|---|---|---|
| D1 | Entry authority | **Deterministic Fabio AMT gates** (`GatePipeline`). TimesFM demoted to forecast/confidence input. E2E `should_enter` branch deleted. |
| D2 | Model transition | **State selects, evidence can override.** `IMBALANCED → TREND`, `BALANCED → MEAN_REVERSION`; a complete `SetupEvidence` or an initiative break with acceptance overrides a lagging VA label. Enforced in ONE place. |
| D3 | Prune scope | **Full prune**: dead path, `quantv2/`, stale worktrees, unreachable code, dead params, tautological test, stale plan docs. |
| D4 | Sizing | The margin-aware fix (`1deadaa9`) is already committed; only the dead `forecast` parameter and the misleading comment are removed. Sizing stays deterministic (House Money Protocol). |
| D5 | TimesFM forecast | Kept as a provider (`TimesFMEngine.last_forecast_for`) feeding exits/UI; the `TimesFMTradingStrategy` class is deleted. |

## Out of Scope

- Rewriting the TimesFM model/advisor internals.
- Live broker E2E validation (needs market hours).
- `LiveOMS.add_pyramid` E9 feature work — we only delete its unreachable body, not implement it.

---

## Parallel Workstream Map (multi-agent)

Worktree cut from HEAD; one agent per stream. Streams A/B/C are the critical path; D and E can start immediately and in parallel; F gates the merge.

```
                    HEAD 7b3dfecc
                         │
        ┌────────────────┼─────────────────┬───────────────┐
        ▼                ▼                 ▼               ▼
   WS-A authority   WS-B router       WS-C reversion   WS-D prune
   (runtime/        (model_router,    (va_fade         (quantv2,
    strategies)      gates_edge,       reclaim,         worktrees,
                     decision_service) exit=POC)        live_oms,
        │                │                 │            dead param)
        └────────────────┴────────┬────────┘               │
                                  ▼                        │
                             WS-E execution truth ◄────────┘
                             (tests, metrics, docs)
                                  │
                                  ▼
                             WS-F verify + regolden
```

| Stream | Branch | Agent role | Depends on |
|---|---|---|---|
| WS-A Single authority | `ws-a2/single-authority` | Systems/architecture engineer | — |
| WS-B Model router | `ws-b2/model-router` | Domain engineer (AMT) | — (touches `decision_service.py`, coordinate with WS-C) |
| WS-C Reversion correctness | `ws-c2/va-reclaim` | Domain engineer (AMT) | — |
| WS-D Prune & hygiene | `ws-d2/prune` | Refactor/hygiene engineer | — (must NOT delete `live_oms.py` region that WS-E reads) |
| WS-E Execution truth | `ws-e2/exec-truth` | Test/integration engineer | WS-A (forecast provider), WS-D |
| WS-F Verification | `ws-f2/cert-regolden` | Integration validator | all |

**Merge order:** WS-D → WS-A → WS-B → WS-C → WS-E → WS-F. WS-B and WS-C both edit `decision_service.py`: WS-B takes the top-of-file router region (`:29-159`), WS-C takes the VA-fade fallback region (`:153-180`); WS-C rebases after WS-B.

**Shared-file collision protocol:** before editing `decision_service.py`, `gates_edge.py`, or `context.py`, run `git fetch . <other-branch>` and diff those files. If a stream needs a field another stream adds, the LATER stream rebases; never duplicate the field.

---

## File Structure

**Create:**
- `quant/strategies/selection.py` — single entry-authority factory.
- `quant/decision/model_router.py` — the ONE model selector (state + evidence override).
- `quant/decision/forecast_provider.py` — forecast access for exits/UI (wraps `TimesFMEngine`).
- `tests/quant/runtime/test_single_authority.py`
- `tests/quant/decision/test_model_router.py` (replaces the tautological one)
- `tests/quant/decision/test_va_fade_reclaim_semantics.py`
- `tests/quant/strategies/test_selection.py`

**Modify:**
- `quant/runtime.py:509-525` (strategy selection), `:1178-1199` (`_fresh_forecast`)
- `quant/strategies/__init__.py` (drop `TimesFMTradingStrategy` export)
- `quant/decision/decision_service.py:29-39,110-181` (router region + fade fallback)
- `quant/decision/gates_edge.py:199-271` (tag paths with model + setup key)
- `quant/decision/result.py` (add `GateResult.setup_key`)
- `quant/decision/va_fade.py` (reclaim semantics)
- `quant/execution/risk.py:380-391,486-497` (drop dead `forecast` param)
- `quant/engine/submission_handler.py:172-187` (stop passing `forecast`)
- `quant/execution/live_oms.py:448-524` (delete unreachable body)
- `start.sh:41`, `.env:5,78`, `backend/.env:5,78` (drop `TIMESFM_END_TO_END`)
- `docs/amt/fabio_decision_pipeline.md` (Gate-3 two-model contract)

**Delete:**
- `quant/strategies/timesfm_strategy.py` and its entry tests
- `quantv2/` (bytecode-only tree)
- `.worktrees/{certification,contract-exchange,coordinator-universe,risk-money-path,runtime-isolation,ws-a,ws-b,ws-c}` (stale branches are ancestors of HEAD)

---

# WS-D: Prune & Hygiene (start first — no dependencies)

### Task D1: Delete the bytecode-only `quantv2/` tree

**Files:**
- Delete: `quantv2/` (0 `.py` files, only `__pycache__/*.pyc`, zero importers)

- [ ] **Step 1: Prove zero importers**

Run: `grep -rn "quantv2" --include='*.py' . | grep -v __pycache__`
Expected: no output.

- [ ] **Step 2: Delete and verify nothing breaks**

```bash
git rm -r quantv2
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant -q -x --timeout=120 -p no:cacheprovider
```
Expected: identical pass/fail set to baseline.

- [ ] **Step 3: Commit**

```bash
git commit -m "chore(prune): delete bytecode-only quantv2/ tree (zero .py sources, zero importers)"
```

### Task D2: Remove stale git worktrees and orphaned bytecode

**Files:**
- Remove: `.worktrees/*`; Delete: `quant/decision/__pycache__/gates_session_position.*.pyc`

- [ ] **Step 1: Confirm each worktree branch is an ancestor of HEAD**

```bash
for b in certification contract-exchange coordinator-universe risk-money-path runtime-isolation ws-a ws-b ws-c; do
  ref=$(git -C .worktrees/$b rev-parse HEAD 2>/dev/null)
  git merge-base --is-ancestor "$ref" HEAD && echo "$b: ancestor (safe)" || echo "$b: NOT ancestor (STOP)"
done
```
Expected: every line ends `ancestor (safe)`. If any says `NOT ancestor`, STOP and report — do not delete.

- [ ] **Step 2: Remove worktrees and prune**

```bash
for b in certification contract-exchange coordinator-universe risk-money-path runtime-isolation ws-a ws-b ws-c; do
  git worktree remove --force .worktrees/$b 2>/dev/null || true
done
git worktree prune
git worktree list
```
Expected: only the main worktree remains.

- [ ] **Step 3: Remove orphaned bytecode**

```bash
git rm -f quant/decision/__pycache__/gates_session_position.*.pyc 2>/dev/null || true
find . -name '__pycache__' -type d -prune -not -path './.git/*' -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
```

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore(prune): remove 8 stale worktrees (all ancestors of HEAD) and orphaned gate bytecode"
```

### Task D3: Delete unreachable body of `LiveOMS.add_pyramid`

**Files:**
- Modify: `quant/execution/live_oms.py:448-524`

- [ ] **Step 1: Confirm the raise is unconditional and the body unreachable**

Run: `sed -n '440,525p' quant/execution/live_oms.py`
Expected: `raise ValueError(` at `:448`, then ~72 lines of unreachable code to `:524`.

- [ ] **Step 2: Delete everything after the raise**

Replace the method body so it ends immediately after the `raise ... )`. The final method must read exactly:

```python
        raise ValueError(
            "E9: pyramids disabled under LiveOMS — submit→fill→linked-close "
            "not implemented end-to-end; refusing to create a ghost pyramid "
            "position"
        )
```
(no statements after it).

- [ ] **Step 3: Test**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_live_oms.py -q -p no:cacheprovider`
Expected: PASS (the raise is still exercised by `test_live_oms.py:275-286`).

- [ ] **Step 4: Commit**

```bash
git add quant/execution/live_oms.py
git commit -m "refactor(oms): delete 72 lines unreachable after unconditional raise in add_pyramid"
```

### Task D4: Remove the dead `forecast` parameter from sizing

**Files:**
- Modify: `quant/execution/risk.py:380-391` (`position_size` signature), `:479-503` (`pyramid_position_size`)
- Modify: `quant/engine/submission_handler.py:172-187`
- Test: `tests/quant/execution/test_risk_sizing_derivatives.py`, `tests/quant/execution/test_lot_aware_risk.py`

**Interfaces:**
- Produces: `SessionRisk.position_size(entry, sl, lot_size=1.0, max_rupee_risk_cap=None, is_expiry=False, max_lots=None, side="LONG", freeze_limit=None) -> float` (no `forecast`).
- Produces: `SessionRisk.pyramid_position_size(entry, sl, lot_size=1.0, is_expiry=False, max_lots=None, side="LONG", freeze_limit=None) -> float`.

- [ ] **Step 1: Prove the parameter is never read**

Run: `grep -n "forecast" quant/execution/risk.py`
Expected: only the two parameter declarations (`:388`, `:486`) and the pass-through (`:497`) — no read in any body. If a read appears, STOP: the premise changed.

- [ ] **Step 2: Remove the parameter and pass-through**

Delete `forecast: Any | None = None,` from both signatures and `forecast=forecast,` from the `pyramid_position_size` call. Remove the now-unused `Any` import only if nothing else uses it (`grep -n "Any" quant/execution/risk.py`).

- [ ] **Step 3: Stop passing it, and delete the misleading comment**

In `quant/engine/submission_handler.py`, `_fresh_forecast()` at `:173` is now used only by exits. Remove the `forecast=tfm_fc` argument from the `position_size(...)` call at `:179-187` and replace the `# ... dynamic Kelly & VaR sizing` comment block (`:172`) with:

```python
        # Sizing is deterministic (House Money Protocol, SessionRisk is the
        # single authority). TimesFM forecasts feed exits/UI only — they must
        # not silently change position size.
```

- [ ] **Step 4: Update tests that pass the keyword**

Run: `grep -rn "forecast=" tests/quant/execution/ | grep -v __pycache__`
Expected: hits in `test_lot_aware_risk.py`, `test_risk_sizing_derivatives.py`. Remove the `forecast=...` keyword from each call (the behavior is unchanged).

- [ ] **Step 5: Test**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/ -q --timeout=90 -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add quant/execution/risk.py quant/engine/submission_handler.py tests/quant/execution/
git commit -m "refactor(sizing): drop dead forecast param — sizing is deterministic, forecast feeds exits only"
```

### Task D5: Archive superseded plan docs

**Files:**
- Move: the completed/duplicated 2026-09-17 plans into `docs/archive/plans/`

- [ ] **Step 1: Create archive dir and move the two superseded plans**

```bash
mkdir -p docs/archive/plans
git mv docs/superpowers/plans/2026-09-17-fabio-amt-alignment-code-quality.md docs/archive/plans/ 2>/dev/null || true
git mv docs/plans/2026-09-16-ws-*-brief.md docs/archive/plans/ 2>/dev/null || true
```

- [ ] **Step 2: Replace the two 2026-09-17 plans' status with a pointer**

Add to the top of `docs/superpowers/plans/2026-09-17-fabio-playbook-alignment-production-readiness.md`:

```markdown
> **SUPERSEDED 2026-09-17:** Tasks 10-13 are DONE. Tasks 14-19 are replaced by
> `docs/superpowers/plans/2026-09-17-amt-single-authority-convergence.md`.
```

- [ ] **Step 3: Commit**

```bash
git add docs/
git commit -m "docs(plans): archive superseded workstream briefs; point task-14+ to convergence plan"
```

---

# WS-A: Single Entry Authority

### Task A1: Add the entry-authority factory

**Files:**
- Create: `quant/strategies/selection.py`
- Test: `tests/quant/strategies/test_selection.py`

**Interfaces:**
- Produces: `build_strategy(*, decision_service=None, exit_engine=None) -> AmtScalpingStrategy`

- [ ] **Step 1: Write the failing test**

```python
# tests/quant/strategies/test_selection.py
"""The entry authority is always the deterministic Fabio AMT playbook."""
from quant.strategies.selection import build_strategy
from quant.strategies.amt_scalping import AmtScalpingStrategy


def test_build_strategy_returns_amt_scalping():
    assert isinstance(build_strategy(), AmtScalpingStrategy)


def test_env_cannot_change_entry_authority(monkeypatch):
    """TIMESFM_END_TO_END must not select a different entry authority."""
    monkeypatch.setenv("TIMESFM_END_TO_END", "true")
    assert isinstance(build_strategy(), AmtScalpingStrategy)
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/strategies/test_selection.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: quant.strategies.selection`.

- [ ] **Step 3: Implement the factory**

```python
# quant/strategies/selection.py
"""Single entry-authority factory — the deterministic Fabio AMT playbook.

Decision 2026-09-17: the gate pipeline is the only thing allowed to approve an
entry. TimesFM no longer selects an entry strategy; it provides forecasts to
exits/UI (see quant/decision/forecast_provider.py).
"""
from __future__ import annotations

from quant.strategies.amt_scalping import AmtScalpingStrategy


def build_strategy(*, decision_service=None, exit_engine=None) -> AmtScalpingStrategy:
    """Return the one entry authority. Ignored env/strategy inputs cannot change it."""
    return AmtScalpingStrategy(
        decision_service=decision_service,
        exit_engine=exit_engine,
    )


__all__ = ["build_strategy"]
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/strategies/test_selection.py -q -p no:cacheprovider`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add quant/strategies/selection.py tests/quant/strategies/test_selection.py
git commit -m "feat(strategy): single entry-authority factory (AMT gates); env cannot override"
```

### Task A2: Runtime always builds the AMT strategy

**Files:**
- Modify: `quant/runtime.py:509-525`
- Test: `tests/quant/runtime/test_single_authority.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/quant/runtime/test_single_authority.py
"""QuantEngine's entry strategy is the AMT playbook regardless of env."""
from unittest.mock import MagicMock
from quant.runtime import QuantEngine
from quant.strategies.amt_scalping import AmtScalpingStrategy


def _engine(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("TIMESFM_END_TO_END", raising=False)
    else:
        monkeypatch.setenv("TIMESFM_END_TO_END", value)
    return QuantEngine(gateway=MagicMock(), symbol="CRUDEOIL")


def test_default_strategy_is_amt(monkeypatch):
    assert isinstance(_engine(monkeypatch, None)._strategy, AmtScalpingStrategy)


def test_env_true_does_not_select_timesfm(monkeypatch):
    assert isinstance(_engine(monkeypatch, "true")._strategy, AmtScalpingStrategy)


def test_env_false_still_amt(monkeypatch):
    assert isinstance(_engine(monkeypatch, "false")._strategy, AmtScalpingStrategy)
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/runtime/test_single_authority.py -q -p no:cacheprovider`
Expected: FAIL on `test_env_true_does_not_select_timesfm` (currently builds `TimesFMTradingStrategy`).

- [ ] **Step 3: Replace the selection block**

In `quant/runtime.py`, replace lines `:509-525` (the `use_timesfm_e2e` branch) with:

```python
        # Strategy — single entry authority (decision 2026-09-17): the
        # deterministic Fabio AMT gate pipeline. An explicitly injected strategy
        # (tests/replay) still wins; nothing else may swap the entry authority.
        if strategy is not None:
            self._strategy = strategy
        else:
            from quant.strategies.selection import build_strategy
            self._strategy = build_strategy(
                decision_service=self._decision_service,
                exit_engine=self._exits,
            )
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/runtime/test_single_authority.py -q -p no:cacheprovider`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add quant/runtime.py tests/quant/runtime/test_single_authority.py
git commit -m "refactor(runtime): AMT gates are the single entry authority; TIMESFM_END_TO_END no longer selects strategy"
```

### Task A3: Forecast provider keeps exits/UI fed

**Files:**
- Create: `quant/decision/forecast_provider.py`
- Modify: `quant/runtime.py:1178-1199` (`_fresh_forecast`)
- Test: `tests/quant/decision/test_forecast_provider.py`

**Interfaces:**
- Consumes: `TimesFMEngine.last_forecast_for(symbol, identity=None)` (`quant/decision/timesfm_engine.py:192`).
- Produces: `fresh_forecast(advisor, strategy, *, symbol, bar_index) -> Any | None` — advisor engine first, then strategy fallback, else `None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/quant/decision/test_forecast_provider.py
from unittest.mock import MagicMock
from quant.decision.forecast_provider import fresh_forecast


def test_prefers_advisor_native_engine():
    fc = object()
    advisor = MagicMock()
    advisor._native_engine.last_forecast_for.return_value = fc
    assert fresh_forecast(advisor, None, symbol="NIFTY", bar_index=5) is fc


def test_falls_back_to_strategy_then_none():
    strategy = MagicMock()
    strategy.get_latest_forecast.return_value = None
    advisor = MagicMock()
    advisor._native_engine.last_forecast_for.return_value = None
    assert fresh_forecast(advisor, strategy, symbol="NIFTY", bar_index=5) is None


def test_no_advisor_no_strategy_returns_none():
    assert fresh_forecast(None, None, symbol="NIFTY", bar_index=5) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_forecast_provider.py -q -p no:cacheprovider`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the provider**

```python
# quant/decision/forecast_provider.py
"""Forecast access for exits/UI — NOT an entry authority (decision 2026-09-17)."""
from __future__ import annotations

from typing import Any


def fresh_forecast(advisor: Any, strategy: Any, *, symbol: str, bar_index: int) -> Any | None:
    """Return the latest TimesFM forecast for ``symbol``, or None.

    Order: the advisor's native engine cache (single inference per bar, shared
    with the UI), then the strategy's cache (transitional), else None. The
    caller applies the staleness rule (bar_index - asof_bar <= 1).
    """
    engine = getattr(advisor, "_native_engine", None) if advisor is not None else None
    if engine is not None:
        getter = getattr(engine, "last_forecast_for", None)
        if callable(getter):
            fc = getter(symbol)
            if fc is not None:
                return fc
    getter = getattr(strategy, "get_latest_forecast", None) if strategy is not None else None
    if callable(getter):
        return getter(symbol)
    return None


__all__ = ["fresh_forecast"]
```

- [ ] **Step 4: Rewire `_fresh_forecast`**

In `quant/runtime.py:1178-1199`, replace the `tfm_fc = getattr(self._strategy, ...)` line with a call to the provider, keeping the existing staleness logic unchanged:

```python
        from quant.decision.forecast_provider import fresh_forecast
        tfm_fc = fresh_forecast(
            getattr(self, "_advisor", None),
            getattr(self, "_strategy", None),
            symbol=self.symbol,
            bar_index=self._bar_index,
        )
```

- [ ] **Step 5: Test**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_forecast_provider.py tests/quant/test_exit_manager.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add quant/decision/forecast_provider.py quant/runtime.py tests/quant/decision/test_forecast_provider.py
git commit -m "feat(runtime): decouple forecast access from entry strategy (advisor engine first)"
```

### Task A4: Delete `TIMESFM_END_TO_END` from scripts/env

**Files:**
- Modify: `start.sh:41`, `.env:5,78`, `backend/.env:5,78`
- Test: `tests/quant/runtime/test_single_authority.py`

- [ ] **Step 1: Remove the env lines**

Delete the `TIMESFM_END_TO_END=...` line from `start.sh` and both occurrences (lines 5 and 78) from `.env` and `backend/.env`. Leave `TIMESFM_ADVISOR_ENABLED` and `TIMESFM_CONTRACT_SELECTION` untouched.

- [ ] **Step 2: Add a no-reader guard test**

Append to `tests/quant/runtime/test_single_authority.py`:

```python
def test_no_code_reads_timesfm_end_to_end():
    """The entry-authority switch is gone; no module may read the env var."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[3]
    offenders = []
    for path in root.glob("quant/**/*.py"):
        if "TIMESFM_END_TO_END" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], f"TIMESFM_END_TO_END still read in {offenders}"
```

- [ ] **Step 3: Test**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/runtime/test_single_authority.py -q -p no:cacheprovider`
Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add start.sh .env backend/.env tests/quant/runtime/test_single_authority.py
git commit -m "chore(config): remove TIMESFM_END_TO_END — entry authority is no longer env-switched"
```

### Task A5: Delete `TimesFMTradingStrategy` and its entry tests

**Files:**
- Delete: `quant/strategies/timesfm_strategy.py`
- Modify: `quant/strategies/__init__.py:9-11`
- Delete/modify the tests that assert E2E entry behavior.

- [ ] **Step 1: List every importer and classify**

Run: `grep -rn "TimesFMTradingStrategy" --include='*.py' . | grep -v __pycache__`
Expected list (verified 2026-09-17): `quant/strategies/__init__.py`, `tests/quant/strategies/test_timesfm_strategy.py`, `tests/quant/strategies/test_timesfm_provider_adoption.py`, `tests/quant/decision/test_timesfm_strategy_cache.py`, `tests/quant/decision/test_timesfm_engine.py:314`, `tests/quant/decision/test_strategy_behavior.py:468,527`, `tests/quant/amt/session/test_scanner_timesfm.py:259`, `scripts/pre_release_decision_check.py:265`, `scripts/audit_e2e_entry_probe.py:19`, `tests/architecture/test_no_dead_exports.py:46`.

- [ ] **Step 2: Delete the class and its export**

```bash
git rm quant/strategies/timesfm_strategy.py
```
Edit `quant/strategies/__init__.py` to export only `AmtScalpingStrategy`:

```python
from quant.strategies.amt_scalping import AmtScalpingStrategy
from quant.strategies.selection import build_strategy

__all__ = ["AmtScalpingStrategy", "build_strategy"]
```

- [ ] **Step 3: Delete E2E-entry tests; keep forecast coverage on `TimesFMEngine`**

```bash
git rm tests/quant/strategies/test_timesfm_strategy.py
git rm tests/quant/strategies/test_timesfm_provider_adoption.py
git rm tests/quant/decision/test_timesfm_strategy_cache.py
```
For `test_timesfm_engine.py:300-330`, `test_strategy_behavior.py:460-570`, and `test_scanner_timesfm.py:255-262`: delete ONLY the cases that construct `TimesFMTradingStrategy` and assert `should_enter`/entry behavior. Forecast-caching assertions must move to `TimesFMEngine.last_forecast_for` if not already covered — verify with:
`grep -n "last_forecast_for\|record_forecast" tests/quant/decision/test_timesfm_engine.py`
If no coverage exists, add one test in `test_timesfm_engine.py`:
```python
def test_last_forecast_for_returns_recorded():
    from unittest.mock import MagicMock
    from quant.decision.timesfm_engine import TimesFMEngine
    eng = TimesFMEngine.__new__(TimesFMEngine)
    eng._forecast_cache = {}
    sentinel = object()
    eng.record_forecast("NIFTY", 7, sentinel)
    assert eng.last_forecast_for("NIFTY") is sentinel
```

- [ ] **Step 4: Fix scripts and the dead-export guard**

- `scripts/pre_release_decision_check.py:265-268` and `scripts/audit_e2e_entry_probe.py:19,55`: delete the `TimesFMTradingStrategy` blocks (these scripts probe a path that no longer exists). If a script becomes empty, delete the file.
- `tests/architecture/test_no_dead_exports.py:46`: remove the now-inaccurate NOTE comment referencing `TimesFMTradingStrategy`.

- [ ] **Step 5: Test the affected suites**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/strategies/ tests/quant/decision/ tests/quant/amt/session/test_scanner_timesfm.py tests/architecture/ -q --timeout=120 -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(strategy): delete TimesFMTradingStrategy entry path; forecasts stay via TimesFMEngine"
```

---

# WS-B: Model Router (state selects, evidence overrides)

### Task B1: Add `GateResult.setup_key`

**Files:**
- Modify: `quant/decision/result.py`
- Test: `tests/quant/decision/test_gate_result_setup_key.py`

**Interfaces:**
- Produces: `GateResult(gate: int, passed: bool, reason: str = "", setup_key: str = "")`.

- [ ] **Step 1: Read the current dataclass**

Run: `cat quant/decision/result.py`
Expected: a small dataclass. Note its exact field names before editing.

- [ ] **Step 2: Write the failing test**

```python
# tests/quant/decision/test_gate_result_setup_key.py
from quant.decision.result import GateResult


def test_gate_result_carries_setup_key_defaulting_empty():
    assert GateResult(3, True, "ok").setup_key == ""
    assert GateResult(3, True, "ok", setup_key="TRIPLE_A").setup_key == "TRIPLE_A"
```

- [ ] **Step 3: Run to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_gate_result_setup_key.py -q -p no:cacheprovider`
Expected: FAIL — unexpected keyword `setup_key`.

- [ ] **Step 4: Add the field**

Add `setup_key: str = ""` as the last field of `GateResult` (keep it defaulted so every existing constructor keeps working).

- [ ] **Step 5: Test + commit**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_gate_result_setup_key.py -q -p no:cacheprovider`
Expected: 1 passed.
```bash
git add quant/decision/result.py tests/quant/decision/test_gate_result_setup_key.py
git commit -m "feat(decision): GateResult carries the setup key for model routing"
```

### Task B2: Add the single model selector

**Files:**
- Create: `quant/decision/model_router.py`
- Test: `tests/quant/decision/test_model_router.py` (REPLACE the existing tautological file)

**Interfaces:**
- Produces: `Model = Literal["TREND","MEAN_REVERSION"]`; constants `TREND`, `MEAN_REVERSION`.
- Produces: `setup_model(setup_key: str) -> Model | None`
- Produces: `select_model(ctx: DecisionContext) -> Model`
- Produces: `allows(setup_key: str, model: Model) -> bool`

- [ ] **Step 1: Delete the tautological test and write the real one**

```bash
git rm tests/quant/decision/test_model_router.py
```

```python
# tests/quant/decision/test_model_router.py
"""One selector: auction state picks the model, certified evidence may override."""
import pytest
from quant.contracts.enums import MarketState
from quant.decision.model_router import (
    TREND, MEAN_REVERSION, allows, select_model, setup_model,
)
from quant.decision.setup_state import SetupEvidence


def _ctx(**kw):
    from quant.decision.context import DecisionContext
    base = dict(market_state=MarketState.BALANCED)
    base.update(kw)
    return DecisionContext(**{k: v for k, v in base.items()
                              if k in DecisionContext.__dataclass_fields__})


def _ev(setup_type, direction="LONG", **kw):
    ev = SetupEvidence(setup_type=setup_type, direction=direction,
                       cvd_agrees=True, **kw)
    return ev


def test_setup_model_mapping():
    assert setup_model("TRIPLE_A") == TREND
    assert setup_model("LVN_SNIPER") == TREND
    assert setup_model("INITIATIVE") == TREND
    assert setup_model("SQUEEZE") == TREND
    assert setup_model("SECOND_DRIVE") == TREND
    assert setup_model("VA_FADE") == MEAN_REVERSION
    assert setup_model("NOPE") is None


def test_balanced_selects_mean_reversion():
    assert select_model(_ctx(market_state=MarketState.BALANCED)) == MEAN_REVERSION


def test_imbalanced_selects_trend():
    assert select_model(_ctx(market_state=MarketState.IMBALANCED)) == TREND


def test_complete_va_fade_evidence_overrides_imbalanced():
    ev = _ev("VA_FADE", rejection=True, acceptance=False)
    assert ev.is_complete()
    assert select_model(_ctx(market_state=MarketState.IMBALANCED,
                             setup_evidence=ev)) == MEAN_REVERSION


def test_initiative_break_overrides_balanced():
    assert select_model(_ctx(market_state=MarketState.BALANCED,
                             break_type="INITIATIVE", break_direction="UP")) == TREND


def test_incomplete_evidence_does_not_override():
    ev = _ev("VA_FADE", rejection=False, acceptance=False)
    assert not ev.is_complete()
    assert select_model(_ctx(market_state=MarketState.IMBALANCED,
                             setup_evidence=ev)) == TREND


def test_allows_is_model_scoped():
    assert allows("VA_FADE", MEAN_REVERSION)
    assert not allows("VA_FADE", TREND)
    assert allows("TRIPLE_A", TREND)
    assert not allows("TRIPLE_A", MEAN_REVERSION)
    assert not allows("UNKNOWN", TREND)
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_model_router.py -q -p no:cacheprovider`
Expected: FAIL — `quant.decision.model_router` not found.

- [ ] **Step 3: Implement the selector**

```python
# quant/decision/model_router.py
"""The ONE place that maps auction state -> playbook model.

Decision 2026-09-17 (D2): IMBALANCED -> TREND, BALANCED -> MEAN_REVERSION.
A *complete* evidence snapshot or a certified initiative break may override a
lagging VA label, because the session-scale VA classification lags the
displacement that actually starts a trend (or the failed auction that starts a
reversion). This module is the single enforcement point; gates only report
which setup fired via GateResult.setup_key.
"""
from __future__ import annotations

from typing import Literal

from quant.contracts.enums import MarketState
from quant.decision.context import DecisionContext

Model = Literal["TREND", "MEAN_REVERSION"]

TREND = "TREND"
MEAN_REVERSION = "MEAN_REVERSION"

_TREND_SETUPS = frozenset(
    {"TRIPLE_A", "SECOND_DRIVE", "LVN_SNIPER", "INITIATIVE", "SQUEEZE"}
)
_REVERSION_SETUPS = frozenset({"VA_FADE"})


def setup_model(setup_key: str) -> Model | None:
    """Map a setup key to its playbook model, or None if unknown."""
    key = str(setup_key or "").upper()
    if key in _TREND_SETUPS:
        return TREND
    if key in _REVERSION_SETUPS:
        return MEAN_REVERSION
    return None


def _evidence_override(ctx: DecisionContext) -> Model | None:
    """Model forced by certified evidence, or None when the state label rules."""
    ev = getattr(ctx, "setup_evidence", None)
    if ev is not None:
        is_complete = getattr(ev, "is_complete", None)
        if callable(is_complete) and is_complete():
            m = setup_model(str(getattr(ev, "setup_type", "")))
            if m is not None:
                return m
    # A certified initiative break is displacement evidence the VA label may not
    # have caught up to yet — ponytail: Fabio Model 1 initiation.
    if str(getattr(ctx, "break_type", "") or "").upper() == "INITIATIVE":
        if str(getattr(ctx, "break_direction", "") or ""):
            return TREND
    return None


def select_model(ctx: DecisionContext) -> Model:
    """Return the active playbook model for this bar (evidence > state)."""
    override = _evidence_override(ctx)
    if override is not None:
        return override
    state = getattr(ctx, "market_state", MarketState.BALANCED)
    value = state.value if hasattr(state, "value") else str(state)
    if value == MarketState.IMBALANCED.value:
        return TREND
    return MEAN_REVERSION


def allows(setup_key: str, model: Model) -> bool:
    """True when ``setup_key`` belongs to ``model``."""
    return setup_model(setup_key) == model


__all__ = [
    "Model", "TREND", "MEAN_REVERSION", "setup_model", "select_model", "allows",
]
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_model_router.py -q -p no:cacheprovider`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add quant/decision/model_router.py tests/quant/decision/test_model_router.py
git commit -m "feat(decision): single model selector — state selects, evidence overrides"
```

### Task B3: Tag Gate-3 paths with setup keys

**Files:**
- Modify: `quant/decision/gates_edge.py:199-271`
- Test: `tests/quant/decision/test_gate3_setup_keys.py`

**Interfaces:**
- Consumes: `GateResult.setup_key` (Task B1).
- Produces: `_pass(ctx, model, reason, setup_key)` returns `GateResult(3, True, reason, setup_key=...)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/quant/decision/test_gate3_setup_keys.py
from quant.decision.gates_edge import gate_triple_a_edge
from quant.decision.context import DecisionContext
from quant.bars import Bar


def _bar():
    return Bar(time=1, open=100, high=102, low=99, close=101.5, volume=1000,
               buy_volume=600, sell_volume=400, delta=200, oi=50000, vwap=100.5)


def _ctx(**kw):
    base = dict(symbol="NIFTY", agent_direction="LONG", tick_size=0.05,
                bar=_bar(), triple_a_phase="AGGRESSION", triple_a_signal="LONG",
                allow_trend=True, cvd_slope=0.5, absorption_side="SELL_ABSORBED",
                poc=100.0, val=98.0, vah=102.0, leg_lvn=101.5)
    base.update(kw)
    return DecisionContext(**{k: v for k, v in base.items()
                             if k in DecisionContext.__dataclass_fields__})


def test_triple_a_aggression_tags_setup_key():
    r = gate_triple_a_edge(_ctx())
    assert r.passed and r.setup_key == "TRIPLE_A"
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_gate3_setup_keys.py -q -p no:cacheprovider`
Expected: FAIL — `setup_key == ""`.

- [ ] **Step 3: Change `_pass` and every call site**

Update `_pass` to accept and forward the key, then pass the key at each `_pass(...)`:
`TRIPLE_A` (AGGRESSION), `SECOND_DRIVE` (drive), `LVN_SNIPER` (both LVN branches), `INITIATIVE` (both breakout branches), `SQUEEZE` (both retest branches), `VA_FADE` (both fade branches). The evidence path passes `str(ev.setup_type)` as the key (normalize `SECOND_DRIVE`/`TRIPLE_A`/`LVN_SNIPER`/`VA_FADE`).

- [ ] **Step 4: Test**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_gate3_setup_keys.py tests/quant/decision/test_gate_triple_a_edge.py tests/quant/decision/test_phase3_pipeline.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quant/decision/gates_edge.py tests/quant/decision/test_gate3_setup_keys.py
git commit -m "feat(gates): tag each Gate-3 path with its setup key for the model router"
```

### Task B4: Enforce the router once in `DecisionService`

**Files:**
- Modify: `quant/decision/decision_service.py:29-39,110-159`
- Test: `tests/quant/decision/test_model_router_enforcement.py`

**Interfaces:**
- Consumes: `select_model`, `allows`, `setup_model` (Task B2), `GateResult.setup_key` (B1/B3).
- Removes: the half-built `_TREND_SETUPS`/`_REVERSION_SETUPS`/`_LABEL_TO_SETUP_KEY` router and the `analyzer_setup_type` gate at `:110-118,126-131,156-159`.

- [ ] **Step 1: Write the failing test**

```python
# tests/quant/decision/test_model_router_enforcement.py
"""DecisionService blocks a setup whose model disagrees with the active model."""
from unittest.mock import patch
from quant.contracts.enums import MarketState
from quant.decision.decision_service import DecisionService
from quant.decision.context import DecisionContext
from quant.decision.result import GateResult
from quant.bars import Bar


def _ctx(**kw):
    bar = Bar(time=1, open=100, high=102, low=99, close=101.5, volume=1000,
              buy_volume=600, sell_volume=400, delta=200, oi=50000, vwap=100.5)
    base = dict(symbol="NIFTY", bar=bar, agent_direction="LONG",
                market_state=MarketState.BALANCED, cvd_slope=0.5)
    base.update(kw)
    return DecisionContext(**{k: v for k, v in base.items()
                             if k in DecisionContext.__dataclass_fields__})


def _gates_with(setup_key):
    passed = [GateResult(1, True), GateResult(2, True),
              GateResult(3, True, "edge", setup_key=setup_key), GateResult(4, True)]
    return patch("quant.decision.decision_service.GatePipeline.evaluate",
                 return_value=passed)


def test_trend_setup_blocked_in_balanced_market():
    """BALANCED -> MEAN_REVERSION; a TRIPLE_A approval must not become a trade."""
    with _gates_with("TRIPLE_A"):
        d = DecisionService(min_rr=1.5).evaluate(_ctx(market_state=MarketState.BALANCED))
    assert not (d.approved and d.model_label == "Triple-A")


def test_trend_setup_allowed_in_imbalanced_market():
    with _gates_with("TRIPLE_A"):
        d = DecisionService(min_rr=1.5).evaluate(_ctx(market_state=MarketState.IMBALANCED))
    assert d.approved is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_model_router_enforcement.py -q -p no:cacheprovider`
Expected: `test_trend_setup_blocked_in_balanced_market` FAILS (current code approves it).

- [ ] **Step 3: Replace the router region**

In `quant/decision/decision_service.py`:
1. Delete `_TREND_SETUPS`, `_REVERSION_SETUPS`, `_LABEL_TO_SETUP_KEY` (`:29-39`).
2. Delete the `analyzer_setup_type` block (`:110-118`) and its two usages (`:126-131`, `:156-159`).
3. After `results = tuple(...GatePipeline().evaluate(...))`, compute the passed setup key from Gate 3:
```python
        from quant.decision.model_router import allows, select_model
        active_model = select_model(ctx)
        gate3_key = next(
            (r.setup_key for r in results if r.gate == 3 and r.passed),
            "",
        )
```
4. Where the trend signal is built (`:124-141`), gate it:
```python
        if all(r.passed for r in results):
            if gate3_key and not allows(gate3_key, active_model):
                _log.info(
                    "Model router blocked %s (active model=%s, state=%s)",
                    gate3_key, active_model, getattr(ctx.market_state, "value", ctx.market_state),
                )
                results = results  # fall through to the reversion fallback
            else:
                label = _label_from_gate_results(results)
                sig, drop_why = SignalBuilder().build_or_reason(ctx, results, model_label=label)
                if sig is not None:
                    return QuantDecision(True, sig, label, "", results, model_label=label)
                return QuantDecision(
                    False, None, "GATE_REJECTED", "", results,
                    blocked + (f"SIGNAL_BUILDER: {drop_why}",),
                )
```
5. Before the VA-fade fallback (`:162`), gate it on the active model:
```python
        if not allows("VA_FADE", active_model):
            return QuantDecision(False, None, "NO_EDGE", "", tuple(results), blocked)
```

- [ ] **Step 4: Test the service + router suites**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/ -q --timeout=120 -p no:cacheprovider`
Expected: PASS. Some pre-existing gate tests may need their fixtures to set `market_state=IMBALANCED` for trend setups — update them in this task (list each change in the commit body).

- [ ] **Step 5: Commit**

```bash
git add quant/decision/decision_service.py tests/quant/decision/
git commit -m "feat(decision): enforce model router in DecisionService — one place maps state+evidence to TREND/MEAN_REVERSION"
```

---

# WS-C: Mean-Reversion Correctness (failed auction → reclaim → POC)

### Task C1: Rewrite `detect_va_fade` around reclaim semantics

**Files:**
- Modify: `quant/decision/va_fade.py`
- Test: `tests/quant/decision/test_va_fade_reclaim_semantics.py`

**Interfaces:**
- Produces: `detect_va_fade(ctx) -> VAFadeSignal | None` — returns None unless the probe beyond VA was **rejected and price closed back inside** the VA, in the fade direction, with flow agreement; `tp` is always `ctx.poc`.
- Consumes: `ctx.session_extreme_low/high`, `ctx.poc/vah/val`, `ctx.cvd_slope`, `ctx.vars_result`, `ctx.setup_evidence` (when it is a complete `VA_FADE`).

**Semantics (TradeZella / Fabio Model 2):** probe beyond VAH/VAL → failed acceptance (close back inside VA) → enter fade toward POC.

- [ ] **Step 1: Write the failing test**

```python
# tests/quant/decision/test_va_fade_reclaim_semantics.py
from quant.decision.va_fade import detect_va_fade
from quant.decision.context import DecisionContext
from quant.bars import Bar


def _bar(o, h, l, c):
    return Bar(time=1, open=o, high=h, low=l, close=c, volume=1000,
               buy_volume=500, sell_volume=500, delta=0, oi=50000, vwap=(h+l+c)/3)


def _ctx(**kw):
    base = dict(symbol="TEST", poc=100.0, vah=102.0, val=98.0, tick_size=0.05)
    base.update(kw)
    return DecisionContext(**{k: v for k, v in base.items()
                             if k in DecisionContext.__dataclass_fields__})


def test_probe_below_val_reclaim_long_targets_poc():
    # low probed 96.5 (outside), close 98.6 back INSIDE VA, buyers in control
    ctx = _ctx(bar=_bar(98.8, 99.0, 96.5, 98.6), cvd_slope=0.7,
               session_extreme_low=96.5)
    sig = detect_va_fade(ctx)
    assert sig is not None and sig.direction == "LONG" and sig.tp == 100.0


def test_probe_above_vah_reclaim_short_targets_poc():
    ctx = _ctx(bar=_bar(101.2, 103.5, 101.0, 101.4), cvd_slope=-0.7,
               session_extreme_high=103.5)
    sig = detect_va_fade(ctx)
    assert sig is not None and sig.direction == "SHORT" and sig.tp == 100.0


def test_still_outside_va_is_not_a_fade():
    """Price below VAL and NOT reclaimed -> no fade (this is a trend, not a fade)."""
    ctx = _ctx(bar=_bar(97.5, 97.8, 96.0, 96.4), cvd_slope=0.7,
               session_extreme_low=96.0)
    assert detect_va_fade(ctx) is None


def test_reclaim_without_flow_agreement_is_not_a_fade():
    ctx = _ctx(bar=_bar(98.8, 99.0, 96.5, 98.6), cvd_slope=-0.7,
               session_extreme_low=96.5)
    assert detect_va_fade(ctx) is None


def test_stop_beyond_probe_extreme():
    ctx = _ctx(bar=_bar(98.8, 99.0, 96.5, 98.6), cvd_slope=0.7,
               session_extreme_low=96.5)
    sig = detect_va_fade(ctx)
    assert sig.sl < 96.5
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_va_fade_reclaim_semantics.py -q -p no:cacheprovider`
Expected: `test_still_outside_va_is_not_a_fade` and `test_reclaim_without_flow_agreement_is_not_a_fade` FAIL (current code fires while outside VA).

- [ ] **Step 3: Rewrite the detection core**

Keep `VAFadeSignal` and the stop/target math. Replace the zone test with a reclaim test:

```python
    close = float(ctx.bar.close)
    cvd = float(ctx.cvd_slope)
    inside_va = val <= close <= vah

    # complete VA_FADE evidence wins when the analyzer already certified it
    ev = getattr(ctx, "setup_evidence", None)
    ev_ok_long = bool(ev is not None and getattr(ev, "setup_type", "") == "VA_FADE"
                      and getattr(ev, "direction", "") == "LONG"
                      and getattr(ev, "is_complete", lambda: False)())
    ev_ok_short = bool(ev is not None and getattr(ev, "setup_type", "") == "VA_FADE"
                       and getattr(ev, "direction", "") == "SHORT"
                       and getattr(ev, "is_complete", lambda: False)())

    probe_low = getattr(ctx, "session_extreme_low", 0.0) or 0.0
    probe_high = getattr(ctx, "session_extreme_high", 0.0) or 0.0
    failed_below = (probe_low > 0 and probe_low < val) or ev_ok_long
    failed_above = (probe_high > 0 and probe_high > vah) or ev_ok_short

    # LONG: a probe below VAL was rejected and price is back inside with buyers
    if inside_va and close < poc and failed_below and cvd > 0:
        ...  # entry=close, sl = min(entry - step, (probe_low or bar.low) - step), tp = poc
    # SHORT: a probe above VAH was rejected and price is back inside with sellers
    if inside_va and close > poc and failed_above and cvd < 0:
        ...  # entry=close, sl = max(entry + step, (probe_high or bar.high) + step), tp = poc
    return None
```

Preserve the VARS-condition branch only when the reclaim test also holds (`vars_bull and inside_va and close < poc`).

- [ ] **Step 4: Update the tests that pinned the wrong behavior**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_va_fade.py tests/quant/decision/test_va_fade_risk.py tests/quant/decision/test_va_fade_stop_extreme.py -q -p no:cacheprovider`
Expected: failures where fixtures still close OUTSIDE the VA. Update each fixture's bar to close back inside (and set `session_extreme_low/high`), listing every changed fixture in the commit body. Delete any assertion that encoded the old "enter while outside VA" behavior.

- [ ] **Step 5: Commit**

```bash
git add quant/decision/va_fade.py tests/quant/decision/
git commit -m "fix(amt): VA fade requires failed auction + reclaim inside VA (Fabio Model 2), target POC"
```

### Task C2: MEAN_REVERSION trades exit at POC

**Files:**
- Modify: `quant/decision/signal_builder.py` (VA_FADE target already POC at `:197-208`)
- Test: `tests/quant/decision/test_mean_reversion_poc_exit.py`

- [ ] **Step 1: Write the test**

```python
# tests/quant/decision/test_mean_reversion_poc_exit.py
"""A MEAN_REVERSION signal's TP must equal the POC, not an R-multiple."""
from quant.decision.signal_builder import SignalBuilder
from quant.decision.context import DecisionContext
from quant.decision.result import GateResult
from quant.decision.setup_state import SetupEvidence
from quant.bars import Bar


def test_va_fade_signal_tp_is_poc():
    bar = Bar(time=1, open=100, high=101, low=99, close=100.2, volume=1000,
              buy_volume=500, sell_volume=500, delta=0, oi=50000, vwap=100)
    ev = SetupEvidence(setup_type="VA_FADE", direction="SHORT", level=101.5,
                       rejection=True, acceptance=False, cvd_agrees=True)
    ctx = DecisionContext(symbol="NIFTY", bar=bar, agent_direction="SHORT",
                          poc=100.0, vah=101.0, val=99.0, tick_size=0.05,
                          setup_evidence=ev, cvd_slope=-0.5)
    gates = [GateResult(1, True), GateResult(2, True),
             GateResult(3, True, "va fade", setup_key="VA_FADE"), GateResult(4, True)]
    sig, _ = SignalBuilder().build_or_reason(ctx, gates, model_label="MEAN_REVERSION")
    assert sig is not None and sig.tp == 100.0
```

- [ ] **Step 2: Run to verify it fails or passes**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_mean_reversion_poc_exit.py -q -p no:cacheprovider`
Expected: PASS if `:197-208` already anchors VA_FADE at POC. If it FAILS, update the VA_FADE branch in `signal_builder.py` so `tp = ctx.poc`.

- [ ] **Step 3: Commit** (skip if already passing — record that in the commit body)

```bash
git add tests/quant/decision/test_mean_reversion_poc_exit.py quant/decision/signal_builder.py
git commit -m "test(amt): pin MEAN_REVERSION target to POC (100% exit at balance)"
```

---

# WS-E: Execution Truth & Docs

### Task E1: Batch-trade persistence smoke (no dead-path assumptions)

**Files:**
- Test: `tests/quant/runtime/test_single_authority.py`

- [ ] **Step 1: Verify the engine no longer constructs an unused DecisionService path twice**

Run: `grep -n "_decision_service" quant/runtime.py`
Expected: constructed once at `:494`, passed into `build_strategy`. If it is constructed but never reachable, delete the construction and let `build_strategy` own it.

- [ ] **Step 2: Add the assertion**

```python
def test_decision_service_is_wired_into_the_authority(monkeypatch):
    from unittest.mock import MagicMock
    from quant.runtime import QuantEngine
    monkeypatch.delenv("TIMESFM_END_TO_END", raising=False)
    engine = QuantEngine(gateway=MagicMock(), symbol="CRUDEOIL")
    assert engine._strategy._decision_service is engine._decision_service
```

- [ ] **Step 3: Test + commit**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/runtime/test_single_authority.py -q -p no:cacheprovider`
```bash
git add quant/runtime.py tests/quant/runtime/test_single_authority.py
git commit -m "test(runtime): one DecisionService instance, wired into the entry authority"
```

### Task E2: Update the Goodbye-Gate-3 architecture docs

**Files:**
- Modify: `docs/amt/fabio_decision_pipeline.md` (Gate-3 section), `docs/architecture/ARCHITECTURE_AND_FLOWS.md:282,319`

- [ ] **Step 1: Replace the Gate-3 section** with the two-model contract: state → model, evidence override, `GateResult.setup_key`, enforcement in `DecisionService`, and the VA-fade reclaim entry.

- [ ] **Step 2: Fix the flow diagram** in `ARCHITECTURE_AND_FLOWS.md` to show one entry authority (`AmtScalpingStrategy`), TimesFM as forecast provider only, and `detect_va_fade` as a MEAN_REVERSION path (not a "tier-2 fallback").

- [ ] **Step 3: Commit**

```bash
git add docs/amt/fabio_decision_pipeline.md docs/architecture/ARCHITECTURE_AND_FLOWS.md
git commit -m "docs(amt): single entry authority + two-model contract"
```

---

# WS-F: Verification & Certification

### Task F1: Full regression + determinism

- [ ] **Step 1: Baseline diff vs ledger**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/ -q --timeout=180 -p no:cacheprovider`
Expected: fail count identical-or-better than `docs/reviews/2026-09-16-test-integrity-ledger.md`. Compare and list every delta.

- [ ] **Step 2: Determinism**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/determinism/ tests/quant/runtime/golden/ -q --timeout=120 -p no:cacheprovider`
Expected: PASS (goldens updated only if the change truly alters the decision, with justification).

### Task F2: Re-golden certification traces with a human-readable diff

- [ ] **Step 1: Produce the before/after entry diff**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/certification/ -q --timeout=120 -p no:cacheprovider`
For each trace that moved, capture: entries taken/dropped, and the reason (state → model change, VA reclaim tightening, forecast provider). Attach as `docs/reviews/2026-09-17-certification-diff.md`.

- [ ] **Step 2: Only then update goldens**

```bash
git add tests/quant/certification/golden/ docs/reviews/2026-09-17-certification-diff.md
git commit -m "chore(cert): regolden traces after single-authority cutover — diff attached"
```

### Task F3: Final metrics + prune proof

- [ ] **Step 1: Prove the prune**

```bash
git diff --stat 7b3dfecc..HEAD
echo "entry authorities:"; grep -rn "should_enter" quant/strategies/ quant/strategy.py | grep -v __pycache__
```
Expected: exactly one `should_enter` implementation (`amt_scalping.py`).

- [ ] **Step 2: Write the summary** to `docs/reviews/2026-09-17-single-authority-convergence-report.md`: lines removed, paths deleted, models enforced, sizing status, remaining risks.

- [ ] **Step 3: Commit**

```bash
git add docs/reviews/2026-09-17-single-authority-convergence-report.md
git commit -m "docs: single-authority convergence summary report"
```

---

## Self-Review

**Spec coverage:**
- D1 single authority → WS-A (A1-A5) + E1. ✓
- D2 state-selects/evidence-overrides in one place → WS-B (B1-B4). ✓
- D3 full prune → WS-D (D1-D5). ✓
- D4 sizing already fixed, remove dead param → D4. ✓
- D5 forecast kept as provider → A3. ✓
- Correctness of Mean Reversion (TradeZella playbook) → WS-C (C1-C2). ✓

**Placeholder scan:** no TBD/TODO steps; every code-changing step shows code or an exact deletion boundary. Two tasks (A5 Step 3, C1 Step 4) are explicitly conditional on the current file contents and tell the implementer the exact grep to run first.

**Type consistency:** `GateResult.setup_key` (B1) is produced in B3 and consumed in B4; `select_model`/`allows`/`setup_model` are defined in B2 and used in B4; `build_strategy` defined in A1, used in A2; `fresh_forecast(advisor, strategy, *, symbol, bar_index)` defined in A3, wired in A3.

**Known risks (carry into WS-F report):**
- WS-B changes entries materially → certification traces move; this is intended (D2) but must be diffed, never silently re-golded.
- Deleting `TimesFMTradingStrategy` (A5) touches ~10 test files and 2 scripts; if any script is a live runbook dependency, keep the script but fail it loudly instead of deleting.
- The `SessionRisk` default `base_risk_pct=0.05` triggers the aggressive-mode branch; D4 removes a dead param but must not perturb that branch — re-run `test_risk_sizing_derivatives.py` specifically.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-09-17-amt-single-authority-convergence.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks; here the *workstreams* are the natural parallel unit (cut one worktree per WS, dispatch WS-D/WS-A/WS-B/WS-C concurrently).

**2. Inline Execution** — batch execution in one session with checkpoints.

**Which approach?**
