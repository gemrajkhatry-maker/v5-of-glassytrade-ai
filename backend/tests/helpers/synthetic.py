"""Path-order-proof re-export of the root tests/helpers/synthetic.py."""

import importlib.util as _ilu
from pathlib import Path as _P

_src = _P(__file__).resolve().parents[3] / "tests" / "helpers" / "synthetic.py"
_spec = _ilu.spec_from_file_location("_root_helpers_synthetic", str(_src))
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("_")})
