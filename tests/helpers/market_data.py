"""Re-export backend/tests/helpers/market_data — immune to path order.

backend/tests/__init__.py makes ``tests`` resolve to backend/tests whenever
backend/ precedes the repo root on sys.path, hiding that copy. Loading by
absolute path works in every ordering.
"""

import importlib.util as _ilu
from pathlib import Path as _Path


def _load():
    here = _Path(__file__).resolve()
    candidates = [
        here.parents[2] / "backend" / "tests" / "helpers" / "market_data.py",
    ]
    for src in candidates:
        if src.is_file():
            spec = _ilu.spec_from_file_location("_backend_market_data", str(src))
            mod = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            globals().update(
                {k: v for k, v in vars(mod).items() if not k.startswith("_")}
            )
            return
    raise FileNotFoundError("backend/tests/helpers/market_data.py not found")


_load()
