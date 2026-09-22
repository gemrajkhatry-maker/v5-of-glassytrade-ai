# Spec 1 Profile/VA Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans or implement task-by-task. Steps use checkbox syntax.

**Goal:** Honest VA expansion, flat-price incremental conservation, unclamped VWAP σ.

**Architecture:** Fix three pure functions/classes in profile layer; no gate/OMS changes.

**Tech Stack:** Python, pytest, existing `VolumeProfileLevel` / `IncrementalVolumeProfile` / `SessionVWAP`.

## Global Constraints

- No money-path / auction / TimesFM / options edits.
- Keep CRUDEOIL sparse-tail test green.
- Merge gate: `pytest tests/architecture tests/quant/amt tests/quant/decision tests/quant/execution tests/quant/runtime -q`

---

### Task 1: VA soft-shell desert false-stop

**Files:**
- Modify: `quant/amt/profile/volume_profile.py` (`compute_value_area` gap guard)
- Test: `tests/quant/amt/profile/test_volume_profile.py`

- [ ] Write failing test `test_soft_shell_reaches_value_area_pct`
- [ ] Change gap guard to `pair <= 0.0` only
- [ ] Confirm `test_sparse_far_tail_does_not_inflate_vah` still passes
- [ ] Commit

### Task 2: Flat-price incremental

**Files:**
- Modify: `quant/amt/profile/volume_profile.py` (`IncrementalVolumeProfile._full_rebuild`)
- Test: `tests/quant/amt/profile/test_volume_profile.py`

- [ ] Write failing test: identical candles → one bucket, volume conserved
- [ ] Fix `_full_rebuild` zero-range branch to single bucket
- [ ] Commit

### Task 3: Unclamped recent_stats σ

**Files:**
- Modify: `quant/amt/profile/vwap.py` (`recent_stats`)
- Test: new or existing vwap tests under `tests/quant/amt/`

- [ ] Write failing test: true std ≪ 0.1%×vwap is not floored to ≥1.0
- [ ] Remove proportional clamp in `recent_stats`
- [ ] Commit

### Task 4: Merge gate + debt doc

- [ ] Run merge gate
- [ ] Move Spec 1 rows to “addressed” in `docs/reviews/amt-math-debt-20260922.md`
