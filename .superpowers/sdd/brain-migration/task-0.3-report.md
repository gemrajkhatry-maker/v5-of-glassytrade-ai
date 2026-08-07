# Task 0.3 Report — Differential parity harness

**Status:** DONE_WITH_CONCERNS
**Commit:** `82b20a1` — `feat(quant): differential parity harness for brain migration`

## Summary

Created the differential parity harness `assert_parity` that all Phase 1 port tasks
import to prove a moved brain module behaves identically to its legacy twin
(full spec from `task-0.3-brief.md`).

## Files

- `tests/quant/parity.py` — harness (exact code from brief: recursive `_eq` with float
  `math.isclose` rel/abs tolerance, element-wise list/tuple, key-wise dict, dataclass
  field-by-field, exact for int/bool/str/None; diffs reported with a `path`).
- `tests/quant/parity/test_parity.py` — the 3 tests from the brief.

## RED → GREEN evidence

**RED (Step 2):** `python -m pytest tests/quant/parity -q` failed at collection:

```
ImportError while importing test module '.../tests/quant/parity/test_parity.py':
E   ImportError: cannot import name 'assert_parity' from 'tests.quant.parity'
    (tests/quant/parity/__init__.py)
```

**GREEN (Step 4):**

```
$ python -m pytest tests/quant/parity -q
...  [100%]
3 passed in 0.01s
```

**Full quant suite (Step 4 tail):**

```
$ python -m pytest tests/quant -q
...
281 passed in 1.53s
```

(278 pre-existing + 3 new parity tests.)

## Note on the brief's file list

The brief listed both `tests/quant/parity.py` **and** `tests/quant/parity/__init__.py`
(empty). These collide: the directory package shadows the sibling module, so
`from tests.quant.parity import assert_parity` resolves to the empty `__init__.py`
and the harness is unreachable (this is the RED seen above — a resolution error,
not merely "function missing"). Since `tests`/`tests.quant` are namespace packages
(no `__init__.py`), the fix was to **omit `tests/quant/parity/__init__.py`**, so
`tests.quant.parity` resolves to the module `tests/quant/parity.py` exactly as the
brief's import contract requires. The harness module and its exact code are untouched.

## Concerns

1. **Deviation from literal file list:** `tests/quant/parity/__init__.py` was not
   created (it is impossible to have both it and `parity.py` resolve the same import
   name; the empty package breaks the import). All other `tests/quant/*` subdirs are
   packages, so `tests/quant/parity/` is the only non-package test dir — harmless, but
   worth noting for later tasks.
2. No other concerns; behavior matches the brief spec exactly.

## Follow-up fix — type drift detection (Important finding)

**Commit:** `c305e28` — `fix(quant): parity harness rejects float/int and bool/int type drift`

## What changed

The scalar fallthrough in `_eq` used bare `a == b`, so Python numeric loosening let
`1.0 == 1` and `True == 1` pass silently — float→int and bool→int type drift was not
caught, violating the requirement that ints/bool/str/None compare exactly.

- `tests/quant/parity.py`: fallthrough now asserts `type(a) is type(b)` (raising
  `AssertionError` with the diff path on drift) before `a == b`. Float
  `math.isclose` and the list/tuple, dict, and dataclass recursion branches are
  unchanged. No other changes.
- `tests/quant/parity/test_parity.py`: added `test_parity_rejects_float_int_type_drift`
  and `test_parity_rejects_bool_int_type_drift` (both expect `AssertionError`).

## Test command + output

```
$ /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant/parity -q
.....  [100%]
5 passed in 0.01s
```

Full quant suite:

```
$ /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q
...
283 passed in 1.54s
```
