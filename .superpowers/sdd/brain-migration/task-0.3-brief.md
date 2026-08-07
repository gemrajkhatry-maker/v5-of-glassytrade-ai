# Task 0.3 — Differential parity harness

**From:** docs/superpowers/plans/2026-08-06-quant-brain-migration.md — Phase 0, Task 0.3

**Goal:** Build the parity-testing helper that every Phase 1 port task uses to prove a moved brain module behaves identically to its legacy counterpart. `assert_parity` runs a legacy function and a quant function on identical inputs and compares outputs recursively with a float tolerance.

**Files:**
- Create: `tests/quant/parity.py`
- Create: `tests/quant/parity/test_parity.py`
- Create: `tests/quant/parity/__init__.py` (empty)

**Interfaces:**
- Produces (every Phase 1 track imports this):
```python
# tests/quant/parity.py
def assert_parity(legacy_fn, quant_fn, *args, tol: float = 1e-6, **kwargs) -> None:
    """Run both fns on identical args; assert equal outputs.
    Floats compared with relative tolerance `tol`; ints/bool/str/None exact;
    dataclasses compared field-by-field recursively; tuples/lists element-wise;
    dicts key-wise. Raises AssertionError with a diff on mismatch."""
```

## Steps

- [ ] **Step 1: Write failing tests** `tests/quant/parity/test_parity.py`:
```python
import pytest

from tests.quant.parity import assert_parity


def _legacy_near():
    return {"x": 1.0}


def _quant_near():
    return {"x": 1.0000001}


def _legacy_far():
    return {"x": 1.0}


def _quant_far():
    return {"x": 2.0}


def test_parity_passes_for_near_equal():
    assert_parity(_legacy_near, _quant_near)


def test_parity_raises_for_mismatch():
    with pytest.raises(AssertionError):
        assert_parity(_legacy_far, _quant_far)


def test_parity_nested_structures():
    leg = {"a": [1, 2.00000001, (3, "x")], "b": {"c": None}, "d": True}
    qnt = {"a": [1, 2.0, (3, "x")], "b": {"c": None}, "d": True}
    assert_parity(lambda: leg, lambda: qnt)
```

- [ ] **Step 2: Run, verify FAIL** — `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant/parity -q` (RED: `assert_parity` not defined).

- [ ] **Step 3: Implement** `tests/quant/parity.py`:
```python
"""Differential parity harness — prove a moved brain module matches its legacy twin.

Phase 1 port tasks import ``assert_parity`` and compare the legacy module (via its
re-export shim) against the ported ``quant.*`` module on identical inputs.
"""
from __future__ import annotations

import math
from dataclasses import fields, is_dataclass
from typing import Any, Callable


def _eq(a: Any, b: Any, tol: float, path: str) -> None:
    if isinstance(a, float) and isinstance(b, float):
        assert math.isclose(a, b, rel_tol=tol, abs_tol=tol), f"{path}: {a} != {b} (tol {tol})"
        return
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        assert type(a) is type(b) or type(a).__name__ == type(b).__name__, f"{path}: {type(a)} != {type(b)}"
        assert len(a) == len(b), f"{path}: len {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            _eq(x, y, tol, f"{path}[{i}]")
        return
    if isinstance(a, dict) and isinstance(b, dict):
        assert set(a) == set(b), f"{path}: key diff {set(a) ^ set(b)}"
        for k in a:
            _eq(a[k], b[k], tol, f"{path}.{k}")
        return
    if is_dataclass(a) and is_dataclass(b):
        assert type(a).__name__ == type(b).__name__, f"{path}: {type(a).__name__} != {type(b).__name__}"
        for f in fields(a):
            _eq(getattr(a, f.name), getattr(b, f.name), tol, f"{path}.{f.name}")
        return
    assert a == b, f"{path}: {a!r} != {b!r}"


def assert_parity(legacy_fn: Callable, quant_fn: Callable, *args: Any, tol: float = 1e-6, **kwargs: Any) -> None:
    _eq(legacy_fn(*args, **kwargs), quant_fn(*args, **kwargs), tol, "root")
```

- [ ] **Step 4: Run, verify PASS** — `cd /Users/apple/Documents/v5-of-glassytrade-ai && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant/parity -q` → 3 passed. Then the full quant suite: `... -m pytest tests/quant -q` → 278 passed (146 + 132 ported).

- [ ] **Step 5: Commit** `feat(quant): differential parity harness for brain migration`

## Report contract

Write your report to `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/task-0.3-report.md`: commit hash, RED→GREEN evidence, final test tails. Return: status, commit, one-line test summary, concerns.
