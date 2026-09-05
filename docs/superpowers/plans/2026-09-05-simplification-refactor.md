# Simplification Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the five verified duplication/architecture targets (dead code, type clones, calc duplication, port fan-out, god files) with zero behavior change, enforced by parity tests, identity re-export tests, and a byte-identical golden trace.

**Architecture:** Strangler refactor in 5 slices on `feat/fractal-half-trend-signals`. Canonical homes stay in place; secondaries become re-exports or calls. Layered models (`Signal`/`Position` pairs) are sanctioned seams — documented and guarded, NOT unified (spec §8).

**Tech Stack:** Python 3.12 (`.venv`), pytest. Baselines: `tests/quant` 1,761 passed / 0 failed; backend unit 687 passed; `tests/quant/runtime/test_decide_golden.py` snapshot byte-stable.

## Global Constraints

- Run tests from repo root: `.venv/bin/python -m pytest <path> -q`
- **Per-task gate (every task):** full `tests/quant` green + `tests/system/test_quant_execution_e2e.py` green before commit. Tasks 2-4 additionally gate on backend unit suite: `.venv/bin/python -m pytest backend/tests/unit -q` (baseline 687 passed, 1 pre-existing environmental failure `test_crit_02`-class allowed).
- **Golden gate:** `tests/quant/runtime/test_decide_golden.py::test_decide_golden_matches_committed_snapshot` must pass unchanged. If it fails: STOP, never regenerate the snapshot, diagnose against `docs/amt`.
- **Exact-equality rule:** parity tests assert exact values (no epsilon tolerance).
- Every re-export shim gets an identity test: `module.X is canonical.X`.
- One concern per commit. No slice mixes deletions with moves.
- Do not touch `quant/decision/*` gate logic, `quant/execution/risk.py` sizing math, or any absorption math semantics in `AbsorptionDetector`.
- Census-driven tasks (7b, 10) have explicit decision rules; if the rule's condition is false, STOP and report instead of improvising.

---

### Task 1: Delete dead `quant/hansi/`

**Files:**
- Delete: `quant/hansi/` (entire package: `models.py` + any siblings)
- Test: none new (suite gate only)

**Interfaces:**
- Consumes: grep evidence that `hansi` has zero importers in `quant/`, `backend/`, `tests/`, `brokers/`, `shared/`
- Produces: repo without the dead third `Signal` copy

- [ ] **Step 1: Verify zero references (guard against dynamic/string imports)**

```bash
grep -rn "hansi" --include="*.py" quant/ backend/ tests/ brokers/ shared/ 2>/dev/null | grep -v "quant/hansi/" || echo "CLEAN"
```

Expected: `CLEAN`. If any hit outside `quant/hansi/`: STOP and report the reference.

- [ ] **Step 2: Delete and gate**

```bash
git rm -rq quant/hansi
.venv/bin/python -m pytest tests/quant -q 2>&1 | tail -1
.venv/bin/python -m pytest tests/system/test_quant_execution_e2e.py -q 2>&1 | tail -1
```

