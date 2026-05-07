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
    """Check for assert True placeholders."""
    issues = []
    for test_file in TESTS_DIR.rglob("test_*.py"):
        content = test_file.read_text()
        for i, line in enumerate(content.splitlines(), 1):
            if re.match(r'\s*assert\s+True\s*$', line) or re.match(r'\s*assert\s+True\s*#', line):
                issues.append(f"{test_file.relative_to(BACKENDV2)}:{i}: Found 'assert True' placeholder")
    return issues


def check_test_functions_have_assertions() -> list[str]:
    """Check that test functions have at least one assertion."""
    issues = []
    for test_file in TESTS_DIR.rglob("test_*.py"):
        content = test_file.read_text()
        # Find test functions
        test_funcs = re.finditer(r'def\s+(test_\w+)\s*\(', content)
        lines = content.splitlines()

        for match in test_funcs:
            func_name = match.group(1)
            start_line = match.start()
            # Find next function or end of file
            next_func = re.search(r'\n\s*def\s+', content[start_line + 1:])
            end_line = next_func.start() + start_line + 1 if next_func else len(content)

            func_body = content[start_line:end_line]
            if 'assert ' not in func_body and 'pytest.raises' not in func_body:
                line_num = content[:start_line].count('\n') + 1
                issues.append(f"{test_file.relative_to(BACKENDV2)}:{line_num}: {func_name}() has no assertions")

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
        if test_file.parent.name == "tests" or "tests" in test_file.parent.parts:
            if not test_file.name.startswith("_"):
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
