# Phase A — Remove Dead DI Bindings (Dead Flows D1–D5, D13)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [x]`) syntax.

**Goal:** Delete the dependency-injection bindings that nothing ever resolves, eliminating dead flows D1–D5 and D13 identified in `.superpowers/audit-2026-08-08/wiring-audit.md`. These are pure removals from `composition_root.py` and `main.py` — no runtime behavior changes because nothing resolves them (verified by grep: the only `resolve()` calls are for IMarketData/IBroker/IStorage/ILLMInference/QuantCoordinator).

**Safety principle:** Phase A removes ONLY the DI registrations + their private factory/getter functions. It does NOT delete the underlying adapter/strategy/module files (that is Phase B/C). It does NOT touch `async_boundary.py` (used by 6 live files — that merge is Phase F). It does NOT touch the metrics/alerts flows (Phase D).

**Verified facts (coordinator pre-check, 2026-08-08):**
- `IProbabilityInference`, `IDeltaProfile`, `IExchangeStrategy`, `GatePipeline`(legacy), `GenerativeAIService`, and builtin `list` are NEVER `resolve()`d anywhere in `backend/app` (grep over all `resolve(` confirmed).
- D1 is a latent crash: `_create_gate_pipeline` calls `GatePipeline(config=…, market_data=…, storage=…, llm=…, probability=…)` but `quant/decision/gates/legacy_gate_pipeline.py` has NO `__init__` — resolving it would raise `TypeError`. (This is the legacy twin; the live path is `quant/decision/pipeline.GatePipeline`.)
- The ONLY test conflict: `backend/tests/unit/domain/test_exchange_abstraction.py::test_di_container_wiring` resolves `IExchangeStrategy` from `compose_container`. It must be updated to assert the port is NOT registered (or removed).
- Baseline: `cd backend && ../.venv/bin/python3 -m pytest tests/unit/domain/test_exchange_abstraction.py tests/unit/application/test_di_container.py -q --no-header` → 50 passed.

## Files

- Modify: `backend/app/application/di/composition_root.py`
- Modify: `backend/app/main.py` (D13)
- Modify: `backend/tests/unit/domain/test_exchange_abstraction.py` (resolve the one test conflict)

## Global Constraints

- **quant purity is a hard constraint:** `quant.*` may NEVER import `app.*`. Phase A only deletes code in backend — quant untouched.
- **Do NOT delete module files** in this phase (adapter/strategy/module deletion is Phase B/C). Only the DI registrations, private factories, and private getters die here.
- Backend tests run from `backend/`: `cd backend && ../.venv/bin/python3 -m pytest <path> -q --no-header`.
- Never commit failing tests. Commit after the task with `refactor:` prefix.

---

### Task A1: Remove dead registrations + factories from composition_root.py

**Files:**
- Modify: `backend/app/application/di/composition_root.py`

- [x] **Step 1: Baseline the container tests**

Run: `cd backend && ../.venv/bin/python3 -m pytest tests/unit/application/test_di_container.py tests/unit/domain/test_exchange_abstraction.py -q --no-header`
Expected: green (baseline before change).

- [x] **Step 2: Delete the dead registrations (D1, D2, D3, D4, D5)**

In `compose_container()`, delete exactly these `register_singleton` blocks:
- D2 probability (`_probability_inference_port()` block, lines 64-67)
- D3 delta profile (`_delta_profile_port()` block, lines 75-78)
- D4 exchange strategy (`_exchange_strategy_port()` block, lines 80-83)
- D1 legacy gate pipeline (`_gate_pipeline()` block, lines 86-89)
- D5 generative AI service (`_generative_ai_service()` block, lines 91-94)

Do NOT delete the Configuration, IMarketData, IBroker, IStorage, ILLMInference, or QuantCoordinator registrations — those are live.

- [x] **Step 3: Delete the now-dead port getters**

Delete exactly:
- `_probability_inference_port()` (lines 123-125)
- `_delta_profile_port()` (lines 274-276)
- `_exchange_strategy_port()` (lines 279-281)
- `_gate_pipeline()` (lines 284-286)
- `_generative_ai_service()` (lines 289-291)

- [x] **Step 4: Delete the now-dead factory functions**

Delete exactly:
- `_create_probability_adapter()` (lines 189-204)
- `_create_delta_profile_adapter()` (lines 298-300)
- `_create_exchange_strategy()` (lines 303-317)
- `_create_gate_pipeline()` (lines 320-333)
- `_create_generative_ai_service()` (lines 336-341)

- [x] **Step 5: Verify no dangling references remain in composition_root.py**

Run: `cd /Users/apple/Documents/v5-of-glassytrade-ai && grep -n "gate_pipeline\|probability\|delta_profile\|exchange_strategy\|generative_ai\|IProbabilityInference\|IDeltaProfile\|IExchangeStrategy" backend/app/application/di/composition_root.py`
Expected: no output. Also confirm `quant/contracts/ports/__init__.py` re-exports remain untouched (they are referenced elsewhere / by tests).

- [x] **Step 6: Verify `Exchange`/`ExchangeConfig` still needed elsewhere**

