import ast
from pathlib import Path

FORBIDDEN = {"quant.runtime", "quant.multi_engine", "quant.persistence_bridge"}


def test_target_runtime_does_not_import_legacy_runtime_modules():
    for path in Path("backend/src/glassytrade/application/runtime").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        assert modules.isdisjoint(FORBIDDEN), path
