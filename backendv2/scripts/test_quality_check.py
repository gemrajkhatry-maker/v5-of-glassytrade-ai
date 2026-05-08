#!/usr/bin/env python3
"""Test quality check script.

Run this before commits to ensure test quality standards.

Checks:
1. No `assert True` in test files
2. No test functions without assertions
3. All @pytest.mark.skip have valid reasons
4. Test file naming conventions

Usage:
    python scripts/test_quality_check.py
"""
import re
import sys
from pathlib import Path

BACKENDV2 = Path(__file__).parent.parent
TESTS_DIR = BACKENDV2 / "tests"


def check_no_assert_true() -> list[str]:
    """Check for assert True placeholders.

    Allows 'assert True' when followed by a comment explaining why
    (e.g., '# No exception = success').
    """
    issues = []
    for test_file in TESTS_DIR.rglob("test_*.py"):
        content = test_file.read_text()
        for i, line in enumerate(content.splitlines(), 1):
            if re.match(r'\s*assert\s+True\s*$', line):
                issues.append(f"{test_file.relative_to(BACKENDV2)}:{i}: Found 'assert True' placeholder")
            elif re.match(r'\s*assert\s+True\s*#', line):
                # Has explanatory comment - allowed
                pass
    return issues


def check_test_functions_have_assertions() -> list[str]:
    """Check that unit test functions have at least one assertion.

    Uses AST parsing to correctly handle nested functions and find all
    assertions within the full function body.
    """
    import ast

    issues = []
    for test_file in TESTS_DIR.rglob("test_*.py"):
        # Only check unit tests
        rel_path = test_file.relative_to(TESTS_DIR)
        if rel_path.parts[0] not in ("unit",):
            continue

        try:
            content = test_file.read_text()
            tree = ast.parse(content)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("test_"):
                    continue

                # Check if function has any Assert nodes in its body
                has_assert = any(
                    isinstance(child, ast.Assert)
                    for child in ast.walk(node)
                )
                if not has_assert:
                    # Check for known patterns that indicate implicit assertions
                    source_lines = content.splitlines()
                    if node.lineno <= len(source_lines):
                        func_source = "\n".join(source_lines[node.lineno - 1:node.end_lineno])
                        # Skip if it uses pytest.raises/warns
                        if "pytest.raises" in func_source or "pytest.warns" in func_source:
                            continue
                        # Skip if it delegates to helper methods
                        if "self._" in func_source or "call_" in func_source:
                            continue
                        # Skip if it has mock assertions
                        if re.search(r'\.assert\w+\(', func_source):
                            continue

                    issues.append(
                        f"{test_file.relative_to(BACKENDV2)}:{node.lineno}: "
                        f"{node.name}() has no assertions"
                    )

    return issues


def check_skip_markers_have_reasons() -> list[str]:
    """Check that all @pytest.mark.skip have reasons."""
    issues = []
    for test_file in TESTS_DIR.rglob("test_*.py"):
        content = test_file.read_text()
        for i, line in enumerate(content.splitlines(), 1):
            if '@pytest.mark.skip' in line and 'reason=' not in line:
                issues.append(f"{test_file.relative_to(BACKENDV2)}:{i}: @pytest.mark.skip without reason")
    return issues


def check_test_file_naming() -> list[str]:
    """Check that test files follow naming convention."""
    issues = []
    for test_file in TESTS_DIR.rglob("*.py"):
        if test_file.name.startswith("test_") or test_file.name == "conftest.py":
            continue
        # Skip fixtures, __init__.py, and helper modules
        if "fixtures" in test_file.parts or test_file.name.startswith("_"):
            continue
        if test_file.parent.name == "tests" or "tests" in test_file.parent.parts:
            issues.append(f"{test_file.relative_to(BACKENDV2)}: Test file should start with 'test_'")
    return issues


def main() -> int:
    """Run all checks."""
    print("=" * 60)
    print("Test Quality Check")
    print("=" * 60)

    all_issues = []

    print("\n1. Checking for 'assert True' placeholders...")
    issues = check_no_assert_true()
    print(f"   Found {len(issues)} issues")
    all_issues.extend(issues)

    print("\n2. Checking test functions have assertions...")
    issues = check_test_functions_have_assertions()
    print(f"   Found {len(issues)} issues")
    all_issues.extend(issues)

    print("\n3. Checking @pytest.mark.skip have reasons...")
    issues = check_skip_markers_have_reasons()
    print(f"   Found {len(issues)} issues")
    all_issues.extend(issues)

    print("\n4. Checking test file naming...")
    issues = check_test_file_naming()
    print(f"   Found {len(issues)} issues")
    all_issues.extend(issues)

    print("\n" + "=" * 60)
    if all_issues:
        print(f"FAILED: {len(all_issues)} issues found")
        print("=" * 60)
        for issue in all_issues:
            print(f"  - {issue}")
        return 1
    else:
        print("PASSED: All quality checks passed")
        print("=" * 60)
        return 0


if __name__ == "__main__":
    sys.exit(main())
