"""Backend root conftest — ensures project-level packages are importable.

This file runs before any test collection, adding the project root to
sys.path so that packages like ``shared`` and ``config`` (which live at
the monorepo root, not inside backend/) can be imported.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

_backend_root = str(Path(__file__).resolve().parent)
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)
