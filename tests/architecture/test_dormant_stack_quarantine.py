"""Quarantine fence for the dormant glassytrade target stack.

The target stack under ``backend/src/glassytrade/`` landed before its B1–B3
execution-safety packages and has no production composition: startup refuses
``GLASSYTRADE_RUNTIME_ENGINE=target`` and no glassytrade router is registered.
This test keeps that isolation provable in one direction only covered by
``backend/tests/architecture/test_glassytrade_imports.py`` (target must not
import legacy). Here we pin the reverse: legacy code must not start consuming
the dormant stack, so its drift cannot silently become load-bearing.

Deliberate allowlist: ``backend/app/main.py`` may import
``glassytrade.bootstrap.runtime_config`` — ``RuntimeConfig`` is the validated
config object and the refusal guard itself needs the engine identity.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

ALLOWED_SEAMS = {
    ("backend/app/main.py", "glassytrade.bootstrap.runtime_config"),
}

SCANNED_ROOTS = (
    REPO_ROOT / "quant",
    REPO_ROOT / "backend" / "app",
    REPO_ROOT / "brokers",
)


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module)
    return modules


def test_legacy_code_does_not_import_dormant_glassytrade_stack() -> None:
    violations: list[str] = []
    for root in SCANNED_ROOTS:
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
            for module in _imported_modules(tree):
                if module != "glassytrade" and not module.startswith(
                    "glassytrade."
                ):
                    continue
                if (rel, module) in ALLOWED_SEAMS:
                    continue
                violations.append(f"{rel} imports {module}")

    assert not violations, (
        "Legacy code must not import the dormant target stack until its "
        "composition gate is approved (see backend/src/glassytrade/README.md; "
        "startup refusal pinned in backend/tests/unit/config/"
        "test_live_startup_policy.py):\n" + "\n".join(violations)
    )
