import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "glassytrade"
DOMAIN_ROOT = SRC_ROOT / "domain"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_domain_does_not_import_host_or_adapters():
    for path in DOMAIN_ROOT.rglob("*.py"):
        modules = _imported_modules(path)
        assert not any(
            module == "fastapi"
            or module.startswith("fastapi.")
            or module == "sqlite3"
            or module.startswith("sqlite3.")
            or module == "dhan"
            or module.startswith("dhan.")
            or module == "os"
            for module in modules
        ), path


def test_domain_does_not_import_application_or_adapters():
    for path in DOMAIN_ROOT.rglob("*.py"):
        modules = _imported_modules(path)
        assert not any(
            module.startswith("glassytrade.application")
            or module.startswith("glassytrade.adapters")
            or module.startswith("app.")
            or module.startswith("quant.")
            for module in modules
        ), path


def test_target_package_is_importable_with_backend_src_path():
    module = __import__("glassytrade.domain.common.ids", fromlist=["ContractId"])
    assert module.ContractId.__name__ == "ContractId"
