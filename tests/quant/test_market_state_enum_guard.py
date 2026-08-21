"""REF-5 guard: MarketState is an enum at internal edges.

Raw "BALANCED"/"IMBALANCED"/"DEAD" literals caused an 11-file rename blast
radius (audit SMELL-5). Internal code must use MarketState members; string
conversion happens only at the DTO/serialization boundary (amt/dto.py,
contracts/enums.py codecs) or when parsing EXTERNAL input (WS payloads).
"""

import ast
import pathlib

QUANT = pathlib.Path(__file__).resolve().parents[2] / "quant"

ALLOWLIST = {
    "contracts/enums.py",        # the enum itself + codec parsing
    "amt/dto.py",                # wire serialization boundary
    "decision/context.py",       # docstring comment only
    "execution/exit_rules.py",   # table keys use MarketState.X.value
    "decision/context_builder.py",  # parses amt_dto wire input (DTO boundary)
    "decision/gates_edge.py",       # accepts enum OR legacy string from DTOs
    "amt/analyzer.py",              # produces .value strings for the DTO
    "position_manager.py",          # parses amt_dto wire input
}


def _raw_state_literals():
    hits = []
    for path in sorted(QUANT.rglob("*.py")):
        rel = str(path.relative_to(QUANT))
        if rel in ALLOWLIST or "__pycache__" in rel:
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value in ("BALANCED", "IMBALANCED", "DEAD")):
                hits.append(f"{rel}:{node.lineno}")
    return hits


def test_no_raw_market_state_literals_outside_allowlist():
    hits = _raw_state_literals()
    assert not hits, (
        "Raw MarketState string literals found — use MarketState members "
        f"or route through amt/dto.py:\n" + "\n".join(hits)
    )
