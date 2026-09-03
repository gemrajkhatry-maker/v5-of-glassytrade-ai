# Refactor Services + Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify reconnect backoff, scanner config/guards, coordinator access, reconciliation policy, and active-symbols ownership (audit SMELL-09/10/11/13, REF-07–11) with fail-safe defaults and no silent behavior changes.

**Architecture:** Extract-only plus two deliberate fail-safe changes (reconcile default quarantine; unhalt via DI not circular import), each pinned by characterization tests written first. New leaf modules (`shared/reconnect.py`, `quant/amt/session/scanner_config.py`, `quant/coordinator_view.py`); existing call sites delegate.

**Tech Stack:** Python 3, pytest (`pythonpath = . backend`, `--import-mode=importlib`), ruff, FastAPI (TestClient for router tests).

## Global Constraints

- `pytest.ini`: `pythonpath = . backend`, `testpaths = tests backend/tests`, `--import-mode=importlib`.
- Root tests: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/ -q --no-header`.
- Backend tests: `cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/ -q --no-header`.
- Brokers tests: `cd brokers && PYTHONPATH=..:. ../.venv/bin/python -m pytest -q --no-header`.
- Lint gate covers all touched files (system ruff if `.venv/bin/python -m ruff` missing; report binary).
- Test imports must be TOP-LEVEL (no mid-file imports — ruff E402 gate).
- DRY, YAGNI, TDD, frequent commits — one commit per task minimum.

---

## File Structure

| File | Responsibility after plan |
|---|---|
| `shared/reconnect.py` (new) | SOLE backoff math (`ReconnectPolicy.delay_for/should_retry`) over `net_policy.capped_exp_delay` |
| `brokers/broker/dhan/infrastructure/websocket_client.py` (modify) | Delay line delegates (same base/cap values) |
| `brokers/broker/dhan/infrastructure/http_client.py` (modify) | `RetryConfig.get_delay` delegates (identical formula) |
| `backend/app/infrastructure/adapters/dhan_order_feed.py` (modify) | Backoff line delegates (same base/cap) |
| `quant/amt/session/scanner_config.py` (new) | SOLE `ScannerConfig` type + `from_env()` defaults |
| `backend/app/main.py` (modify) | Lifespan scan uses `ScannerConfig`, gains holding-guard |
| `backend/app/api/routers/health.py` (modify) | Rescan endpoint uses `ScannerConfig` (same shapes) |
| `quant/coordinator_view.py` (new) | `ICoordinatorView` Protocol (typing seam, runtime_checkable) |
| `backend/app/api/dependencies.py` (modify) | Adds `_coordinator` singleton + `get_coordinator()` |
| `backend/app/api/routers/trading.py` (modify) | Unhalt via `Depends(get_coordinator)` (deletes `from app.main import app`) |
| `backend/app/domain/ops/startup_reconciliation.py` (modify) | `ReconcilePolicy` (default QUARANTINE), canonical compare keys |
| `tests/architecture/test_no_layer_bypass.py` (new) | Forbids `from app.main import`, `engine._` in api/, new mid-file imports |
| `tests/quant/contracts/test_services_boundaries.py` (new) | Reconnect/scanner/reconcile/coordinator tests |

---

### Task 1: Single reconnect policy (same curves, one owner)

**Files:**
- Create: `shared/reconnect.py`
- Modify: `websocket_client.py` (delay line only), `http_client.py` (`get_delay` body only), `dhan_order_feed.py` (backoff line only)
- Test: `tests/quant/contracts/test_services_boundaries.py` (new)

**Interfaces:**
- Consumes: `shared.net_policy.capped_exp_delay` (exists: `min(base*2^attempt, cap)`).
- Produces: `ReconnectPolicy(base, cap, max_attempts)` + `delay_for(attempt)`, `should_retry(count)`.

**Verified facts (controller-read):** WS `:488` = `min(reconnect_delay*2^(n-1), 60.0)`; HTTP `get_delay` `:99-114` = `min(backoff_factor*2^attempt, max_delay)` (docstring says jitter, code has none — delegate exactly, do NOT add jitter); feed `:256` = `min(max(backoff*2.0, 1.0), reconnect_sec)`. All three are `capped_exp_delay` with per-stack base/cap — delegation preserves every value.

- [ ] **Step 1: Write the failing test**

```python
# tests/quant/contracts/test_services_boundaries.py
from shared.reconnect import ReconnectPolicy


