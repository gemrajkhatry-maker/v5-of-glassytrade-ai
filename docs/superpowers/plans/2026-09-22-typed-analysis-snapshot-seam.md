# Typed Analysis Snapshot Seam Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Demote the camelCase AMT DTO from the live money-path bus to a WS-only adapter; decision and exit read a typed `AnalysisSnapshot` built from `AMTResult`.

**Architecture:** Introduce a frozen `AnalysisSnapshot` that wraps `AMTResult` plus `asof_time` and once-derived stacked-imbalance fields. `AMTEngine` owns `last_snapshot` and still emits `last_amt_dto` via `amt_result_to_dto` for WebSocket / `AmtUpdated` only. `DecisionContextBuilder` and exit/position paths prefer the snapshot; dict DTO becomes a transitional fallback then a hard error on money-path call sites. Do not invent a second parallel field catalog — project from `AMTResult` attributes (snake_case).

**Tech Stack:** Python 3.11+, pytest, existing `AMTResult` / `DecisionContext` / `AMTEngine`.

## Global Constraints

- Zero-parity: live / paper / replay share the same snapshot path.
- No Gate1–4 policy changes, no auction / TimesFM / options scanner / sizing changes except type of AMT input.
- WS frontend contract unchanged: `amt_result_to_dto` output shape stays camelCase.
- ADR-0001 / ADR-0002 / ADR-0003 untouched.
- Merge gate after each vertical task: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture tests/quant/amt tests/quant/decision tests/quant/execution tests/quant/runtime -q`
- Commit only when the human asks (plan steps still list commits for agentic runners who were told to commit).

## File map

| File | Role |
|------|------|
| Create `quant/amt/snapshot.py` | `AnalysisSnapshot` + `from_result` + stacked-imbalance derivation (moved once from dto) |
| Modify `quant/amt/dto.py` | Keep WS adapter; import stacked helper from snapshot or delete duplicate |
| Modify `quant/amt_engine.py` | Store `_last_snapshot`; stamp `asof_time`; keep `_last_amt_dto` for WS |
| Modify `quant/decision/context_builder.py` | `build(..., snapshot=...)` primary; map from `AMTResult` fields |
| Modify `quant/engine/decision_loop.py` | Pass snapshot into builder / advisor |
| Modify `quant/execution/exit_checks.py` | Read stacked imbalance from snapshot or typed fields |
| Modify `quant/execution/exits.py` | Accept snapshot; stop dual camel/snake dto.get |
| Modify `quant/position_manager.py` | Prefer snapshot for market_state / VWAP / leg LVN |
| Modify `quant/amt/profile/leg_lvn.py` | Accept `AMTResult` or snapshot; stop requiring `legLvns` wire key |
| Modify `quant/runtime.py` / tick emit path | WS still gets dto; decide/exit get snapshot |
| Test `tests/quant/amt/test_analysis_snapshot.py` | New |
| Modify `tests/architecture/test_amt_dto_contract.py` | Ratchet: money-path readers may use snapshot; dto keys remain for WS |

---

### Task 1: AnalysisSnapshot type + single stacked-imbalance producer

**Files:**
- Create: `quant/amt/snapshot.py`
- Modify: `quant/amt/dto.py` (call shared helper; delete local `_derive_stacked_imbalance` body)
- Test: `tests/quant/amt/test_analysis_snapshot.py`

**Interfaces:**
- Consumes: `AMTResult`, `FootprintCandle` / `FootprintLevel` from `quant.contracts.value_objects`
- Produces:
  - `AnalysisSnapshot(result: AMTResult, asof_time: str, stacked_imbalance_direction: str, stacked_imbalance_magnitude: int, stacked_imbalance_low: float, stacked_imbalance_high: float)`
  - `def derive_stacked_imbalance(footprints: dict[str, FootprintCandle]) -> tuple[str, int, float, float]`
  - `def analysis_snapshot_from_result(result: AMTResult, asof_time: str) -> AnalysisSnapshot`

- [ ] **Step 1: Write the failing test**

```python
# tests/quant/amt/test_analysis_snapshot.py
from quant.amt.snapshot import analysis_snapshot_from_result, derive_stacked_imbalance
from quant.contracts.value_objects import AMTResult, FootprintCandle, FootprintLevel


