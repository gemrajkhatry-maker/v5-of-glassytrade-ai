# Refactor Telemetry + Standards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the audit's last two root causes — typed config errors (SMELL-22), vocabulary-ownership ratchets + module `__all__` (recurrence guardrails §5.4), and telemetry sink contracts (SMELL-20) — without changing runtime behavior.

**Architecture:** Small, additive changes with backward-compat preserved by construction (multiple inheritance keeps `except ValueError` working; tests only pin shapes; `__all__` is metadata). No refactors of logging formats or metric pipelines (explicitly out of scope — those need product decisions).

**Tech Stack:** Python 3, pytest (`pythonpath = . backend`, `--import-mode=importlib`), ruff.

## Global Constraints

- `pytest.ini`: `pythonpath = . backend`, `testpaths = tests backend/tests`, `--import-mode=importlib`.
- Root tests: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/ -q --no-header`.
- Brokers tests: `cd brokers && PYTHONPATH=..:. ../.venv/bin/python -m pytest -q --no-header`.
- Lint gate covers all touched files (system ruff if `.venv/bin/python -m ruff` missing; report binary).
- Test imports must be TOP-LEVEL (no mid-file imports — ruff E402 gate).
- DRY, YAGNI, TDD, frequent commits — one commit per task minimum.

---

## File Structure

| File | Responsibility after plan |
|---|---|
| `brokers/broker/dhan/domain/errors.py` (modify) | `DhanConfigError` also subclasses `ValueError` (compat) |
| `brokers/broker/dhan/application/config.py` (modify) | `from_env` raises typed errors |
| `shared/money.py`, `shared/net_policy.py`, `shared/reconnect.py` (modify) | Add `__all__` |
| `brokers/broker/dhan/domain/order_status.py` (modify) | Add `__all__` |
| `quant/execution/fills.py`, `quant/execution/lots.py` (modify) | Add `__all__` |
| `quant/contracts/instrument_registry.py` (modify) | Add helpers to `__all__` (or create it) |
| `backend/app/infrastructure/metrics.py` (modify) | `MetricsCollector.reset()` + snapshot-key contract |
| `backend/app/core/metrics.py` (modify) | `MetricsRegistry.reset()` (test isolation) |
| `tests/architecture/test_no_layer_bypass.py` (extend) | Ownership ratchet tests |
| `tests/quant/contracts/test_telemetry_standards.py` (new) | Config-error + telemetry contract tests |

---

### Task 1: Typed DhanConfig errors (backward compatible)

**Files:**
- Modify: `brokers/broker/dhan/domain/errors.py` (base-class change only)
- Modify: `brokers/broker/dhan/application/config.py` (raise sites + docstring)
- Test: `tests/quant/contracts/test_telemetry_standards.py` (new)

**Interfaces:** `DhanConfig.from_env(prefix)` — same returns; raises `DhanMissingConfigError` (missing vars) / `DhanConfigError` (unparseable numerics), both still catchable as `ValueError`.

**Verified facts (controller-read):** `config.py:118-130` raises bare `ValueError` for missing CLIENT_ID / ACCESS_TOKEN (with TOTP+PIN fallback preserved); `:135-136` `float()/int()` can raise raw `ValueError` on garbage. `DhanConfigError`/`DhanMissingConfigError` exist at `errors.py:522,532` (`DhanMissingConfigError(DhanConfigError)`, `DhanConfigError(DhanError)`).

- [ ] **Step 1: Write the failing test**

```python
# tests/quant/contracts/test_telemetry_standards.py
import pytest
from brokers.broker.dhan.application.config import DhanConfig
from brokers.broker.dhan.domain.errors import DhanConfigError, DhanError, DhanMissingConfigError


def test_missing_client_id_typed(monkeypatch):
    monkeypatch.delenv("DHAN_CLIENT_ID", raising=False)
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "tok")
    with pytest.raises(DhanMissingConfigError):
        DhanConfig.from_env()


def test_missing_token_without_totp_typed(monkeypatch):
    monkeypatch.setenv("DHAN_CLIENT_ID", "cid")
    monkeypatch.delenv("DHAN_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("DHAN_TOTP_SECRET", raising=False)
    monkeypatch.delenv("TOTP_SECRET", raising=False)
    monkeypatch.delenv("DHAN_PIN", raising=False)
    monkeypatch.delenv("PIN", raising=False)
    with pytest.raises(DhanMissingConfigError):
        DhanConfig.from_env()


def test_bad_numeric_typed(monkeypatch):
    monkeypatch.setenv("DHAN_CLIENT_ID", "cid")
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("DHAN_TIMEOUT", "not-a-number")
    with pytest.raises(DhanConfigError):
        DhanConfig.from_env()


def test_backward_compat_valueerror(monkeypatch):
    assert issubclass(DhanConfigError, ValueError)
    assert issubclass(DhanMissingConfigError, ValueError)
    monkeypatch.delenv("DHAN_CLIENT_ID", raising=False)
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "tok")
    with pytest.raises(ValueError):
        DhanConfig.from_env()
