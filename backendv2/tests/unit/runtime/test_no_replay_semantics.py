"""Verification gates for deterministic audit semantics."""

import inspect
import pkgutil
import re
import importlib

import app.runtime


def test_runtime_modules_do_not_expose_historic_reconstitution_dispatch():
    for module_info in pkgutil.walk_packages(app.runtime.__path__, prefix="app.runtime."):
        module = importlib.import_module(module_info.name)
        source = inspect.getsource(module)
        assert re.search(r"\bdef\s+[\w]*historic\w*\s*\(", source) is None