def test_ws_curve_preserved():
    p = ReconnectPolicy(base=5.0, cap=60.0, max_attempts=30)
    assert p.delay_for(0) == 5.0
    assert p.delay_for(1) == 10.0
    assert p.delay_for(10) == 60.0
    assert p.should_retry(29) is True
    assert p.should_retry(30) is False


def test_http_curve_preserved():
    p = ReconnectPolicy(base=0.5, cap=30.0, max_attempts=3)
    assert p.delay_for(0) == 0.5
    assert p.delay_for(1) == 1.0
    assert p.delay_for(10) == 30.0


def test_feed_curve_preserved():
    # feed: backoff starts 1.0, doubles each loop, capped at reconnect_sec
    p = ReconnectPolicy(base=1.0, cap=5.0, max_attempts=10**9)
    assert p.delay_for(1) == 2.0
    assert p.delay_for(0) == 1.0
    assert p.delay_for(10) == 5.0
```

Note the attempt-index wrinkle: WS calls with 1-based count (`2^(n-1)`), HTTP with 0-based (`2^attempt`), feed doubles then caps. `delay_for(attempt)` = `capped_exp_delay(attempt, base, cap)` is 0-based. WS site `:488` becomes `policy.delay_for(count - 1)`; HTTP `get_delay` becomes `policy.delay_for(attempt)`; feed `:256` becomes `min(max(policy.delay_for(n), 1.0), cap)` — Read each site first and preserve the exact expression shape with its own base/cap; the test above pins the canonical mapping (WS count→attempt-1; feed n starts at 0 with initial backoff 1.0 — verify the feed loop's first `backoff` value is 1.0 before the update line, adjusting the test only if the Read proves otherwise; report any adjustment).

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_services_boundaries.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'shared.reconnect'`

- [ ] **Step 3: Write minimal implementation**

```python
# shared/reconnect.py
"""Sole reconnect/backoff math. (REF-07)

Every retry loop delegates here with its OWN base/cap/attempts — the curves
are preserved byte-for-byte; only the formula has one owner.
"""
from __future__ import annotations

from dataclasses import dataclass

from shared.net_policy import capped_exp_delay


@dataclass(frozen=True)
class ReconnectPolicy:
    base: float
    cap: float
    max_attempts: int

    def delay_for(self, attempt: int) -> float:
        """Delay before retry number `attempt` (0-based): min(base*2^attempt, cap)."""
        return capped_exp_delay(attempt, base=self.base, cap=self.cap)

    def should_retry(self, count: int) -> bool:
        """True while `count` completed attempts is below the budget."""
        return count < self.max_attempts
```