def test_snapshot_carries_result_and_asof_time():
    result = AMTResult(market_state="BALANCED", poc=100.0, value_area_high=101.0, value_area_low=99.0)
    snap = analysis_snapshot_from_result(result, asof_time="2026-09-22T10:00:00+05:30")
    assert snap.result is result
    assert snap.asof_time == "2026-09-22T10:00:00+05:30"


def test_derive_stacked_imbalance_matches_three_buy_stack():
    levels = tuple(
        FootprintLevel(price=100.0 + i, bid=1, ask=10, delta=9, imbalance=True, stacked=True)
        for i in range(3)
    )
    fps = {"t1": FootprintCandle(time="t1", levels=levels, poc_price=101.0, total_delta=27.0, step_price=1.0)}
    direction, mag, lo, hi = derive_stacked_imbalance(fps)
    assert direction == "BUY"
    assert mag >= 3
    assert lo <= hi
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/test_analysis_snapshot.py -q --tb=short`  
Expected: FAIL with `ModuleNotFoundError: quant.amt.snapshot`

- [ ] **Step 3: Write minimal implementation**

```python
# quant/amt/snapshot.py
from __future__ import annotations
from dataclasses import dataclass
from quant.contracts.value_objects import AMTResult, FootprintCandle


def derive_stacked_imbalance(footprints: dict[str, FootprintCandle]) -> tuple[str, int, float, float]:
    if not footprints:
        return "", 0, 0.0, 0.0
    latest_key = max(footprints.keys())
    levels = footprints[latest_key].levels
    best_dir, best_n, best_prices = "", 0, []
    run_dir, run_n, run_prices = "", 0, []
    for lvl in levels:
        if not lvl.stacked:
            run_dir, run_n, run_prices = "", 0, []
            continue
        d = "BUY" if lvl.ask > lvl.bid else "SELL"
        px = float(lvl.price)
        if d != run_dir:
            run_dir, run_n, run_prices = d, 1, [px]
        else:
            run_n += 1
            run_prices.append(px)
        if run_n > best_n:
            best_dir, best_n, best_prices = run_dir, run_n, list(run_prices)
    if best_n < 3 or not best_prices:
        return "", 0, 0.0, 0.0
    return best_dir, best_n, min(best_prices), max(best_prices)


@dataclass(frozen=True)
class AnalysisSnapshot:
    result: AMTResult
    asof_time: str
    stacked_imbalance_direction: str = ""
    stacked_imbalance_magnitude: int = 0
    stacked_imbalance_low: float = 0.0
    stacked_imbalance_high: float = 0.0


def analysis_snapshot_from_result(result: AMTResult, asof_time: str) -> AnalysisSnapshot:
    d, n, lo, hi = derive_stacked_imbalance(result.footprints or {})
    return AnalysisSnapshot(
        result=result,
        asof_time=asof_time,
        stacked_imbalance_direction=d,
        stacked_imbalance_magnitude=n,
        stacked_imbalance_low=lo,
        stacked_imbalance_high=hi,
    )
```

In `quant/amt/dto.py`, replace `_derive_stacked_imbalance` body with a call to `derive_stacked_imbalance` so WS dto and snapshot share one producer.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/test_analysis_snapshot.py tests/architecture/test_amt_dto_contract.py -q`  
Expected: PASS

- [ ] **Step 5: Commit** (only if human requested commits)

```bash
git add quant/amt/snapshot.py quant/amt/dto.py tests/quant/amt/test_analysis_snapshot.py
git commit -m "feat(amt): AnalysisSnapshot with single stacked-imbalance producer"
```

---

### Task 2: AMTEngine owns last_snapshot

**Files:**
- Modify: `quant/amt_engine.py`
- Test: `tests/quant/amt/test_amt_engine_properties.py` (extend) or `tests/quant/amt/test_analysis_snapshot.py`

**Interfaces:**
- Consumes: `analysis_snapshot_from_result`, `amt_result_to_dto`
- Produces:
  - `AMTEngine.last_snapshot -> AnalysisSnapshot | None`
  - `AMTEngine.last_amt_dto` still returns camelCase dict for WS (derived from snapshot.result)
  - `analyze(bar) -> dict` return type unchanged for callers that emit WS / AmtUpdated (dto still returned)

- [ ] **Step 1: Write the failing test**

