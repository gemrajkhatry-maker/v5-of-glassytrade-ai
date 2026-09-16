"""Verify quant.transition alias is not imported anywhere in production code."""

import ast
from pathlib import Path


def test_no_imports_of_transition_alias():
    """Ensure no production code imports from quant.transition (the alias)."""
    quant_dir = Path("quant")
    violations = []
    
    for py_file in quant_dir.rglob("*.py"):
        if py_file.name == "transition.py":
            continue  # Skip if the alias file exists
        
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                # Check for exact match: "quant.transition" (not "quant.transitions")
                if node.module == "quant.transition":
                    violations.append(f"{py_file}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    # Check for exact match
                    if alias.name == "quant.transition":
                        violations.append(f"{py_file}:{node.lineno}")
    
    assert not violations, f"Found imports of quant.transition alias: {violations}"


def test_transition_alias_file_deleted():
    """Ensure the alias file has been deleted."""
    alias_file = Path("quant/transition.py")
    assert not alias_file.exists(), "quant/transition.py should be deleted"
