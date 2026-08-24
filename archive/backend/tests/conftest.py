"""Shared test fixtures and configuration.

This conftest.py provides:
1. Project root on sys.path so 'shared' and 'config' packages resolve
2. Mock for the shared module's subpackages before any imports that depend on them
3. Test environment setup
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

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

# Also ensure backend/ is importable (sibling of project root relative to tests/)
_backend_root = str(Path(__file__).resolve().parent.parent)  # backend/
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

# ---------------------------------------------------------------------------
# No global mocks needed — stub modules provide importable types.
# Tests that require network/hardware should mock at the test level.
# ---------------------------------------------------------------------------
