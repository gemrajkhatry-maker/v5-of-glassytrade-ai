# Phase 2 — God Module Decomposition: Status & Plan

> Last updated: 2026-09-07
> Branch: `refactor/phase0-runtime-truth`
> Status: **Analysis complete. Pragmatic approach: document, don't decompose.**

---

## 1. Module Sizes

| Module | Lines | Methods/Functions | Classes |
|---|---|---|---|
| `quant/runtime.py` | 1,595 | ~45 methods | `QuantEngine` |
| `quant/multi_engine.py` | 1,528 | ~35 methods | `QuantCoordinator` |
| `quant/amt/analyzer.py` | 1,066 | ~30 methods | `AMTAnalyzer` |
| **Total** | **4,189** | **~110** | **3** |

---

## 2. Current Structure Analysis

### 2.1 `QuantEngine` (runtime.py) — 1,595 lines

**Already well-separated internal methods:**
- `_manage_tick_exit()` — tick-level fast SL/TP
- `_manage_exit()` — bar-level exits
- `_decide()` — entry decision gating
- `_on_bar_closed()` — bar close handling
- `startup_reconcile()` — startup recovery
- `_emit_merged_amt()` — AMT DTO merging
- `_release_partial_reserves()` — portfolio risk release
- `_book_full_close()` — full close accounting
- `_check_pyramid()` — pyramid add-on logic

**The god module problem is file size + import complexity, not lack of internal structure.**

### 2.2 `QuantCoordinator` (multi_engine.py) — 1,528 lines

**Already well-separated internal methods:**
- `_spawn_engine()` — engine construction
- `_stop_engine()` — engine teardown
- `start()` — lifecycle start
- `rescan()` — symbol rescan
- `switch_symbol()` — contract rotation
- `_start_eod_watchdog()` — EOD handling
- `crashed_engines()` — health check
- `stale_engines()` — staleness check
- `emergency_halt()` — panic stop

**Similar to QuantEngine — internal structure is clean, file size is the issue.**

### 2.3 `AMTAnalyzer` (amt/analyzer.py) — 1,066 lines

**Already has extracted sub-modules:**
- `quant/amt/orderflow/compute.py` — order flow calculations
- `quant/amt/profile/volume_profile.py` — volume profile
- `quant/amt/session/structure.py` — session structure

**The analyzer orchestrates these but still owns too much logic directly.**

---

## 3. Pragmatic Approach: Document, Don't Decompose

After careful analysis, a full decomposition is **not recommended** because:

1. **Internal structure is already clean** — all three modules have well-separated methods
2. **High risk, low benefit** — extracting collaborators would require passing ~20 parameters
3. **File size is the only real issue** — and that's a cosmetic concern, not a correctness one

### What we WILL do

1. **Document the architecture** — add module-level docstrings explaining the structure
2. **Add section comments** — make navigation easier
3. **Move truly independent helpers** — only if they're already well-isolated

### What we will NOT do

- Break the internal method structure
- Move every helper to a separate file
- Rewrite the run loop

---

## 4. Step-by-Step Plan

### Step 1: Add Architecture Documentation

Add module-level docstrings and section comments to all three modules.

### Step 2: Move Independent Helpers (if any)

Only move helpers that are already well-isolated and don't couple to the class.

### Step 3: Verify All Tests Pass

Full regression check.

---

## 5. Migration Gates

| Gate | Criteria |
|---|---|
| **C1** | All tests pass after documentation |
| **C2** | All tests pass after helper extraction |

---

**Next step:** Execute Step 1 — add architecture documentation.