Expected: 1,761 passed / 0 failed (count may drop by hansi's own tests only — if a drop exceeds that, STOP and diagnose).

- [ ] **Step 3: Commit**

```bash
git commit -q -m "refactor: delete dead quant/hansi package (zero importers)"
```

---

### Task 2: Unify `Bar` (canonical `quant/bars.py`, `state_machine` re-exports)

**Files:**
- Modify: `quant/bars.py` (Bar defaults widened)
- Modify: `quant/state_machine.py` (class Bar → re-export)
- Test: `tests/quant/test_type_unification.py` (new; holds ALL identity tests from this plan)

**Interfaces:**
- Produces: `quant.state_machine.Bar is quant.bars.Bar` — event_store fold and all state tests keep working; all fields now default-constructible.

- [ ] **Step 1: Write the failing identity test**

Create `tests/quant/test_type_unification.py`:

```python
# tests/quant/test_type_unification.py
"""Identity guarantees: sanctioned single definitions. Every re-export shim
must be the SAME object as its canonical home — equality is not enough."""

import quant.bars as bars
import quant.state_machine as state_machine


def test_bar_is_single_definition():
    assert state_machine.Bar is bars.Bar
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/quant/test_type_unification.py -q
```

Expected: FAIL (`is` comparison False — two distinct classes).

- [ ] **Step 3: Widen `quant/bars.py::Bar` defaults (compatible — adds defaults only)**

In `quant/bars.py`, replace the field list:

```python
class Bar:
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    delta: float = 0.0
    oi: float = 0.0
    vwap: float = 0.0  # volume-weighted average price accumulated by BarAggregator
```

with:

```python
class Bar:
    time: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    delta: float = 0.0
    oi: float = 0.0
    vwap: float = 0.0  # volume-weighted average price accumulated by BarAggregator
```

- [ ] **Step 4: Replace `quant/state_machine.py` Bar class with the re-export**

In `quant/state_machine.py`, replace the entire `class Bar:` dataclass block (line ~41, through the end of its fields) with:

```python
from quant.bars import Bar  # canonical single definition (was a local dataclass)
```

placed at the module's import section; delete the local `@dataclass class Bar:` block entirely. Keep any internal uses of `Bar` unchanged (the name still resolves via the import). If `state_machine.py` uses `Bar` in type annotations only, nothing else changes.

- [ ] **Step 5: Gate + commit**

```bash
.venv/bin/python -m pytest tests/quant/test_type_unification.py tests/quant/test_state_machine.py tests/quant/test_transitions.py tests/quant/test_event_store_prune.py tests/quant/test_projector_replacement.py tests/quant/test_event_store_jsonl.py tests/quant/security/test_tamper_resistance.py tests/quant/integration/test_desync.py -q
.venv/bin/python -m pytest tests/quant -q 2>&1 | tail -1
.venv/bin/python -m pytest tests/system/test_quant_execution_e2e.py -q 2>&1 | tail -1
git add -A tests/quant/test_type_unification.py quant/bars.py quant/state_machine.py
git commit -q -m "refactor: unify Bar — bars.py canonical, state_machine re-exports (defaults widened compatibly)"
```

Expected: all green, 1,761+ passed.

---

### Task 3: Unify `OHLC` (field-compat gate gates the direction)

> **OUTCOME (2026-09-05): BLOCKED BY DESIGN GATE — correct result.** The AST field-compat script printed `DIFFERENT` (and methods differ): `contracts.OHLC` = 9 Decimal fields (engine order-flow candle, `create`/`to_float`), `dhan.OHLC` = 4 float fields + `range`/`body_size`/`is_bullish`/`is_bearish` properties. Per spec §8 these are **layered models — kept, pinned by the Task 4 guard**. No files changed. Task 4's guard lists below reflect this.

**Files:**
- Possibly modify: `brokers/broker/dhan/domain/value_objects.py` (OHLC → re-export) OR `quant/contracts/value_objects.py` (reverse direction)
- Test: `tests/quant/test_type_unification.py` (append)

**Interfaces:**
- Consumes: Task 2's test file.
- Produces: exactly one `OHLC` definition; both import populations (`quant/contracts/value_objects` users: amt_engine, analyzer, footprint, aggressive_prints, detectors, cvd; `brokers/.../value_objects` users: backend schemas, dhan_adapter) resolve to it.

- [ ] **Step 1: Field-compatibility check (decision gate)**

```bash
$(cat graphify-out/.graphify_python 2>/dev/null || echo .venv/bin/python) - <<'EOF'
import ast, json
def fields(path, cls):
    src = open(path).read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            out = []
            for s in node.body:
                if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name):
                    out.append((s.target.id, ast.unparse(s.annotation)))
            return out
    return None
a = fields('quant/contracts/value_objects.py', 'OHLC')
b = fields('brokers/broker/dhan/domain/value_objects.py', 'OHLC')
print('contracts.OHLC :', a)
print('dhan.OHLC      :', b)
print('IDENTICAL' if a == b else 'DIFFERENT')
EOF
```

Expected: prints both field lists. **Decision rule:** `IDENTICAL` → continue Step 2. `DIFFERENT` → STOP and report the two field lists (spec §8 permits either direction; a mismatch means these are layered models like Signal/Position — do NOT force).

- [ ] **Step 2: Append failing identity test**

```python
def test_ohlc_is_single_definition():
    import quant.contracts.value_objects as cvo
    import brokers.broker.dhan.domain.value_objects as dvo
    assert dvo.OHLC is cvo.OHLC
```

Run: `.venv/bin/python -m pytest tests/quant/test_type_unification.py -q` → Expected: FAIL.

- [ ] **Step 3: Make dhan's OHLC the re-export (canonical stays `quant/contracts/value_objects.py` per spec)**

In `brokers/broker/dhan/domain/value_objects.py`: delete the local `class OHLC:` block and add at the module imports:

```python
from quant.contracts.value_objects import OHLC  # canonical single definition
```

- [ ] **Step 4: Gate + commit**

```bash
.venv/bin/python -m pytest tests/quant/test_type_unification.py tests/quant/amt tests/backend -q 2>/dev/null || .venv/bin/python -m pytest tests/quant/test_type_unification.py tests/quant/amt -q
.venv/bin/python -m pytest tests/quant -q 2>&1 | tail -1
.venv/bin/python -m pytest tests/system/test_quant_execution_e2e.py -q 2>&1 | tail -1
.venv/bin/python -m pytest backend/tests/unit -q 2>&1 | tail -1
git add -A && git commit -q -m "refactor: unify OHLC — contracts/value_objects canonical, dhan value_objects re-exports"
```

Expected: all green (backend baseline 687 passed + 1 pre-existing environmental failure allowed).

---

### Task 4: Anti-clone AST guard (locks every unification in)

**Files:**
- Test: `tests/quant/test_no_duplicate_types.py` (new)

**Interfaces:**
- Consumes: the canonical table from the spec (§2/§8).
- Produces: a CI guard — any future re-clone of `Bar`/`OHLC` outside sanctioned homes fails the suite; `Signal`/`Position` layer pairs pinned to exactly their sanctioned files.

- [ ] **Step 1: Write the guard (should pass — this locks current good state)**

Create `tests/quant/test_no_duplicate_types.py`:

```python
# tests/quant/test_no_duplicate_types.py
"""AST guard: sanctioned type homes. Re-cloning any unified type outside its
canonical home fails the suite. Layered model pairs (Signal, Position) are
sanctioned seams — pinned to exactly the listed files (spec §8)."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CANONICAL = {
    "Bar": ["quant/bars.py"],
}
# Layered-model pairs: exactly these files may define these class names.
LAYERED = {
    "Signal": [
        "quant/contracts/entities.py",
        "quant/decision/signal_builder.py",
    ],
    "Position": [
        "quant/contracts/entities.py",
        "quant/execution/order.py",
        "shared/entities/models.py",
    ],
    "OHLC": [
        "quant/contracts/value_objects.py",
        "brokers/broker/dhan/domain/value_objects.py",
    ],
}


def _class_defs(name: str) -> list[str]:
    hits = []
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith(("graphify-out/", ".worktrees/", "old.freebuff/")):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == name:
                hits.append(rel)
    return sorted(hits)


def test_bar_and_ohlc_have_single_definition():
    for name, allowed in CANONICAL.items():
        assert _class_defs(name) == allowed, (
            f"{name} cloned outside canonical home: {_class_defs(name)}"
        )


def test_layered_pairs_pinned_to_sanctioned_files():
    for name, allowed in LAYERED.items():
        assert _class_defs(name) == allowed, (
            f"{name} defined in unexpected files: {_class_defs(name)} — "
            f"sanctioned: {allowed}"
        )
```

- [ ] **Step 2: Run**

```bash
.venv/bin/python -m pytest tests/quant/test_no_duplicate_types.py -q
```

Expected: PASS. If `Signal`/`Position`/`Bar`/`OHLC` counts mismatch (e.g. a copy was missed in recon), the assertion output IS the true census — STOP and reconcile with the spec before proceeding.

- [ ] **Step 3: Commit**

```bash
git add tests/quant/test_no_duplicate_types.py
git commit -q -m "test: AST guard pinning canonical type homes and sanctioned layer pairs"
```

---

### Task 5: Delete test-only `detect_absorption`

**Files:**
- Delete: `quant/amt/orderflow/footprint.py::detect_absorption` (function only — keep the rest of footprint.py)
- Delete: `tests/quant/amt/orderflow/test_footprint_gaps.py`
- Test: `tests/quant/amt/orderflow/test_absorption_semantics_preserved.py` (new, conditional port — Step 1 decides)

**Interfaces:**
- Consumes: census — `detect_absorption` has zero production callers (only `test_footprint_gaps.py`).
- Produces: single absorption definition (`AbsorptionDetector`), AMT-meaningful assertions preserved.

- [ ] **Step 1: Read `tests/quant/amt/orderflow/test_footprint_gaps.py` and classify its assertions**

For each assertion decide: does it encode **absorption semantics** (aggression-without-price-move ⇒ absorption direction) worth keeping, or is it testing the dead function's dict-shaped contract? Semantics assertions get ported to `AbsorptionDetector` fixtures; contract-only assertions are dropped.

- [ ] **Step 2: If any semantics assertions exist, port them (TDD: write against `AbsorptionDetector` and confirm they pass or are fixed)**

```python
# tests/quant/amt/orderflow/test_absorption_semantics_preserved.py
"""Absorption semantics (AMT: aggression without price movement = hidden
opposite-side activity) survive the deletion of the test-only parallel impl."""
from quant.amt.orderflow.detectors import AbsorptionDetector, AbsorptionResult
# Populate fixtures mirroring the deleted test's candles; assert direction and
# pending/confirmed state transitions identical to the AbsorptionDetector tests.
```

(The concrete fixtures are copied from the deleted test in Step 1 — carry the numbers over verbatim.)

- [ ] **Step 3: Delete function + old test file, gate, commit**

```bash
# remove detect_absorption function block from quant/amt/orderflow/footprint.py
git rm -q tests/quant/amt/orderflow/test_footprint_gaps.py
.venv/bin/python -m pytest tests/quant/amt tests/quant -q 2>&1 | tail -1
.venv/bin/python -m pytest tests/system/test_quant_execution_e2e.py -q 2>&1 | tail -1
git add -A && git commit -q -m "refactor: delete test-only detect_absorption; AbsorptionDetector is the single absorption definition"
```

Expected: green. If removing the function breaks an import inside footprint.py (e.g. `__all__`), fix the export list in the same commit.

---

### Task 6: Symbol parsing single-home check (`_extract_underlying`)

**Files:**
- Possibly modify: `quant/amt/session/symbol_registry.py`, `quant/amt/session/futures_provider.py`
- Test: `tests/quant/amt/session/test_extract_underlying_parity.py` (new)

**Interfaces:**
- Consumes: canonical `ExchangeConfig.extract_underlying` (already used by `quant/runtime.py:1432`).
- Produces: parity proof that all symbol→underlying paths agree; deletion of any genuine duplicate logic.

- [ ] **Step 1: Write the parity test FIRST (it may already pass — that is the point: it locks agreement)**

Create `tests/quant/amt/session/test_extract_underlying_parity.py`:

```python
# tests/quant/amt/session/test_extract_underlying_parity.py
"""All symbol→underlying extractions must agree with ExchangeConfig — the
canonical parser used by runtime entry sizing."""
import pytest
from quant.contracts.exchange_config import ExchangeConfig
from quant.amt.session.futures_provider import FuturesProvider  # adjust import to real name

SYMBOLS = [
    "NIFTY 27 FEB 25500 CE",
    "BANKNIFTY 05 SEP 51000 PE",
    "CRUDEOIL 17 AUG 6100 CALL",
    "NATURALGAS SEP FUT",
    "NIFTY-27FEB-25500-CE",
    "NIFTY27FEB25500CE",
    "SILVERM 24 SEP 235000 PUT",
]

@pytest.mark.parametrize("symbol", SYMBOLS)
def test_futures_provider_matches_exchange_config(symbol):
    provider = FuturesProvider()  # adjust ctor to real signature
    assert provider._extract_underlying(symbol) == (
        ExchangeConfig.for_exchange("NSE").extract_underlying(symbol)
        or ExchangeConfig.for_exchange("MCX").extract_underlying(symbol)
    )
```

Adjust imports/ctor to the real names (read the module headers first). Run:

```bash
.venv/bin/python -m pytest tests/quant/amt/session/test_extract_underlying_parity.py -q
```

- [ ] **Step 2: Decision rule on failure**

If any case disagrees: the discrepancy is a live parsing bug. Diff the outputs, decide correctness against the symbol grammar in `quant/contracts/exchange_config.py` (and `docs/amt` symbol examples), fix `futures_provider._extract_underlying` (or the fallback), re-run to green. **Do not delete a fallback that a test proves load-bearing.**

- [ ] **Step 3: Read `symbol_registry._extract_underlying` body and apply the same rule**

If its logic duplicates `ExchangeConfig` semantics → replace the body with a `DEFAULT_REGISTRY`/`ExchangeConfig` call and rely on the parity test extended with one registry-routed case. If it is registry-specific logic (injected underlying sets, prefix-match over injected data) → keep it, and add a comment `# registry-specific; canonical parsing lives in ExchangeConfig.extract_underlying` so the next graph audit does not re-flag it.

- [ ] **Step 4: Gate + commit**

```bash
.venv/bin/python -m pytest tests/quant/amt/session tests/quant -q 2>&1 | tail -1
.venv/bin/python -m pytest tests/system/test_quant_execution_e2e.py -q 2>&1 | tail -1
git add -A && git commit -q -m "refactor/test: pin symbol→underlying parsing to ExchangeConfig (parity test)"
```

---

### Task 7: Broker port single home + adapter census

**Files:**
- Modify: `brokers/broker/ports.py` (receives `IBroker`), `quant/contracts/ports/broker.py` (becomes re-export)
- Census output: appended to this plan file as a comment block OR reported in the task report
- Test: `tests/quant/test_type_unification.py` (append identity test)

**Interfaces:**
- Consumes: `quant/contracts/ports/broker.py::IBroker` (3 methods: `execute_order`, `close_position`, `cancel_order`) — the port `PaperBrokerAdapter`/`DhanBrokerAdapter` implement.
- Produces: one file declaring all broker ports; adapters import from the canonical home.

- [ ] **Step 1: Move `IBroker` to `brokers/broker/ports.py`**

Append to `brokers/broker/ports.py` (imports adjusted to that module's existing style — it already imports `Instrument`, `Order`, `Position`, `Tick`):

```python
class IBroker(ABC):
    """Engine-side execution port (order entry/exit). Canonical definition —
    quant/contracts/ports/broker.py re-exports this."""

    # ... exact body copied verbatim from quant/contracts/ports/broker.py
```

Then replace the ENTIRE content of `quant/contracts/ports/broker.py` with:

```python
"""Engine-side broker port — canonical definition lives in
brokers/broker/ports.py (single home for all broker ports; spec §8)."""
from brokers.broker.ports import IBroker

__all__ = ["IBroker"]
```

- [ ] **Step 2: Identity test**

```python
def test_ibroker_single_home():
    import quant.contracts.ports.broker as cpb
    import brokers.broker.ports as bbp
    assert cpb.IBroker is bbp.IBroker
```

- [ ] **Step 3: Gate (backend suite critical here — adapters implement this port)**

```bash
.venv/bin/python -m pytest tests/quant -q 2>&1 | tail -1
.venv/bin/python -m pytest backend/tests/unit -q 2>&1 | tail -1
.venv/bin/python -m pytest tests/system/test_quant_execution_e2e.py -q 2>&1 | tail -1
git add -A && git commit -q -m "refactor: broker ports single home — IBroker defined in brokers/broker/ports.py, contracts re-exports"
```

- [ ] **Step 4: Backend adapter census (decision-gated)**

```bash
echo "=== who imports backend dhan_adapter ==="
grep -rln "adapters.dhan_adapter\|adapters import dhan_adapter\|from app.infrastructure.adapters.dhan_adapter" backend/ --include="*.py" | grep -v "dhan_adapter.py"
echo "=== dhan_adapter.py public methods ==="
grep -n "def [a-z]" backend/app/infrastructure/adapters/dhan_adapter.py | head -30
echo "=== same-name methods in brokers/broker/dhan ==="
grep -rn "def get_option_chain\|def stream_full\|def get_lot_size\|def get_historical" brokers/broker/dhan/application/broker.py brokers/broker/dhan/application/services/*.py | head -10
```

**Decision rule:** if every public method of `dhan_adapter.py` is (a) reachable via `DhanBroker`/`brokers/broker/dhan` services by its live callers, AND (b) its importers can be re-pointed with no behavior change → re-point callers, delete `dhan_adapter.py`, commit as `refactor: delete legacy backend dhan_adapter (superseded by brokers/broker/dhan)`. If ANY method has unique capability or a caller cannot be re-pointed without behavior change → KEEP the file, append the census verdict to `.superpowers/sdd/progress.md`, and stop this task (do not delete).

---

### Task 8: Split `brokers/broker/dhan/domain/entities.py` (144 nodes, 7 classes)

**Files:**
- Create: `brokers/broker/dhan/domain/instrument.py` (DhanInstrument)
- Create: `brokers/broker/dhan/domain/market_data.py` (DhanQuote, DhanTick, DhanOption, DhanOptionChain)
- Create: `brokers/broker/dhan/domain/orders.py` (DhanOrder, DhanPosition)
- Modify: `brokers/broker/dhan/domain/entities.py` (becomes re-export hub)

**Interfaces:**
- Produces: `entities.py` re-exports every class (identity preserved) — zero import churn for existing consumers; new code can import from the focused modules.

- [ ] **Step 1: Move class blocks verbatim into the three new files** (copy imports each file needs; no edits to class bodies)

- [ ] **Step 2: Replace `entities.py` class definitions with re-exports**

```python
"""Dhan domain entities — split by family; this module re-exports everything
so existing imports keep resolving to the same objects."""
from brokers.broker.dhan.domain.instrument import DhanInstrument
from brokers.broker.dhan.domain.market_data import (
    DhanOption,
    DhanOptionChain,
    DhanQuote,
    DhanTick,
)
from brokers.broker.dhan.domain.orders import DhanOrder, DhanPosition

__all__ = ["DhanInstrument", "DhanQuote", "DhanTick", "DhanOption", "DhanOptionChain", "DhanOrder", "DhanPosition"]
```

- [ ] **Step 3: Identity test (append to `tests/quant/test_type_unification.py`)**

```python
def test_dhan_entities_split_preserves_identity():
    import brokers.broker.dhan.domain.entities as ents
    import brokers.broker.dhan.domain.market_data as md
    assert ents.DhanQuote is md.DhanQuote
    assert ents.DhanOrder is __import__("brokers.broker.dhan.domain.orders", fromlist=["DhanOrder"]).DhanOrder
```

- [ ] **Step 4: Gate + commit**

```bash
.venv/bin/python -m pytest tests/quant backend/tests/unit -q 2>&1 | tail -1
.venv/bin/python -m pytest tests/system/test_quant_execution_e2e.py -q 2>&1 | tail -1
git add -A && git commit -q -m "refactor: split dhan domain entities by family (instrument/market_data/orders), re-export hub preserves identity"
```

---

### Task 9: Assess `settings_adapter.py` split (guarded — may conclude "keep")

**Files:**
- Possibly modify: `backend/app/config_models/settings_adapter.py`

**Interfaces:**
- Produces: a cohesion verdict; split only if it genuinely improves clarity.

- [ ] **Step 1: Cohesion assessment.** Read the file. Decision rule: it is ONE class (`SettingsAdapter`). If its methods cluster into ≥3 distinct config domains each with ≥5 methods and no shared private state between clusters → split into per-domain modules composed by `SettingsAdapter` (same re-export-hub pattern as Task 8). If it is one coherent translation layer over the settings model (methods share state/transforms) → KEEP, append verdict `settings_adapter: coherent single adapter, kept` to the task report. YAGNI governs; a split that fragments shared state is a regression, not an improvement.

- [ ] **Step 2: Gate + commit (only if split was performed)**

```bash
.venv/bin/python -m pytest backend/tests/unit -q 2>&1 | tail -1
git add -A && git commit -q -m "refactor: split settings_adapter by config domain (or no-op verdict recorded)"
```

---

### Task 10: Final verification (the "improve, not break" proof)

**Files:**
- None modified (verification only). Push.

- [ ] **Step 1: Full gates**

```bash
.venv/bin/python -m pytest tests/quant -q 2>&1 | tail -1
.venv/bin/python -m pytest backend/tests/unit -q 2>&1 | tail -1
.venv/bin/python -m pytest tests/system/test_quant_execution_e2e.py tests/quant/test_no_duplicate_types.py tests/quant/test_type_unification.py -q 2>&1 | tail -1
```

Expected: quant ≥1,761 green (may grow from new tests), backend 687 green (+1 pre-existing environmental), all unification/identity tests green.

- [ ] **Step 2: Runtime smoke (stack boot + health, same protocol as truthfulness branch)**

```bash
./start.sh > /dev/null 2>&1 & sleep 10
curl -s http://localhost:8090/health | head -c 200; echo
curl -s http://localhost:8090/health/ready | .venv/bin/python -c "import json,sys; d=json.load(sys.stdin); print('ready:', d['status'], '| recon:', d['checks'].get('startup_reconciliation_summary'))"
grep -c '"level": "ERROR"' backend/backend.log
```

Expected: status ok/ready, reconciliation `discrepancies=0`, 0 errors.

- [ ] **Step 3: Push**

```bash
git push -q origin feat/fractal-half-trend-signals
```

---

## Self-Review

**1. Spec coverage:** Spec targets 1-5 → Tasks 1 (dead code), 2-4 (type clones + guard), 5-6 (calc dedup), 7 (port single home + adapter census), 8-9 (god files). Census amendments from spec §8 honored (Signal/Position pinned not unified — Task 4; detect_absorption deleted not deduped — Task 5).
**2. Placeholder scan:** Census tasks (6 Step 3, 7 Step 4, 9) carry explicit decision rules with STOP conditions; test fixtures in Task 5 Step 2 are carried over verbatim from the deleted file (explicit instruction). No TBDs.
**3. Type consistency:** Identity-test style consistent across Tasks 2/3/4/7/8; canonical table matches spec §2/§8; guard file lists match census results verified in recon.
