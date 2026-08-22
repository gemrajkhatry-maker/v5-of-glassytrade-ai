"""Repo root conftest — exposes the backend ``app`` package to repo-root quant tests.

Some quant/system tests import live backend application modules (e.g.
``app.application.services.quant_bridge``), so the ``backend/`` root must be
importable from the repo root.

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

# Root must PRECEDE backend on sys.path: backend/tests/__init__.py creates a
# competing ``tests`` package that shadows tests/helpers/synthetic.py etc.
# (the source of every 'No module named tests.helpers' collection error).
_repo = str(Path(__file__).resolve().parent)
if _repo in sys.path:
    sys.path.remove(_repo)
sys.path.insert(0, _repo)