```python
def test_analyze_stores_last_snapshot_with_asof_time(monkeypatch):
    from quant.amt_engine import AMTEngine
    # Use existing engine test fixtures in test_amt_engine_properties / seed tests.
    # Minimal: after analyze with a real analyzer path, last_snapshot.result.poc > 0
    # and last_snapshot.asof_time == last_amt_dto["time"]
```

Concrete assertion against the engine under test already used in `tests/quant/amt/test_amt_engine_properties.py`:

```python
def test_last_snapshot_matches_dto_time_and_poc():
    eng = ...  # same construction as existing property tests
    # after one successful analyze:
    assert eng.last_snapshot is not None
    assert eng.last_snapshot.asof_time == eng.last_amt_dto["time"]
    assert eng.last_snapshot.result.poc == eng.last_amt_dto["poc"]
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL `AttributeError: last_snapshot`

- [ ] **Step 3: Write minimal implementation**

In `AMTEngine.__init__`: `self._last_snapshot: AnalysisSnapshot | None = None`

On successful analyze / seed analyze:

```python
snap = analysis_snapshot_from_result(result, asof_time=iso_now)
dto = amt_result_to_dto(result)
dto["time"] = iso_now
# stacked fields already in dto via shared helper
with self._amt_lock:
    self._last_snapshot = snap
    self._last_amt_dto = dto
```

```python
@property
def last_snapshot(self) -> AnalysisSnapshot | None:
    with self._amt_lock:
        return self._last_snapshot
```

Rollover / reset clears both `_last_snapshot` and `_last_amt_dto` consistently.

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/test_amt_engine_properties.py tests/quant/amt/test_analysis_snapshot.py tests/quant/amt/test_spec4_seed_multitf.py -q`  
Expected: PASS (adjust test file names if Spec 4 tests live elsewhere — search `test_.*seed`)

- [ ] **Step 5: Commit** (if requested)

```bash
git add quant/amt_engine.py tests/quant/amt/
git commit -m "feat(amt): AMTEngine stores typed last_snapshot beside WS dto"
```

---

### Task 3: DecisionContextBuilder prefers AnalysisSnapshot

**Files:**
- Modify: `quant/decision/context_builder.py`
- Test: `tests/quant/decision/test_context_builder_behavior.py`

**Interfaces:**
- Consumes: `AnalysisSnapshot`
- Produces: `DecisionContextBuilder.build(..., snapshot: AnalysisSnapshot | None = None, amt_dto: dict | None = None)`  
  - If `snapshot` set, read `snapshot.result.*` (and stacked fields from snapshot).  
  - If only `amt_dto` set, keep current behavior (compat for tests).  
  - Prefer snapshot when both provided.

- [ ] **Step 1: Write the failing test**

```python
def test_build_from_snapshot_does_not_need_camel_dto():
    result = AMTResult(
        market_state="BALANCED", poc=100.0, value_area_high=102.0, value_area_low=98.0,
        session_vwap=100.0, cvd_slope=1.5, cvd_divergence="NONE",
    )
    snap = analysis_snapshot_from_result(result, "2026-09-22T10:00:00+05:30")
    ctx = DecisionContextBuilder().build(
        symbol="NIFTY", bar=bar_fixture, market="NSE",
        snapshot=snap, amt_dto={},  # empty dto must not wipe typed fields
        best_bid=99.9, best_ask=100.1, position=None,
        cooldown_remaining_sec=0.0,
    )
    assert ctx.poc == 100.0
    assert ctx.vah == 102.0
    assert ctx.cvd_slope == 1.5
```

(Adapt `build` kwargs to the real signature in `context_builder.py:639`.)

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL on unexpected kwarg `snapshot` or wrong values from empty dto.

- [ ] **Step 3: Write minimal implementation**

Add optional `snapshot: AnalysisSnapshot | None = None` to `build`. When present:

```python
r = snapshot.result
# use r.value_area_high instead of df(amt_dto, "valueAreaHigh")
# use snapshot.stacked_imbalance_* instead of _latest_stacked_imbalance(amt_dto)
# use r.aggressive_prints instead of _print_levels_from_dto
```

Keep `_df`/`_ds` path when `snapshot is None` for existing unit tests that only pass dicts.