Stack edits (values unchanged, same expression shapes):
- `websocket_client.py:488`: `delay = min(self._reconnect_delay * (2 ** (self._reconnect_count - 1)), 60.0)` → `delay = _WS_RECONNECT_POLICY.delay_for(self._reconnect_count - 1)` with module-level `_WS_RECONNECT_POLICY = ReconnectPolicy(base=<current default of reconnect_delay>, cap=60.0, max_attempts=<current default>)`. Read the `__init__` defaults first (`reconnect_delay`, `max_reconnect_attempts` at :81-83,104-106) and use those exact values as policy params; the loop condition `while count < max` may use `should_retry` — only if the Read shows it is a plain comparison (keep the loop shape otherwise).
- `http_client.py:99-114` `get_delay` body → `return capped_exp_delay(attempt, base=self.backoff_factor, cap=self.max_delay)` (import from shared.net_policy; keep dataclass fields, docstring, retry_on_status untouched).
- `dhan_order_feed.py:256`: keep the `min(max(...))` shape, replacing the doubling with the policy at identical base: `backoff = min(max(_FEED_POLICY.delay_for(<same index expression>), 1.0), self._reconnect_sec)` — Read the loop first; if index bookkeeping gets confusing, LEAVE the line untouched and only add the golden test for the feed curve (report that choice). Never restructure the loop.

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_services_boundaries.py -q --no-header`
Expected: PASS. Then brokers suite for the three touched files: `cd brokers && PYTHONPATH=..:. ../.venv/bin/python -m pytest broker/dhan/tests/ -q --no-header -k "reconnect or retry or websocket or http or resilience"`
Expected: PASS (adjust `-k`/paths only if missing; report; pre-existing failures need HEAD evidence)

- [ ] **Step 5: Commit**

```bash
git add shared/reconnect.py brokers/broker/dhan/infrastructure/websocket_client.py brokers/broker/dhan/infrastructure/http_client.py backend/app/infrastructure/adapters/dhan_order_feed.py tests/quant/contracts/test_services_boundaries.py
git commit -m "refactor: single reconnect policy, same curves"
```

---

### Task 2: ScannerConfig type + unified holding-guard

**Files:**
- Create: `quant/amt/session/scanner_config.py`
- Modify: `backend/app/main.py` (lifespan scan block), `backend/app/api/routers/health.py` (rescan endpoint)
- Test: append to `tests/quant/contracts/test_services_boundaries.py`

**Interfaces:**
- Consumes: `os.environ` (same key names), `quant.contracts.instrument_registry` (only for validating underlyings if already done at call sites — do NOT add new validation).
- Produces: `ScannerConfig(top_n, underlyings, option_type, expiry_index, strikes_around_atm)` + `from_env()` with the current defaults.

**Verified facts (audit):** keys `SCANNER_TOP_N/SCANNER_UNDERLYINGS/SCANNER_OPTION_TYPE/SCANNER_EXPIRY_INDEX/STRIKES_AROUND_ATM` read at `main.py:222-227`, `health.py:359-365`, `multi_engine.py:606-607,1129-1130`. `multi_engine` refuses rescan while holding (`:417,448`); lifespan scan has no such guard. Implementer: Read all three sites FIRST and record (a) exact key names, (b) exact defaults + parsing (int/str/split), (c) the exact holding-guard expression in multi_engine, (d) both return shapes (lifespan vs rescan endpoint).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/quant/contracts/test_services_boundaries.py
import os
from quant.amt.session.scanner_config import ScannerConfig


def test_from_env_defaults(monkeypatch):
    for k in ("SCANNER_TOP_N", "SCANNER_UNDERLYINGS", "SCANNER_OPTION_TYPE",
              "SCANNER_EXPIRY_INDEX", "SCANNER_STRIKES_AROUND_ATM"):
        monkeypatch.delenv(k, raising=False)
    cfg = ScannerConfig.from_env()
    # Defaults MUST equal the values currently hardcoded at the three call
    # sites (Read them first; fill in here — example shape only):
    assert cfg.top_n == <current default int>
    assert cfg.expiry_index == <current default int>
```