```

Caveat: `from_env` calls `cls._load_dotenv()` which walks up for `.env` — a repo `.env` with real values could mask `delenv` (load_dotenv with override=False won't override existing env, and monkeypatch.delenv removes from environ... but `_load_dotenv` may SET defaults from file for deleted keys? Read `_load_dotenv` first: if it uses `setdefault`/no-override, delenv sticks. If the test fails because repo `.env` provides values, scope env with a custom `prefix="TESTDHAN_"` instead (from_env takes prefix) — decide after Reading `_load_dotenv`, and report the choice.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_telemetry_standards.py -v`
Expected: FAIL (`DhanMissingConfigError` not raised — bare `ValueError`; and `issubclass` fails)

- [ ] **Step 3: Write minimal implementation**

In `errors.py`: `class DhanConfigError(DhanError):` → `class DhanConfigError(DhanError, ValueError):` (keep docstring; `DhanMissingConfigError` inherits both automatically). In `config.py`: `:118-121` → `raise DhanMissingConfigError(f"Missing required environment variable: {prefix}CLIENT_ID")`; `:127-130` → `raise DhanMissingConfigError(...)` (same message); wrap `:135-136`:
```python
        try:
            timeout = float(os.environ.get(f"{prefix}TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS)))
            max_retries = int(os.environ.get(f"{prefix}MAX_RETRIES", str(DEFAULT_MAX_RETRIES)))
        except (TypeError, ValueError) as e:
            raise DhanConfigError(f"Invalid numeric config: {e}") from e
```
Add `from brokers.broker.dhan.domain.errors import DhanConfigError, DhanMissingConfigError` (check current imports first — errors may already be imported; `DhanError` is imported per audit). Update the `Raises:` docstring (`:104-105`) to the typed errors. Before editing, grep all callers of `from_env` and all `except ValueError` handlers touching DhanConfig — report each; the dual inheritance keeps them working, but any test asserting `type(e) is ValueError` exactly would break (update only such exact-type assertions, reported individually).

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_telemetry_standards.py -q --no-header`
Expected: PASS. Then: `cd brokers && PYTHONPATH=..:. ../.venv/bin/python -m pytest broker/dhan/tests/test_application.py broker/dhan/tests/test_auth_wiring.py -q --no-header`
Expected: PASS (adjust only if missing; report; pre-existing failures need HEAD evidence)

- [ ] **Step 5: Commit**

```bash
git add brokers/broker/dhan/domain/errors.py brokers/broker/dhan/application/config.py tests/quant/contracts/test_telemetry_standards.py
git commit -m "refactor: typed DhanConfig errors with ValueError compat"
```

---

### Task 2: Ownership ratchets + `__all__` declarations

**Files:**
- Modify (add `__all__` only): `shared/money.py`, `shared/net_policy.py`, `shared/reconnect.py`, `brokers/broker/dhan/domain/order_status.py`, `quant/execution/fills.py`, `quant/execution/lots.py`, `quant/contracts/instrument_registry.py`
- Test: extend `tests/architecture/test_no_layer_bypass.py`

**Interfaces:** none (metadata + static gates only).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/architecture/test_no_layer_bypass.py
import re

_DUPS = {
    # pattern -> (files allowed to contain it, reason)
    r"^\s*(?:\w+\s*:\s*)?(?:Dict\[str, (?:int|float)\]|dict\[str, (?:int|float)\])\s*=\s*\{[^}]*NIFTY": (
        {"brokers/broker/market_info.py", "brokers/broker/dhan/domain/constants.py"},
        "registry-derived tables with marked extras only",
    ),
    r"def\s+_to_(decimal|float)\s*\(": (
        set(),
        "converters live in shared.money only",
    ),
    r"(?<!_OFFSET_SECONDS|OFFSET_SECONDS_|SECONDS)\b19800\b": (
        {
            "quant/contracts/timezones.py",  # computes from timedelta, not literal... VERIFY
            "frontend/time/ist.ts",
            "frontend/constants.ts",  # re-export line only — VERIFY, else drop
            "tests/quant/contracts/test_money_parity.py",
            "tests/quant/amt/session/test_context.py",
            "backend/tests/unit/domain/test_session_context.py",
        },
        "IST offset literal lives in time owners + pinned tests only",
    ),
}


def _hits(pattern: str, rel: str) -> list[str]:
    return re.findall(pattern, (ROOT / rel).read_text(), re.MULTILINE)


def test_no_new_duplicate_tables():
    bad: dict[str, list[str]] = {}
    for rel in _py_files():
        for pattern, (allowed, _reason) in _DUPS.items():
            if "def " in pattern or "19800" in pattern:
                if _hits(pattern, rel) and rel not in allowed:
                    bad.setdefault(rel, []).append(pattern)
    assert bad == {}, bad
```

