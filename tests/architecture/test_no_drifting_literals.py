"""D-28: the same numeral meant different things across modules."""

import pathlib
import re

QUANT = pathlib.Path(__file__).resolve().parents[2] / "quant"

PATTERNS = {
    "fallback equity literal": re.compile(r"\bor\s+100000\.0\b|\bor\s+200000\.0\b"),
    "binary forecast band": re.compile(r"0\.998|1\.002"),
    "hardcoded conviction threshold": re.compile(r"agent_probability\s*>=\s*0\.65"),
    "sizing leverage literal": re.compile(r"equity \* (2\.5|3\.0)"),
}


def test_no_drifting_literals():
    offenders = []
    for path in QUANT.rglob("*.py"):
        if path.name == "constants.py":
            continue
        text = path.read_text(encoding="utf-8")
        for label, pattern in PATTERNS.items():
            for m in pattern.finditer(text):
                line = text[: m.start()].count("\n") + 1
                offenders.append(f"{label}: {path.relative_to(QUANT.parent)}:{line}")
    assert not offenders, "\n  ".join(offenders)
