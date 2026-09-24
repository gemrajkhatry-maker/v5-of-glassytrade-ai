"""Shared test fixtures and configuration.

This conftest.py provides:
1. Project root on sys.path so 'shared' and 'config' packages resolve
2. Mock for the shared module's subpackages before any imports that depend on them
3. Test environment setup
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

# Before any LightGBM/MLX imports: avoid OpenMP runtime aborts in mixed native stacks.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")

# ---------------------------------------------------------------------------
# Path setup — add project root to sys.path so packages like 'shared' and
# 'config' (which live at the monorepo root, not inside backend/) resolve.
# ---------------------------------------------------------------------------
_project_root = str(
    Path(__file__).resolve().parent.parent.parent  # backend/tests → backend → project root
)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Also ensure backend/ is importable (sibling of project root relative to
# tests/). APPEND, never insert(0): backend/tests/__init__.py creates a
# competing ``tests`` package and inserting backend first shadows the root
# tests/ package (helpers like synthetic.py vanish mid-collection).
_backend_root = str(Path(__file__).resolve().parent.parent)  # backend/
if _backend_root not in sys.path:
    sys.path.append(_backend_root)
# Re-assert root-first in case any prior import inserted backend ahead.
_root = str(Path(__file__).resolve().parent.parent.parent)
if _root in sys.path:
    sys.path.remove(_root)
sys.path.insert(0, _root)

# ---------------------------------------------------------------------------
# No global mocks needed — stub modules provide importable types.
# Tests that require network/hardware should mock at the test level.
# ---------------------------------------------------------------------------

# ``backend/tests`` is a package named ``tests`` and can shadow the root
# ``tests`` package while pytest imports plugins. Load the shared fixture by
# path so backend-only invocations still receive the same profile.
_hermetic_path = Path(_project_root) / "tests" / "helpers" / "hermetic.py"
_hermetic_spec = importlib.util.spec_from_file_location(
    "glassytrade_hermetic_profile", _hermetic_path
)
if _hermetic_spec is None or _hermetic_spec.loader is None:
    raise RuntimeError(f"could not load hermetic profile: {_hermetic_path}")
_hermetic_module = importlib.util.module_from_spec(_hermetic_spec)
_hermetic_spec.loader.exec_module(_hermetic_module)
hermetic_test_profile = _hermetic_module.hermetic_test_profile
pytest_configure = _hermetic_module.pytest_configure