Fix known honesty bug while mapping: `vwap_std` must come from band width / true σ if available on result — do **not** map `vwapDeviationSigmas` into `ctx.vwap_std` when building from snapshot. Use `abs(r.vwap_upper_1 - r.session_vwap)` as σ when `session_vwap` and bands are set; else `0.0`. (Anti-climax already wants price-unit σ.)

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_context_builder_behavior.py tests/quant/decision/test_decision_service.py -q`  
Expected: PASS

- [ ] **Step 5: Commit** (if requested)

```bash
git add quant/decision/context_builder.py tests/quant/decision/
git commit -m "feat(decision): ContextBuilder builds from AnalysisSnapshot"
```

---

### Task 4: DecisionLoop + runtime decide path pass snapshot

**Files:**
- Modify: `quant/engine/decision_loop.py`
- Modify: `quant/runtime.py` (only decide wiring / `_decide` args if needed)
- Modify: `quant/engine/tick_handler.py` (pass through; freshness still uses dto time **or** `snapshot.asof_time`)
- Test: `tests/quant/test_decision_loop.py`, `tests/quant/test_tick_handler.py`

**Interfaces:**
- Consumes: `amt_engine.last_snapshot`
- Produces: `_build_context` / `_build_decision` accept snapshot; dto retained for advisor/WS notify if still required

- [ ] **Step 1: Write the failing test**

Extend tick freshness test: when `last_snapshot.asof_time` is fresh, decide fires even if callers stop stuffing camelCase into decide — or assert `DecisionContextBuilder.build` was called with `snapshot=`.

```python
def test_decide_uses_engine_last_snapshot(monkeypatch):
    # monkeypatch DecisionContextBuilder.build to capture kwargs
    ...
    assert captured.get("snapshot") is engine._amt_engine.last_snapshot
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL (snapshot not passed)

- [ ] **Step 3: Write minimal implementation**

In `decision_loop._build_context`:

```python
snap = getattr(self._amt_engine, "last_snapshot", None)
return DecisionContextBuilder().build(..., snapshot=snap, amt_dto=amt_dto or {})
```

In `tick_handler._decide_if_macro_fresh`, prefer:

```python
dto_time = parse_bar_time(
    (amt_dto or {}).get("time")
    or getattr(getattr(self._amt_engine, "last_snapshot", None), "asof_time", None)
)
```

Do not change Gate policy.

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/test_decision_loop.py tests/quant/test_tick_handler.py tests/quant/runtime/test_1min_trigger.py -q`  
Expected: PASS

- [ ] **Step 5: Commit** (if requested)

```bash
git add quant/engine/decision_loop.py quant/engine/tick_handler.py quant/runtime.py tests/quant/
git commit -m "feat(engine): decide path threads AnalysisSnapshot"
```

---

### Task 5: Exit + PositionManager read snapshot (or result), not camelCase dual keys

**Files:**
- Modify: `quant/execution/exit_checks.py`
- Modify: `quant/execution/exits.py`
- Modify: `quant/position_manager.py`
- Modify: `quant/amt/profile/leg_lvn.py`
- Test: `tests/quant/execution/test_exits.py`, `tests/quant/execution/test_exit_source.py`, existing PM tests

**Interfaces:**
- Consumes: `AnalysisSnapshot | AMTResult | dict` (dict last)
- Produces:
  - `check_stacked_imbalance_tighten(position, snapshot_or_dto)` reads `stacked_imbalance_direction` from snapshot attrs first
  - `resolve_leg_lvn(result_or_dto, close)` reads `leg_lvns` from `AMTResult.leg_lvns` when typed

- [ ] **Step 1: Write the failing test**

```python
def test_stacked_imbalance_tighten_reads_snapshot_fields():
    snap = AnalysisSnapshot(
        result=AMTResult(market_state="BALANCED", poc=100, value_area_high=101, value_area_low=99),
        asof_time="t",
        stacked_imbalance_direction="SELL",
        stacked_imbalance_magnitude=3,
    )
    # long position; opposing SELL stack → tighten decision true (per current rule contract)
    decision = check_stacked_imbalance_tighten(long_position, snap)
    assert decision.should_exit is True  # or whatever current ExitDecision shape is
