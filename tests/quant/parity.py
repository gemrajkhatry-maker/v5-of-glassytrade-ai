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