`_create_exchange_strategy` imported `app.domain.models.exchange.Exchange` and `quant.contracts.exchange_config.ExchangeConfig`. After deletion, confirm neither becomes orphaned in a way that breaks imports:
Run: `cd /Users/apple/Documents/v5-of-glassytrade-ai && grep -rn "domain.models.exchange\|exchange_config" --include="*.py" backend/app quant | grep -v __pycache__ | grep -v composition_root`
Expected: at least one live importer remains (e.g. `composition_root.py:305` was the exchange import; `quant/contracts/exchange_config.py` is self-contained). If `app/domain/models/exchange.py` becomes orphaned, that's fine for Phase A (it stays; Phase B audits deletions) — just report it.

- [x] **Step 7: Run the container + exchange test suites**

Run: `cd backend && ../.venv/bin/python3 -m pytest tests/unit/application/test_di_container.py -q --no-header && ../.venv/bin/python3 -m pytest tests/unit/domain/test_exchange_abstraction.py -q --no-header`
Expected: `test_di_container.py` green; `test_exchange_abstraction.py` will now FAIL on `test_di_container_wiring` (it resolves the removed IExchangeStrategy). This is expected — Task A3 fixes the test.

- [x] **Step 8: Commit**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
git add backend/app/application/di/composition_root.py
git commit -m "refactor: remove dead DI bindings (prob/delta/exchange/gate/genai)"
```

---

### Task A2: Remove dead `list` singleton registration (D13)

**Files:**
- Modify: `backend/app/main.py`

- [x] **Step 1: Delete the dead registration**

In `main.py` lifespan, the `option_scanner` block line ~197 does `container.register_singleton(list, lambda c: selected_symbols)`. This registers the builtin `list` type which nothing ever resolves. Delete JUST that one line. Keep `app.state.active_symbols = selected_symbols` (that IS live — consumed by coordinator + dependencies).

- [x] **Step 2: Verify no code resolves `list` from container**

Run: `cd /Users/apple/Documents/v5-of-glassytrade-ai && grep -rn "resolve(list)\|resolve(\s*list\b" --include="*.py" backend/app | grep -v __pycache__`
Expected: no output.

- [x] **Step 3: Commit**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
git add backend/app/main.py
git commit -m "refactor: remove dead list singleton registration (D13)"
```

---

### Task A3: Fix the one affected test

**Files:**
- Modify: `backend/tests/unit/domain/test_exchange_abstraction.py`

- [x] **Step 1: Update `test_di_container_wiring`**

The test currently does `container.resolve(IExchangeStrategy)` and asserts not None. Since the binding is deliberately removed, change it to assert the port is NOT registered:
```python
def test_di_container_wiring(self):
    """DIContainer should NOT register the dead exchange-strategy port."""
    from app.application.di.composition_root import compose_container
    from app.config import settings

    mode = settings.get_mode_config()
    config = mode.system_config if mode is not None else None
    container = compose_container(config)

    from quant.contracts.ports import IExchangeStrategy
    assert not container.has(IExchangeStrategy)
    assert container is not None
```
(Match the file's existing style — check for other `container.has(` usage or use `registered_types()`.)

- [x] **Step 2: Run the exchange test suite**

Run: `cd backend && ../.venv/bin/python3 -m pytest tests/unit/domain/test_exchange_abstraction.py -q --no-header`
Expected: green.

- [x] **Step 3: Commit**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
git add backend/tests/unit/domain/test_exchange_abstraction.py
git commit -m "refactor: test exchange-strategy port is no longer registered"
```

---

### Task A4: Final verification

- [x] **Step 1: Full backend unit+integration suite**

Run: `cd backend && ../.venv/bin/python3 -m pytest tests/unit tests/integration -q --no-header`
Expected: green except the KNOWN pre-existing failures (order-dependent `TestAIHistory::test_history_endpoint_exists`, float-precision `test_long_signal_builds_valid_rr` — both proven pre-existing; not regressions).

- [x] **Step 2: Verify no runtime wiring regressions**

Run: `cd /Users/apple/Documents/v5-of-glassytrade-ai && grep -rn "IProbabilityInference\|IDeltaProfile\|IExchangeStrategy\|legacy_gate_pipeline\|GenerativeAIService" --include="*.py" backend/app | grep -v __pycache__`
Expected: only references in `quant/contracts/ports/*` (definitions), adapter files (still exist, Phase B), and any remaining legit use. No reference should point at the deleted composition_root factory functions.

- [x] **Step 3: Verify the app still imports and boots**

Run: `cd backend && ../.venv/bin/python3 -c "from app.application.di.composition_root import compose_container; from app.config import settings; mode=settings.get_mode_config(); c=compose_container(mode.system_config if mode else None); print('container ok')"`
Expected: prints `container ok` (proves no import-time breakage from the deletions).

---

## Definition of Done

- [x] All dead DI bindings (D1–D5, D13) removed from `composition_root.py` + `main.py`
- [x] The one affected test updated to assert non-registration
- [x] Full backend suite green (except the two documented pre-existing failures)
- [x] `container ok` boot check passes
- [x] No quant files touched
