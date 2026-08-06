"""Repo root conftest — exposes the backend legacy package to quant parity tests.

Parity tests import moved brain modules via their re-export shim at the legacy
path (``app.domain.*``), so the ``backend/`` root must be importable from the
repo root. Same approach as tests/system/*.

Appended (not prepended) so that ``backend/tests/`` cannot shadow the repo-root
``tests`` package.
"""

import sys
from pathlib import Path

_root = Path(__file__).resolve()
for parent in (_root, *_root.parents):
    backend = parent / "backend"
    if backend.is_dir() and (backend / "app").is_dir():
        _backend = str(backend)
        break
else:
    raise RuntimeError("could not locate backend/ root from conftest")

if _backend not in sys.path:
    sys.path.append(_backend)