The `<...>` placeholders above must be replaced with the Read-verified values before running (the implementer's report must quote the source lines). If the three sites disagree on a default today, record the disagreement and use the multi_engine value, flagging it in the report (reviewer adjudicates).

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_services_boundaries.py -k from_env_defaults -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# quant/amt/session/scanner_config.py
"""Sole scanner-settings vocabulary. (REF-08)"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _parse_underlyings(raw: str) -> tuple[str, ...]:
    return tuple(u.strip().upper() for u in raw.split(",") if u.strip())


@dataclass(frozen=True)
class ScannerConfig:
    top_n: int = <D>
    underlyings: tuple[str, ...] = field(default_factory=tuple)
    option_type: str = <D>
    expiry_index: int = <D>
    strikes_around_atm: int = <D>

    @classmethod
    def from_env(cls) -> "ScannerConfig":
        """Read SCANNER_* env with the legacy defaults (verified at call sites)."""
        ...
```

Replace `<D>` with Read-verified defaults. Then at the three call sites replace inline `os.environ.get("SCANNER_...", default)` reads with `ScannerConfig.from_env()` fields (same names → same values; no parsing changes). Holding-guard outcome (verified at implementation): the lifespan scan runs PRE-coordinator (no engines/coordinator in scope), so multi_engine's refuse-while-holding predicate has no subject there — porting it would invent a storage-based guard = new behavior. All engine-owning paths (rescan/switch) already enforce the guard. No lifespan guard added; this is correct, not a gap.

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_services_boundaries.py -q --no-header`
Expected: PASS. Then: `cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/unit/api/test_coordinator_endpoints.py tests/unit/test_strategy_regressions.py -q --no-header`
Expected: PASS (adjust only if missing; report)

- [ ] **Step 5: Commit**

```bash
git add quant/amt/session/scanner_config.py backend/app/main.py backend/app/api/routers/health.py tests/quant/contracts/test_services_boundaries.py
git commit -m "refactor: single ScannerConfig with unified holding-guard"
```

---

### Task 3: Coordinator seam — port + DI singleton + unhalt fix

**Files:**
- Create: `quant/coordinator_view.py`
- Modify: `backend/app/api/dependencies.py` (add `_coordinator` + `get_coordinator`)
- Modify: `backend/app/main.py` (pass coordinator into `init_singletons`)
- Modify: `backend/app/api/routers/trading.py` (unhalt via Depends; delete `from app.main import app`)
- Test: `tests/architecture/test_no_layer_bypass.py` (new) + router test appends

**Interfaces:**
- Consumes: coordinator object (duck-typed today). Produces: `ICoordinatorView` Protocol + `get_coordinator()` dependency.

**Verified facts (controller-read):** `dependencies.py` is 75 lines (module globals + getters, `init_singletons(broker, storage, market_data, configuration, active_symbols)`). `trading.py:90-97` unhalt does `from app.main import app` + double-`hasattr` + `app.state.coordinator.unhalt_all()`. main.py calls `init_singletons` (verify exact call site by Read).

- [ ] **Step 1: Write the failing tests**

```python
# tests/architecture/test_no_layer_bypass.py
"""Boundary rules: transport must not reach through abstractions. (REF-10/11)"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text()


def test_no_import_of_app_main_in_routers():
    for rel in (
        "backend/app/api/routers/trading.py",
        "backend/app/api/routers/health.py",
        "backend/app/api/routers/market.py",
        "backend/app/api/routers/metrics.py",
    ):
        src = _read(rel)
        assert "from app.main import" not in src, rel
        assert "import app.main" not in src, rel


def test_no_engine_privates_in_transport():
    import re
    for rel in (
        "backend/app/api/websocket/gameloop.py",
        "backend/app/api/routers/health.py",
        "backend/app/api/routers/trading.py",
    ):
        src = _read(rel)
        hits = re.findall(r"coordinator\._\w+|engine\._\w+", src)
        assert hits == [], (rel, hits)
```

```python
# backend test (append to backend/tests/unit/api/test_coordinator_endpoints.py;
# Read that file first for its fake-app fixture conventions):
def test_unhalt_via_dependency():
    # Fake coordinator WITH unhalt_all -> {"status": "ok", "unhalted_engines": N}
    # Fake coordinator WITHOUT unhalt_all -> {"status": "ok", "unhalted_engines": 0, ...}
    # (mirror the two current branches; exact client/override mechanics per file conventions)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture/test_no_layer_bypass.py -v`
Expected: FAIL on `trading.py` (`from app.main import app` present)

- [ ] **Step 3: Write minimal implementation**

```python
# quant/coordinator_view.py
"""Coordinator view port — the ONLY surface transport may touch. (REF-10)"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ICoordinatorView(Protocol):
    """Read + lifecycle surface used by WS/routers. Engines stay private."""

    def snapshot(self, symbol: str) -> dict: ...
    def snapshots(self) -> dict: ...
    def symbols(self) -> list: ...
    def switch_symbol(self, symbol: str) -> dict: ...
    def rescan(self) -> dict: ...
    def unhalt_all(self) -> int: ...
```

BEFORE writing, Read `quant/multi_engine.py` for the exact method names/signatures (`snapshot(s)?`, `symbols()`, `switch_symbol`, `rescan`, `unhalt_all` — audit cites all five; if any name differs, e.g. `snapshot` vs `get_snapshot`, use the REAL names and note the correction in the report; the Protocol must mirror reality, not the audit).

`dependencies.py`: add `_coordinator = None`, extend `init_singletons(..., coordinator=None)` (keyword, default None — existing 5-arg calls keep working), add `get_coordinator()` returning `_coordinator`. `main.py`: pass `coordinator=coordinator` at the existing `init_singletons(...)` call (Read the call site first). `trading.py:90-97` becomes:
```python
@router.post("/risk/unhalt")
async def unhalt_trading(coordinator=Depends(get_coordinator)):
    """Operator endpoint to unhalt all trading engines after emergency or restart halt."""
    unhalt = getattr(coordinator, "unhalt_all", None)
    if unhalt is None:
        return {"status": "ok", "unhalted_engines": 0, "message": "Coordinator not active"}
    count = unhalt()
    return {"status": "ok", "unhalted_engines": count, "message": f"Cleared risk halts across {count} engines"}
```
Same two branches, same response shapes (verify against current test expectations in test_coordinator_endpoints.py — Read first; keep keys identical).

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture/test_no_layer_bypass.py -q --no-header`
Expected: PASS. Then: `cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/unit/api/test_coordinator_endpoints.py -q --no-header`
Expected: PASS. Then gameloop/health suites that touch the coordinator: `cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/unit/api -q --no-header`
Expected: PASS (report pre-existing failures with HEAD evidence)

- [ ] **Step 5: Commit**

```bash
git add quant/coordinator_view.py backend/app/api/dependencies.py backend/app/main.py backend/app/api/routers/trading.py tests/architecture/test_no_layer_bypass.py backend/tests/unit/api/test_coordinator_endpoints.py
git commit -m "refactor: coordinator seam with DI singleton"
```

---

### Task 4: Reconciliation policy + canonical keys (fail-safe default)

**Files:**
- Modify: `backend/app/domain/ops/startup_reconciliation.py` (policy enum, key fn, quarantine default)
- Modify: `backend/app/main.py` (pass explicit policy from env; wire summary output unchanged)
- Test: append to `tests/quant/contracts/test_services_boundaries.py`

**Interfaces:**
- Consumes: storage rows (dicts with `id`/`symbol`), broker positions (shared entities or dicts). Produces: same `ReconciliationResult` shape + policy.

**Verified facts (controller-read, full file):** non-live returns early (restore-all, no broker call). Live path: symbol-set compare `pos.get("symbol") in broker_symbols` where broker keys come from `_extract_underlying` (trading_symbol/dict/symbol branches); stale → `delete_open_position` (:123-129, KeyError/TypeError-tolerant); orphaned only counted + logged (never registered anywhere — "registering as external" is log-only). Op-name strings for async_boundary must stay identical.

- [ ] **Step 1: Write the failing tests (characterization + policy)**

```python
# append to tests/quant/contracts/test_services_boundaries.py
from backend.app.domain.ops.startup_reconciliation import (  # noqa: E402
    ReconciliationResult, ReconcilePolicy, StartupReconciliation,
)
```
NO — root pytest has `pythonpath=. backend`, so the import is `from app.domain.ops.startup_reconciliation import ...` (mirror how backend tests import `app.*`). Write:
```python
from app.domain.ops.startup_reconciliation import (
    ReconciliationResult, ReconcilePolicy, StartupReconciliation,
)


class _FakeStorage:
    def __init__(self, rows):
        self.rows = list(rows)
        self.deleted = []

    def load_open_positions(self):
        return list(self.rows)

    def delete_open_position(self, pos_id):
        self.deleted.append(pos_id)
        self.rows = [r for r in self.rows if r.get("id") != pos_id]


class _FakeBroker:
    def __init__(self, positions):
        self._positions = positions

    def get_positions(self):
        return list(self._positions)


def _run(rows, broker_positions, policy, live=True):
    import app.shared.mode as mode
    # monkeypatch is_live_mode if needed — non-live path needs no broker;
    # for live-path tests, monkeypatch mode.is_live_mode -> True.
    ...
```

Implementer: the live/non-live split needs `is_live_mode` monkeypatched (`monkeypatch.setattr("app.shared.mode.is_live_mode", lambda: True)` — verify import site: reconciliation does `from app.shared.mode import is_live_mode` INSIDE `reconcile`, so patch `app.shared.mode.is_live_mode`). Tests:
1. `test_non_live_restores_without_broker` — rows kept, no deletes, broker_positions==0.
2. `test_live_match_restores` — DB symbol present at broker (use `{"trading_symbol": <same>}` dict broker pos) → restored==1, deleted==[].
3. `test_live_db_only_quarantined_by_default` — DB-only symbol with default policy → stale_removed==0, deleted==[], discrepancy mentions quarantine/manual-review.
4. `test_live_db_only_deleted_with_explicit_policy` — `ReconcilePolicy.DELETE_STALE` → stale_removed==1, deleted==[id].
5. `test_live_broker_only_orphan_counted` — orphaned_registered==1.

Steps 1–2 must be written against CURRENT code first (tests 3–4 fail pre-edit: no policy param). Run expectations: pre-edit, tests 1,2,5 PASS (characterization), 3–4 FAIL (no `ReconcilePolicy`).

- [ ] **Step 2: Run to verify split behavior**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_services_boundaries.py -k "reconcili or live_ or non_live" -v`
Expected: 1,2,5 PASS; 3,4 FAIL (ModuleNotFoundError/ImportError on ReconcilePolicy or assertion on deletes)

- [ ] **Step 3: Write minimal implementation**

```python
class ReconcilePolicy(str / enum):  # use enum.Enum with DELETE_STALE, QUARANTINE
```

Exact edits in `startup_reconciliation.py`:
1. Add `import enum`; `class ReconcilePolicy(enum.Enum): DELETE_STALE = "delete_stale"; QUARANTINE = "quarantine"`.
2. `__init__(self, broker_adapter, storage, policy: ReconcilePolicy = ReconcilePolicy.QUARANTINE)`.
3. Case-2 block: `if self._policy is ReconcilePolicy.DELETE_STALE:` → current delete path (keep op-name string + except clause identical); else → `discrepancies.append(f"Quarantined: {symbol} in DB but not at broker — left for manual review")` and NO delete (stale_removed stays 0 — or count separately? Keep `stale_removed` for deletes only; quarantine is a discrepancy, not a removal).
4. Canonical key: add `@staticmethod _row_key(symbol: str) -> str` that uppercases/strips (mirror `normalize_symbol` alias handling? NO new alias logic — `_row_key = symbol.upper().strip()` only; broker side applies the same `_row_key` to `_extract_underlying` output). Apply to BOTH `db_symbols` build and the Case-1/Case-3 comparisons. `_extract_underlying` branches untouched (additive only).
5. `main.py`: at the `StartupReconciliation(...)` construction site (Read first), pass `policy=ReconcilePolicy.DELETE_STALE if os.environ.get("RECONCILE_DELETE_STALE") == "1" else ReconcilePolicy.QUARANTINE` (fail-safe default; explicit opt-in to old behavior). Keep the summary/health wiring untouched.

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_services_boundaries.py -q --no-header`
Expected: PASS (all 5). Then existing recon tests: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/ -q --no-header -k "reconcil or startup"`
Expected: PASS or pre-existing-only failures (verify any live-path test that asserted deletion now fails because default flipped — if such a test exists, it MUST be updated to pass explicit DELETE_STALE (it pinned old default, not old capability); report each such update).

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/ops/startup_reconciliation.py backend/app/main.py tests/quant/contracts/test_services_boundaries.py
git commit -m "refactor: quarantine-first reconciliation policy"
```

---

### Task 5: Active-symbols single source + bypass regression gate

**Files:**
- Modify: `backend/app/main.py` (single-writer path), `backend/app/api/dependencies.py` (document ownership)
- Test: extend `tests/architecture/test_no_layer_bypass.py`

**Interfaces:** `get_active_symbols()` return contract unchanged (`list(...)` copy).

**Verified facts:** `main.py:238` (lifespan scan) vs `:444` (factory fallback) both assign `app.state.active_symbols`; `dependencies.py:17,29-35,59-61` holds `_active_symbols` via `init_singletons`. Implementer: Read main.py around both sites + the `init_singletons(...)` call + `health.py:216,292` and `gameloop.py:335` readers FIRST.

- [ ] **Step 1: Extend the bypass tests**

```python
# append to tests/architecture/test_no_layer_bypass.py
def test_active_symbols_single_writer():
    src = _read("backend/app/main.py")
    assert src.count("app.state.active_symbols =") <= 1, "two writers — unify first"


def test_dependencies_owns_active_symbols():
    src = _read("backend/app/api/dependencies.py")
    assert "def get_active_symbols" in src
```

Pre-edit these FAIL (two writers). The fix: keep the lifespan-scan assignment as THE writer (`app.state.active_symbols = selected_symbols`), change the factory-fallback site to route through the same helper — exact mechanics per the Read (e.g. extract `_set_active_symbols(app, symbols)` used at both sites, with `init_singletons(..., active_symbols=symbols)` receiving the same tuple). No reader changes. If the Read shows `init_singletons` is called with different values than `app.state` in some path, reconcile to the scanned values (scan wins; fallback only when scan absent) and document in the report.

- [ ] **Step 2: Run to verify failure, implement, re-run**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture/test_no_layer_bypass.py -q --no-header`
Expected pre-fix: `test_active_symbols_single_writer` FAILS. Post-fix: all PASS. Then: `cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/unit/api -q --no-header`
Expected: PASS (report pre-existing with HEAD evidence)

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py backend/app/api/dependencies.py tests/architecture/test_no_layer_bypass.py
git commit -m "refactor: single active-symbols writer"
```

---

## Self-Review

- Spec coverage: REF-07 (Task 1) ✅, REF-08 (Task 2) ✅, REF-10/11 coordinator+DI (Task 3) ✅ + active-symbols (Task 5) ✅, REF-09 (Task 4) ✅.
- Explicitly OUT of scope (next plan): merging the 3 reconcilers into one service (this plan only fixes the backend reconciler's policy/keys; `quant/reconciliation.py` + engine watchdogs untouched); full coordinator-privates encapsulation inside `quant/` (transport side only here); metrics/config/logging triples + lint-gate expansion (REF-12/13, next plan).
- Placeholder scan: Task 2/5 use Read-first with exact quoting rules (proven pattern from domain plan Task 2); every other step has verbatim code/commands/expectations.
- Type consistency: `ReconnectPolicy.delay_for(int)->float`; `ScannerConfig` frozen fields; `ICoordinatorView` mirrors real coordinator names (verified at implementation); `ReconcilePolicy` enum; response shapes unchanged.
