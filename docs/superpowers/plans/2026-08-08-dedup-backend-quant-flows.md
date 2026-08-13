# Deduplicate backend ↔ quant Flows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Eliminate duplicated domain-logic flows that exist as independent reimplementations in both `backend/` and `quant/`, so backend delegates to quant (the canonical decision brain) instead of cloning it.

**Architecture:** The repo's own docs (`docs/superpowers/specs/2026-08-07-quant-brain-backend-design.md`, `docs/AMT_UNIFICATION.md`) are explicit: **quant is the canonical home of domain logic; backend is a thin transport shell**. Git history confirms the migration is underway (`3cf8341` deleted the legacy AMT/gate/entry/LLM-handler pipeline). Every merge in this plan follows that direction — backend imports quant, never vice versa. The graph analysis surfaced 6 real actions: 1 true merge (`amt_result_to_dto`), 4 zombie/stale deletions (`trade_aggregate.py`, `market_state.py`, `volume_profile_models.py`, `test_amt_handler.py`), and 1 helper consolidation (`_to_float`).

**Tech Stack:** Python 3.11+ (type hints), pytest (backend config in `backend/pytest.ini`, tests run with `PYTHONPATH=.`), FastAPI backend, pure-Python quant engine.

## Global Constraints

- **quant purity is a hard constraint:** `quant.*` may NEVER import `app.*`. All merges must keep quant free of backend imports. Direction is always backend → quant.
- **LLM adapters are NOT to be merged:** `GGUFInferenceAdapter` and `MLXInferenceAdapter` are two transports behind one port (`ILLMInference`) — keep both. Selection is by model path in `backend/app/application/di/composition_root.py:167-176`.
- **`JournalEntry` and `ExchangeConfig` are NOT duplicates:** name collisions only, different shapes/roles — do not merge them.
- **`LiveGateway` and `database.py` are adapters over quant contracts, not duplicates:** keep them; `LiveGateway` dies only with the `:8765` reference server retirement.
- **`backend/scripts/dataset_render.py:33` `_to_float` variant (strips `+`, defaults to `None`) has different semantics — do not touch it.**
- Backend tests run from `backend/` dir: `cd backend && PYTHONPATH=. python3 -m pytest <path>`. Quant tests run from repo root: `PYTHONPATH=. python3 -m pytest <path>`.
- Run the full relevant suites after each task before committing. Never commit failing tests.
- No `TBD`/`TODO`/placeholder content. Every task below is complete and runnable.
- Commit after each task with a `refactor:` or `chore:` prefix matching repo style (e.g. `refactor: delegate amt DTO to quant.amt.dto`).

---

### Task 1: Merge `amt_result_to_dto` — backend delegates to `quant.amt.dto`

**Files:**
- Modify: `backend/app/infrastructure/serialization/schemas.py:493-602` (delete backend copy)
- Modify: `backend/app/api/routers/analysis.py:10`
- Modify: `backend/tests/unit/infrastructure/test_schemas_serialization.py`
- Modify: `backend/tests/integration/test_schemas_serialization.py`
- Modify: `backend/tests/integration/test_frontend_integration.py:137,167`

