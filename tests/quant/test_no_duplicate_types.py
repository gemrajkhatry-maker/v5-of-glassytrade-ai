# tests/quant/test_no_duplicate_types.py
"""AST guard: sanctioned type homes. Re-cloning any unified type outside its
canonical home fails the suite. Layered model pairs (Signal, Position) are
sanctioned seams — pinned to exactly the listed files (spec §8)."""

import ast
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CANONICAL = {
    "Bar": ["quant/bars.py"],
}
# Layered-model pairs: exactly these files may define these class names.
LAYERED = {
    "Signal": [
        "quant/contracts/entities.py",
        "quant/decision/signal_builder.py",
    ],
    "Position": [
        "backend/src/glassytrade/domain/execution/types.py",
        "quant/contracts/entities.py",
        "quant/execution/order.py",
        "shared/entities/models.py",
    ],
    "OHLC": [
        "brokers/broker/dhan/domain/value_objects.py",
        "quant/contracts/value_objects.py",
    ],
}

# Excluded from the census: vendored/virtual envs, generated graph output,
# archived snapshots, and worktrees. Nothing else in the repo holds project
# source (frontend has no .py files).
_EXCLUDED_DIRS = (
    ".venv/",
    "backend/venv/",
    ".worktrees/",
    "graphify-out/",
    "old.freebuff/",
    "node_modules/",
)


@lru_cache(maxsize=None)
def _class_defs(name: str) -> list[str]:
    hits = []
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith(_EXCLUDED_DIRS):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == name:
                hits.append(rel)
    return sorted(hits)


def test_bar_and_ohlc_have_single_definition():
    for name, allowed in CANONICAL.items():
        assert _class_defs(name) == allowed, (
            f"{name} cloned outside canonical home: {_class_defs(name)}"
        )


def test_layered_pairs_pinned_to_sanctioned_files():
    for name, allowed in LAYERED.items():
        assert _class_defs(name) == allowed, (
            f"{name} defined in unexpected files: {_class_defs(name)} — "
            f"sanctioned: {allowed}"
        )
