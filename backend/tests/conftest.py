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