**Interfaces:**
- Consumes: `quant.amt.dto.amt_result_to_dto(r, *, llm_thinking: str = "") -> dict` — exists, output byte-identical to the backend copy on real `AMTResult` (both build the same camelCase keys; `AMTResult.signal` is deprecated and always `None`, so `signal_to_dto(None)` === quant's hardcoded `signal: None`).
- Produces: `backend/app/api/routers/analysis.py` imports `amt_result_to_dto` from `quant.amt.dto`. The backend copy in `schemas.py` is removed. Tests updated to import from `quant.amt.dto` and drop the dead `llm_json` kwarg.

- [x] **Step 1: Confirm both implementations are behaviorally identical**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/unit/infrastructure/test_schemas_serialization.py tests/integration/test_schemas_serialization.py -q --no-header`
Expected: all pass (baseline green before the change).

- [x] **Step 2: Update the router import**

In `backend/app/api/routers/analysis.py`, replace the `schemas` import of `amt_result_to_dto` with a quant import. The current import block is:

```python
from app.infrastructure.serialization.schemas import (
    amt_result_to_dto,
)
```

Replace with:

```python
from quant.amt.dto import amt_result_to_dto
```

- [x] **Step 3: Delete the backend copy from schemas.py**

In `backend/app/infrastructure/serialization/schemas.py`, delete the `amt_result_to_dto` function (the `def amt_result_to_dto(...)` block spanning lines 493-602, including its docstring). Do NOT delete `signal_to_dto` (still used by `test_schemas_serialization.py` and the DTO contract) — but verify after the merge whether it is still referenced in `schemas.py`; if the only remaining `signal_to_dto` reference was inside the deleted function, keep the function for its tests.

- [x] **Step 4: Update unit tests to import from quant and drop `llm_json`**

In `backend/tests/unit/infrastructure/test_schemas_serialization.py`:
- Change the import at line ~15 from `app.infrastructure.serialization.schemas import (amt_result_to_dto, ...)` to `from quant.amt.dto import amt_result_to_dto`.
- Remove the `llm_json="{}"` kwarg from the 3 call sites at lines ~29, ~68, ~108 so calls are `amt_result_to_dto(result, llm_thinking="")`.

- [x] **Step 5: Update integration tests to import from quant**

In `backend/tests/integration/test_schemas_serialization.py`:
- Change line ~20 import of `amt_result_to_dto` to `from quant.amt.dto import amt_result_to_dto`.
- Keep `stats_to_dto`, `footprint_to_dto`, `signal_to_dto`, `portfolio_to_dto`, `position_to_dto` importing from `app.infrastructure.serialization.schemas`.

In `backend/tests/integration/test_frontend_integration.py:137`, change:
```python
from app.infrastructure.serialization.schemas import amt_result_to_dto
```
to:
```python
from quant.amt.dto import amt_result_to_dto
```

- [x] **Step 6: Run the tests to verify they pass**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/unit/infrastructure/test_schemas_serialization.py tests/integration/test_schemas_serialization.py tests/integration/test_frontend_integration.py -q --no-header`
Expected: all pass. If an assertion fails on `signal` shape, the DTO contract changed — do not paper over it; report back.

- [x] **Step 7: Run the broader backend unit+integration suite**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/unit tests/integration -q --no-header`
Expected: green. If `analysis.py` router tests or websocket tests fail, verify the quant import path resolves in the backend runtime.

- [x] **Step 8: Commit**

```bash
git add backend/app/infrastructure/serialization/schemas.py backend/app/api/routers/analysis.py backend/tests/unit/infrastructure/test_schemas_serialization.py backend/tests/integration/test_schemas_serialization.py backend/tests/integration/test_frontend_integration.py
git commit -m "refactor: delegate AMT DTO serialization to quant.amt.dto"
```

---

### Task 2: Delete zombie `backend/app/domain/ops/trade_aggregate.py`

**Files:**
- Delete: `backend/app/domain/ops/trade_aggregate.py` (770 lines)
- Delete: `backend/tests/unit/domain/test_invariants.py`
- Delete: `backend/tests/unit/domain/test_trade_aggregate.py`

**Interfaces:**
- Consumes: nothing — verified zero production importers. Only the two deleted test files import `app.domain.ops.trade_aggregate`.
- Produces: nothing. The of-record entities live in `quant/contracts/entities.py` (`Position`), `quant/execution/order.py` (`Fill`), `quant/decision/trade_thesis.py` (`TradeThesis`). Backend already imports `quant.contracts.entities.Position` in `dhan_broker_adapter.py:31`, `paper_broker.py:31`, `trading_query_service.py:6`.

- [x] **Step 1: Verify zero production importers (safety gate)**

Run: `cd /Users/apple/Documents/v5-of-glassytrade-ai && grep -rl "app.domain.ops.trade_aggregate\|from app.domain.ops import trade_aggregate" --include="*.py" . | grep -v __pycache__`
Expected: only the two test files. If any other file appears, STOP and report — the plan's premise is broken.

- [x] **Step 2: Delete the module and its two test files**

```bash
git rm backend/app/domain/ops/trade_aggregate.py backend/tests/unit/domain/test_invariants.py backend/tests/unit/domain/test_trade_aggregate.py
```

- [x] **Step 3: Verify no dangling references anywhere**

Run: `cd /Users/apple/Documents/v5-of-glassytrade-ai && grep -rn "trade_aggregate\|TradeThesis\|EntrySignal\|TradeStatus" --include="*.py" backend/app | grep -v __pycache__`
Expected: no output (only the deleted module referenced these). If `TradeThesis`/`EntrySignal` appear in any live backend file, STOP and report — quant is the source, so the reference must be re-pointed to `quant.decision.trade_thesis`.

- [x] **Step 4: Run backend suites to confirm nothing broke**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/unit tests/integration -q --no-header`
Expected: green (the 37 deleted tests are gone; nothing else referenced the module).

- [x] **Step 5: Commit**

```bash
git commit -m "chore: delete zombie trade_aggregate.py (quant.contracts is of record)"
```

---

### Task 3: Delete zero-importer `backend/app/domain/models/market_state.py`

**Files:**
- Delete: `backend/app/domain/models/market_state.py` (172 lines)

**Interfaces:**
- Consumes: nothing — verified zero references anywhere (the only `domain.models` import in the codebase is `composition_root.py:305` `from app.domain.models.exchange import Exchange`).
- Produces: nothing. Live equivalents are `quant/vwap.py` (`VWAPState`, `VWAPBuilder`), `quant/volume_profile.py` and `quant/amt/profile/volume_profile.py` (`IncrementalVolumeProfile`).

- [x] **Step 1: Verify zero references (safety gate)**

Run: `cd /Users/apple/Documents/v5-of-glassytrade-ai && grep -rn "app.domain.models.market_state\|domain.models import market_state" --include="*.py" . | grep -v __pycache__`
Expected: no output.

- [x] **Step 2: Delete the module**

```bash
git rm backend/app/domain/models/market_state.py
```

- [x] **Step 3: Run backend suites**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/unit tests/integration -q --no-header`
Expected: green.

- [x] **Step 4: Commit**

```bash
git commit -m "chore: delete zero-importer market_state.py (quant/vwap is of record)"
```

---

### Task 4: Delete zero-importer `quant/contracts/volume_profile_models.py`

**Files:**
- Delete: `quant/contracts/volume_profile_models.py` (57 lines)

**Interfaces:**
- Consumes: nothing — verified zero importers. The live volume-profile code is `quant/amt/profile/volume_profile.py` (`IncrementalVolumeProfile`), used by `quant/amt/analyzer.py:169` and `quant/runtime.py:22,287`.
- Produces: nothing.

- [x] **Step 1: Verify zero references (safety gate)**

Run: `cd /Users/apple/Documents/v5-of-glassytrade-ai && grep -rn "volume_profile_models" --include="*.py" . | grep -v __pycache__`
Expected: no output.

- [x] **Step 2: Delete the module**

```bash
git rm quant/contracts/volume_profile_models.py
```

- [x] **Step 3: Run quant + backend suites**

Run: `PYTHONPATH=. python3 -m pytest tests/quant -q --no-header && cd backend && PYTHONPATH=. python3 -m pytest tests/unit -q --no-header`
Expected: both green.

- [x] **Step 4: Commit**

```bash
git commit -m "chore: delete zero-importer volume_profile_models.py"
```

---

### Task 5: Delete stale `backend/tests/unit/application/test_amt_handler.py`

**Files:**
- Delete: `backend/tests/unit/application/test_amt_handler.py` (623 lines)

**Interfaces:**
- Consumes: nothing — it patches `app.application.handlers.amt_handler`, a module deleted in `3cf8341` (the `handlers/` dir now contains only `__pycache__`). pytest already auto-skips it (`collected 0 items / 1 skipped`).

- [x] **Step 1: Confirm the module it tests is gone**

Run: `ls backend/app/application/handlers/*.py`
Expected: no match (dir contains only `__pycache__`).

- [x] **Step 2: Delete the stale test**

```bash
git rm backend/tests/unit/application/test_amt_handler.py
```

- [x] **Step 3: Run backend unit suite**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/unit -q --no-header`
Expected: green (previously-skipped test now removed).

- [x] **Step 4: Commit**

```bash
git commit -m "chore: delete stale amt_handler test (module deleted in 3cf8341)"
```

---

### Task 6: Consolidate `_to_float` into `quant/contracts/numeric.py`

**Files:**
- Create: `quant/contracts/numeric.py`
- Modify: `backend/app/application/services/trade_journal.py:112`
- Modify: `backend/app/infrastructure/adapters/dhan_broker_adapter.py:68`
- Modify: `quant/decision/trade_thesis.py:21`
- Modify: `quant/decision/gates/confirmation_bundle.py:26`
- Modify: `quant/decision/gates/grading.py:84`
- Modify: `quant/decision/gates/three_align.py:115`
- Test: `tests/quant/contracts/test_numeric.py` (create)

**Interfaces:**
- Produces: `quant/contracts/numeric.py`:
  ```python
  from __future__ import annotations
  from typing import Any

  def to_float(value: Any, default: float | None = 0.0) -> float | None:
      """Coerce a numeric (float/int/str/Decimal) to float, else `default`."""
      if value is None:
          return default
      try:
          return float(value)
      except (TypeError, ValueError):
          return default
  ```
  Handles all 6 existing call sites (three_align.py currently uses `default=None`; the unified helper accepts it).
- Consumes: nothing external.

- [x] **Step 1: Write the failing test**

Create `tests/quant/contracts/test_numeric.py`:
```python
from decimal import Decimal

from quant.contracts.numeric import to_float


def test_to_float_coerces_ints_floats_and_strings():
    assert to_float(1) == 1.0
    assert to_float(2.5) == 2.5
    assert to_float("3.75") == 3.75
    assert to_float(Decimal("4.5")) == 4.5


def test_to_float_returns_default_on_none_and_bad_values():
    assert to_float(None) == 0.0
    assert to_float("abc") == 0.0
    assert to_float(object()) == 0.0


def test_to_float_honors_custom_default():
    assert to_float(None, default=None) is None
    assert to_float("n/a", default=None) is None
```

- [x] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. python3 -m pytest tests/quant/contracts/test_numeric.py -q --no-header`
Expected: FAIL with `ModuleNotFoundError: No module named 'quant.contracts.numeric'`.

- [x] **Step 3: Create `quant/contracts/numeric.py`**

Write the module exactly as defined in **Interfaces**.

- [x] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. python3 -m pytest tests/quant/contracts/test_numeric.py -q --no-header`
Expected: PASS.

- [x] **Step 5: Replace the 6 copies with imports**

For each of the 6 files, delete the local `def _to_float(...)` and add an import of `to_float`:

- `quant/decision/trade_thesis.py:21` — delete `_to_float`, add `from quant.contracts.numeric import to_float`, rename its call sites `_to_float(` → `to_float(`.
- `quant/decision/gates/confirmation_bundle.py:26` — same pattern.
- `quant/decision/gates/grading.py:84` — same pattern.
- `quant/decision/gates/three_align.py:115` — same pattern; call sites already pass `default=None`, which the helper supports.
- `backend/app/infrastructure/adapters/dhan_broker_adapter.py:68` — delete module-level `_to_float`, add `from quant.contracts.numeric import to_float`, rename call sites.
- `backend/app/application/services/trade_journal.py:112` — this is a **method** `_to_float` on the `TradeJournal` class. Delete the method body, and either (a) replace each `self._to_float(...)` call with a module-level `to_float(...)` import, or (b) keep the method as a one-line delegate `return to_float(value, default=default)`. Prefer (a) for true dedup; keep (b) only if many call sites make (a) risky.

Do NOT touch `backend/scripts/dataset_render.py:33` (different semantics — strips `+`, defaults to `None`) or `quant/runtime.py:359` `_to_float_ohlc` (different function).

- [x] **Step 6: Run quant + backend suites to verify**

Run: `PYTHONPATH=. python3 -m pytest tests/quant -q --no-header && cd backend && PYTHONPATH=. python3 -m pytest tests/unit tests/integration -q --no-header`
Expected: both green.

- [x] **Step 7: Commit**

```bash
git add quant/contracts/numeric.py tests/quant/contracts/test_numeric.py quant/decision/trade_thesis.py quant/decision/gates/confirmation_bundle.py quant/decision/gates/grading.py quant/decision/gates/three_align.py backend/app/infrastructure/adapters/dhan_broker_adapter.py backend/app/application/services/trade_journal.py
git commit -m "refactor: consolidate _to_float into quant.contracts.numeric"
```

---

### Task 7: Final verification and summary

**Files:**
- Modify: none (verification only)

- [x] **Step 1: Full backend suite**

Run: `cd backend && PYTHONPATH=. python3 -m pytest tests/ -q --no-header`
Expected: green.

- [x] **Step 2: Full quant suite**

Run: `cd /Users/apple/Documents/v5-of-glassytrade-ai && PYTHONPATH=. python3 -m pytest tests/quant -q --no-header`
Expected: green.

- [x] **Step 3: Confirm no duplicate definitions remain**

Run: `cd /Users/apple/Documents/v5-of-glassytrade-ai && grep -rn "def _to_float" --include="*.py" . | grep -v __pycache__`
Expected: only `backend/scripts/dataset_render.py:33` (intentionally kept).

Run: `cd /Users/apple/Documents/v5-of-glassytrade-ai && grep -rn "def amt_result_to_dto" --include="*.py" . | grep -v __pycache__`
Expected: only `quant/amt/dto.py:17`.

Run: `cd /Users/apple/Documents/v5-of-glassytrade-ai && grep -rn "class TradeThesis\|class VWAPState\|class VolumeProfile" --include="*.py" backend/app | grep -v __pycache__`
Expected: no output.

- [ ] **Step 4: Rebuild the graph (optional)**

Run: `/graphify .` to refresh `graphify-out/` so the graph no longer shows the deleted duplicate pairs.
