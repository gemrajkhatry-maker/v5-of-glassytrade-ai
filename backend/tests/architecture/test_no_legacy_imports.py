import ast
from pathlib import Path

from scripts.check_retirement import check_retirement, FORBIDDEN


def test_production_import_scan_reports_legacy_modules_until_cutover():
    report = check_retirement(Path("."), evidence_verified=False)
    assert report.ready is False
    assert "legacy_imports_remain" in report.blockers
    assert "cutover_evidence_missing" in report.blockers


def test_target_package_has_no_legacy_imports():
    for path in Path("backend/src/glassytrade").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        assert modules.isdisjoint(FORBIDDEN)
