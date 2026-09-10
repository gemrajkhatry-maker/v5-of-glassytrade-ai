"""D-24: a swallowed exception must be a deliberate, annotated choice."""

import ast
import pathlib

ROOTS = [
    pathlib.Path(__file__).resolve().parents[2] / "quant",
    pathlib.Path(__file__).resolve().parents[2] / "backend" / "app",
]


def test_no_unannotated_silent_except_pass():
    offenders = []
    for root in ROOTS:
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            lines = source.splitlines()
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                if len(node.body) != 1 or not isinstance(node.body[0], ast.Pass):
                    continue
                handler_line = lines[node.lineno - 1]
                if "silent-except" in handler_line:
                    continue
                offenders.append(f"{path.relative_to(root.parent)}:{node.lineno}")
    assert not offenders, (
        "silent `except: pass` without a `# silent-except - <reason>` marker:\n  "
        + "\n  ".join(offenders)
    )
