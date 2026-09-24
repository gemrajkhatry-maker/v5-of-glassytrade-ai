"""Retirement gate: report legacy imports and require cutover evidence before deletion."""

from __future__ import annotations

import ast
import argparse
from dataclasses import dataclass
from pathlib import Path

FORBIDDEN = frozenset(
    {
        "quant.runtime",
        "quant.multi_engine",
        "quant.persistence_bridge",
        "quant.execution.live_oms",
        "quant.execution.oms",
    }
)


@dataclass(frozen=True)
class RetirementReport:
    ready: bool
    legacy_imports: tuple[str, ...]
    blockers: tuple[str, ...]


def scan_production_imports(root: Path = Path(".")) -> set[str]:
    found: set[str] = set()
    bases = (root / "backend" / "app", root / "quant")
    if not bases[0].exists() and (root / "app").exists():
        bases = (root / "app", root / "quant")
    for base in bases:
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    found.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    found.add(node.module)
    return {name for name in found if name in FORBIDDEN or any(name.startswith(item + ".") for item in FORBIDDEN)}


def check_retirement(root: Path = Path("."), *, evidence_verified: bool = False) -> RetirementReport:
    imports = tuple(sorted(scan_production_imports(root)))
    blockers: list[str] = []
    if imports:
        blockers.append("legacy_imports_remain")
    if not evidence_verified:
        blockers.append("cutover_evidence_missing")
    return RetirementReport(not blockers, imports, tuple(blockers))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--evidence-verified", action="store_true")
    args = parser.parse_args()
    report = check_retirement(args.root, evidence_verified=args.evidence_verified)
    print(report)
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
