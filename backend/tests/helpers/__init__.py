"""Re-export root tests/helpers so BOTH package resolutions work.

When backend/ precedes the repo root on sys.path, ``tests`` resolves to this
package and helpers like synthetic.py vanish (the source of recurring
"No module named tests.helpers" collection errors). Each module here loads
its root twin by absolute path and re-exports its public names.
"""

import importlib.util as _ilu
from pathlib import Path as _P

_ROOT_HELPERS = _P(__file__).resolve().parents[3] / "tests" / "helpers"


def _load(name: str) -> None:
    src = _ROOT_HELPERS / (name + ".py")
    if not src.is_file():
        return
    spec = _ilu.spec_from_file_location("_root_tests_helpers_" + name, str(src))
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for _k, _v in vars(mod).items():
        if not _k.startswith("_"):
            globals()[_k] = _v


for _name in ("synthetic", "market_data"):
    _load(_name)
