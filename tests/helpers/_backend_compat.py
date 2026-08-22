"""Load backend/tests helpers regardless of tests-package shadowing.

backend/tests/__init__.py makes ``tests`` resolve to backend/tests whenever
backend/ precedes the repo root on sys.path, hiding
backend/tests/helpers/market_data.py from the root package. This loader
fetches it by absolute path — immune to sys.path order.
"""

import importlib.util as _ilu
from pathlib import Path as _Path


def load_generate_market_data():
    here = Path(__file__).resolve()
    # this file: <root>/tests/helpers/_backend_compat.py → root is parents[2]
    candidates = [
        here.parents[2] / "backend" / "tests" / "helpers" / "market_data.py",
        here.parents[1] / "backend" / "tests" / "helpers" / "market_data.py",
    ]
    for src in candidates:
        if src.is_file():
            spec = _ilu.spec_from_file_location("_backend_market_data", str(src))
            mod = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.generate_market_data
    raise FileNotFoundError(f"market_data.py not found in {[str(c) for c in candidates]}")
