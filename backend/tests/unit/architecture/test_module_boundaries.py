"""Architecture tests — verify module boundaries and zero cross-domain coupling."""

import ast
from pathlib import Path
import pytest

BACKEND = Path(__file__).resolve().parent.parent.parent.parent / "app"
TRADING_DIR = BACKEND / "domain" / "trading"
FABIO_DIR = BACKEND / "domain" / "fabio_ai"
DOMAIN_DIR = BACKEND / "domain"


def _collect_imports(directory: Path) -> list[tuple[Path, str]]:
    """Return (file, module_path) for every `from X import ...` in directory."""
    results = []
    for py_file in directory.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                results.append((py_file, node.module))
    return results


class TestTradingDomainBoundary:
    """trading/ must not import from fabio_ai/."""

    def test_no_fabio_ai_imports(self):
        violations = [
            (f.relative_to(TRADING_DIR), mod)
            for f, mod in _collect_imports(TRADING_DIR)
            if "fabio_ai" in mod
        ]
        assert violations == [], f"trading/ imports fabio_ai/: {violations}"


class TestDomainInfrastructureBoundary:
    """domain/ must not import from infrastructure/."""

    def test_no_infrastructure_imports(self):
        violations = [
            (f.relative_to(DOMAIN_DIR), mod)
            for f, mod in _collect_imports(DOMAIN_DIR)
            if "app.infrastructure" in mod
        ]
        assert violations == [], f"domain/ imports infrastructure/: {violations}"


ADAPTERS_DIR = BACKEND / "infrastructure" / "adapters"


class TestBrokersImportBoundary:
    """Only infrastructure/adapters may import the root-level brokers package."""

    def test_brokers_imports_only_in_adapters(self):
        violations = [
            (f.relative_to(BACKEND), mod)
            for f, mod in _collect_imports(BACKEND)
            if (mod == "brokers" or mod.startswith("brokers."))
            and ADAPTERS_DIR not in f.parents
        ]
        assert violations == [], f"brokers/ imported outside adapters/: {violations}"