Implementer: this sketch needs hardening — (a) write the `_py_files()` helper (rglob `*.py` excluding `.venv`, `venv`, `backend/venv`, `node_modules`, `.worktrees`, `__pycache__`); (b) VERIFY each allowlist entry by grepping first: `timezones.py` must NOT contain literal 19800 (it computes via timedelta — if it does contain it, that's today's bug to fix by replacing with the computed expression... actually if timezones.py contains 19800 literally, just allowlist it and note); `constants.ts` re-export must not contain the literal; (c) the LOT_SIZES-dict pattern must not match the registry-derived comprehensions (they contain no `NIFTY` literal — good) nor `_SPECS` in instrument_registry (keyed by variable? `_SPECS` entries use `_spec("NIFTY", ...)` — string literal, not dict-literal-with-NIFTY-key... the regex requires `= {` + `NIFTY` — `_SPECS: dict[str, InstrumentSpec] = {` + `"NIFTY"` inside `_spec(...)` calls WOULD match! Add `quant/contracts/instrument_registry.py` to that pattern's allowlist as the canonical owner); (d) run the test pre-fix to record the TRUE failure set — if grandfathered violations beyond the allowlist appear, extend the allowlist with `GRANDFATHERED` reason + file:line in the report rather than fixing unrelated code (reviewer adjudicates).

- [ ] **Step 2: Run to record the true failure set, then implement**

`__all__` additions (append-only, alphabetical):
- `shared/money.py`: `__all__ = ["safe_decimal_operation", "to_decimal", "to_float"]` (the module's real public names; verified at implementation)
- `shared/net_policy.py`: all 8 constants + `capped_exp_delay`
- `shared/reconnect.py`: `["ReconnectPolicy"]`
- `order_status.py`: `["DHAN_ORDER_STATUS_MAP", "TERMINAL_STATUSES", "is_terminal", "normalize_status"]`
- `fills.py`: `["BrokerFill", "broker_position_to_fill"]`
- `lots.py`: `["snap_to_lot"]`
- `instrument_registry.py`: Read first — if `__all__` exists, add `get_lot_size/get_tick_size`; else create with existing public names (`InstrumentSpec`, `UnknownInstrumentError`, `InstrumentRegistry`, `DEFAULT_REGISTRY`, `root_token`, `get_lot_size`, `get_tick_size`, + `specs`/`resolve` methods? no — `__all__` is module-level names only: verify each name exists at module level via Read).
Verify each `__all__` name is importable: `python -c "from <mod> import *"` per module (or a test asserting `all(hasattr(mod, n) for n in mod.__all__)` — add such a test, it self-checks).

- [ ] **Step 3: Run tests**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture/test_no_layer_bypass.py tests/quant/contracts/test_telemetry_standards.py -q --no-header`
Expected: PASS. Then ruff on all touched files.

- [ ] **Step 4: Commit**

```bash
git add shared/money.py shared/net_policy.py shared/reconnect.py brokers/broker/dhan/domain/order_status.py quant/execution/fills.py quant/execution/lots.py quant/contracts/instrument_registry.py tests/architecture/test_no_layer_bypass.py
git commit -m "refactor: ownership ratchets and module __all__"
```

---

### Task 3: Telemetry sink contracts (pin, don't merge)

**Files:**
- Modify: `backend/app/infrastructure/metrics.py` (add `reset()` + snapshot-key docstring)
- Modify: `backend/app/core/metrics.py` (add `reset()` for test isolation)
- Test: append to `tests/quant/contracts/test_telemetry_standards.py`

**Interfaces:** additive only (`reset()` classmethods); snapshot dict + prometheus shapes unchanged.

**Verified facts (controller-read):** Collector (79 lines, fully read): singleton, `record_signal/record_pnl/record_cache_hit|miss/record_regime_change/record_tick`, `snapshot()` keys `uptime_seconds/ticks_processed/signals/total_pnl/cache{hits,misses,hit_rate}/regime_changes`. Registry: `MetricsRegistry` singleton + module singletons `metrics`, `ticks_processed`, `signals_generated` (core/metrics.py:181-189). `health.py:283` serves `MetricsCollector().snapshot()`; `observability.py:24-25` reads prometheus counters. Header says do-not-merge (different purpose) — this task PINS the split, it does not merge.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/quant/contracts/test_telemetry_standards.py
# NOTE: root pytest has pythonpath `. backend`, and backend tests import the
# app package as `app.*` — mirror that (verify against any backend test's imports):
from app.infrastructure.metrics import MetricsCollector


def test_collector_snapshot_contract():
    c = MetricsCollector()
    c.reset()
    c.record_tick(); c.record_tick()
    c.record_signal("LONG")
    c.record_pnl(12.345)
    c.record_cache_hit(); c.record_cache_miss()
    c.record_regime_change()
    snap = MetricsCollector().snapshot()  # same singleton
    assert snap["ticks_processed"] == 2
    assert snap["signals"] == {"LONG": 1}
    assert snap["total_pnl"] == 12.35
    assert snap["cache"] == {"hits": 1, "misses": 1, "hit_rate": 0.5}
    assert snap["regime_changes"] == 1
    assert snap["uptime_seconds"] >= 0
    c.reset()


def test_collector_reset_isolation():
    c = MetricsCollector()
    c.record_tick()
    c.reset()
    assert MetricsCollector().snapshot()["ticks_processed"] == 0


def test_registry_counter_names():
    from app.core.metrics import metrics
    assert hasattr(metrics, "counter")
    c1 = metrics.counter("ticks_processed_total", "Total ticks processed")
    c2 = metrics.counter("signals_generated_total", "Signals generated")
    assert c1.value >= 0 and c2.value >= 0
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_telemetry_standards.py -k "collector or registry" -v`
Expected: FAIL (`reset` missing → AttributeError)

- [ ] **Step 3: Write minimal implementation**

In `MetricsCollector`: add
```python
    @classmethod
    def reset(cls) -> None:
        """Reset singleton state (test isolation only — never call live)."""
        inst = cls._instance
        if inst is not None and getattr(inst, "_initialized", False):
            with inst._lock:
                inst._signal_counts.clear()
                inst._total_pnl = 0.0
                inst._cache_hits = 0
                inst._cache_misses = 0
                inst._regime_changes = 0
                inst._ticks_processed = 0
```
(keep `_start_time`; snapshot docstring: append `Keys are a stable contract for /api/v1/metrics — do not rename.` to `snapshot()`.) In `core/metrics.py` `MetricsRegistry`: add
```python
    @classmethod
    def reset(cls) -> None:
        """Drop all registered families (test isolation only)."""
        inst = cls._instance
        if inst is not None:
            with inst._lock:
                inst._metrics.clear()
                inst._families.clear()
```
Check prometheus_client family re-registration after clear works (test_registry_counter_names calls counter() post-reset in other tests? If `test_collector_*` run before registry tests in same session, families were created fresh — fine. If duplicate-registration errors appear, report NEEDS_CONTEXT with the error.)

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_telemetry_standards.py -q --no-header`
Expected: PASS. Then: `cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/unit/api/test_coordinator_endpoints.py -q --no-header`
Expected: PASS (metrics-adjacent suite; report pre-existing with HEAD evidence)

- [ ] **Step 5: Commit**

```bash
git add backend/app/infrastructure/metrics.py backend/app/core/metrics.py tests/quant/contracts/test_telemetry_standards.py
git commit -m "refactor: telemetry sink contracts and test reset"
```

---

## Self-Review

- Spec coverage: SMELL-22 typed errors (Task 1) ✅, §5.4 guardrails — ratchets + `__all__` (Task 2) ✅, SMELL-20 telemetry contracts (Task 3) ✅.
- Explicitly OUT of scope (needs product decisions): merging the two metrics sinks; unifying the three logging schemas; removing the ~40 `except Exception` in quant/; removing `shared/conversion.py` overlap (left for a cleanup task once callers migrate); frontend `NETWORK_CONFIG` generation.
- Placeholder scan: Task 1 fully verbatim; Tasks 2–3 use Read-first with exact verification rules (proven pattern); every step has commands + expected outputs.
- Type consistency: `DhanConfigError(DhanError, ValueError)`; `__all__: list[str]`; `reset() -> None`; snapshot keys frozen.
