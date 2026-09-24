import ast
from pathlib import Path

RUNTIME_ROOT = Path("backend/src/glassytrade/application/runtime")


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_symbol_worker_has_no_broker_or_persistence_authority():
    modules = imports(RUNTIME_ROOT / "symbol_worker.py")
    assert not any(
        module.startswith("glassytrade.adapters")
        or module.startswith("glassytrade.application.oms")
        or module.startswith("sqlite3")
        or module.startswith("app.")
        or module.startswith("quant.")
        for module in modules
    )


def test_execution_coordinator_is_the_only_runtime_order_writer():
    worker_source = (RUNTIME_ROOT / "symbol_worker.py").read_text(encoding="utf-8")
    coordinator_source = (RUNTIME_ROOT / "execution_coordinator.py").read_text(encoding="utf-8")
    assert "prepare_entry" not in worker_source
    assert "prepare_entry" in coordinator_source
    assert "claim_dispatch" in coordinator_source or "oms_service" in coordinator_source


def test_supervisor_has_explicit_shutdown_order():
    source = (RUNTIME_ROOT / "supervisor.py").read_text(encoding="utf-8")
    stop_index = source.index("def stop")
    tail = source[stop_index:]
    assert tail.index('getattr(self.scanner, "stop"') < tail.index('getattr(worker, "stop"')
    assert tail.index('getattr(worker, "stop"') < tail.index("self.storage")
    assert tail.index("storage") < tail.index("broker")