```

Read current `check_stacked_imbalance_tighten` return type before asserting — match existing tests in `test_exits.py`.

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL type/attribute errors on snapshot

- [ ] **Step 3: Write minimal implementation**

```python
def _si_fields(src) -> tuple[str, int]:
    if hasattr(src, "stacked_imbalance_direction"):
        return str(src.stacked_imbalance_direction), int(src.stacked_imbalance_magnitude)
    if hasattr(src, "result"):  # nested unlikely
        ...
    dto = src if isinstance(src, dict) else {}
    return (
        str(dto.get("stackedImbalanceDirection") or dto.get("stacked_imbalance_direction") or ""),
        int(dto.get("stackedImbalanceMagnitude") or dto.get("stacked_imbalance_magnitude") or 0),
    )
```

`PositionManager.manage_exit`: accept optional `snapshot`; if None, `snapshot = self._amt_engine.last_snapshot` via injected getter `get_snapshot` parallel to `get_amt_dto`. Prefer snapshot for `market_state` / `session_vwap`:

```python
r = snapshot.result if snapshot else None
raw_ms = (r.market_state if r else str(amt_dto.get("marketState") or "BALANCED")).upper()
```

`resolve_leg_lvn`:

```python
def resolve_leg_lvn(src, close_px: float) -> LegLVNResolution:
    if hasattr(src, "result"):
        levels = list(src.result.leg_lvns or ())
    elif hasattr(src, "leg_lvns"):
        levels = list(src.leg_lvns or ())
    else:
        raw = (src or {}).get("legLvns")
        levels = list(raw or [])
    ...
```

Wire `get_snapshot` in runtime when constructing PositionManager.

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution tests/quant/test_exit_manager.py -q`  
Expected: PASS

- [ ] **Step 5: Commit** (if requested)

```bash
git add quant/execution/exit_checks.py quant/execution/exits.py quant/position_manager.py quant/amt/profile/leg_lvn.py quant/runtime.py tests/quant/
git commit -m "feat(execution): exits and PM prefer AnalysisSnapshot over dto keys"
```

---

### Task 6: Architecture ratchet + merge gate

**Files:**
- Modify: `tests/architecture/test_amt_dto_contract.py` (document WS-only readers; add note that decision_loop/exits may use snapshot)
- Create: `tests/architecture/test_analysis_snapshot_seam.py` — assert `DecisionContextBuilder.build` signature accepts `snapshot`; assert `AMTEngine` has `last_snapshot`
- Optional: fail if `quant/decision/gates_*.py` contains `valueAreaHigh` string (gates should use DecisionContext only — already true; skip if grepping is flaky)

**Interfaces:** none new

- [ ] **Step 1: Write the failing ratchet test**

```python
def test_amt_engine_exposes_last_snapshot_property():
    from quant.amt_engine import AMTEngine
    assert hasattr(AMTEngine, "last_snapshot")


def test_context_builder_build_accepts_snapshot_param():
    import inspect
    from quant.decision.context_builder import DecisionContextBuilder
    sig = inspect.signature(DecisionContextBuilder.build)
    assert "snapshot" in sig.parameters
```

- [ ] **Step 2: Run — should pass after Tasks 2–3; if run early, fails**

- [ ] **Step 3: Full merge gate**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture tests/quant/amt tests/quant/decision tests/quant/execution tests/quant/runtime -q`  
Expected: all pass (aside from pre-existing skips)

- [ ] **Step 4: Commit** (if requested)

```bash
git add tests/architecture/
git commit -m "test(arch): ratchet AnalysisSnapshot seam on engine and builder"
```

---

## Out of scope (follow-on plans)

- Candidate 2 EdgeEvaluator / SetupCandidate
- Candidate 3 exit ownership fold
- Deleting `GatePipeline` / TickHandler shells
- Removing `amt_dto` parameter entirely from every test fixture (compat fallback remains until a cleanup plan)
- Changing WS field names

## Spec coverage self-check

| Candidate 1 requirement | Task |
|-------------------------|------|
| Typed seam analysis→decision→execution | 1–5 |
| DTO WS-only adapter | 2 (dto still produced), 4–5 (money path prefers snapshot) |
| Single stacked-imbalance producer | 1 |
| Locality / one map per field | 3 maps from `AMTResult` |
| Deletion test (dto removable from decide) | 3–4 with empty dto + snapshot |
| No money-path policy change | Global constraints |

## Placeholder scan

No TBD / "add validation" / "similar to Task N" left unresolved. Commit steps are optional per human commit policy.
