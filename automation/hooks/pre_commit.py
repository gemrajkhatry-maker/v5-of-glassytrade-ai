#!/usr/bin/env python3
"""Pre-commit hook for automated quality checks."""

import sys
import subprocess
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from automation.quality.scanner import CodeQualityScanner
from automation.orchestrator import QualityOrchestrator


def main():
    """Run pre-commit quality checks."""
    print("Running pre-commit quality checks...")
    
    # Get list of staged Python files
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
    )
    
    staged_files = [
        f for f in result.stdout.strip().split('\n')
        if f.endswith('.py') and f
    ]
    
    if not staged_files:
        print("No Python files staged. Skipping quality checks.")
        return 0
    
    print(f"Checking {len(staged_files)} staged file(s)...")
    
    # Run quality scan on staged files
    scanner = CodeQualityScanner("automation/config/quality_rules.yaml")
    
    all_issues = []
    for filepath in staged_files:
        if Path(filepath).exists():
            source = Path(filepath).read_text()
            issues = scanner._analyze_complexity(filepath, source)
            issues.extend(scanner._check_architecture(filepath, source))
            issues.extend(scanner._detect_patterns(filepath, source))
            all_issues.extend(issues)
    
    # Filter to only errors (not warnings)
    errors = [i for i in all_issues if i.severity == "error"]
    
    if errors:
        print(f"\n❌ Quality gate FAILED: {len(errors)} error(s) found")
        print("\nErrors:")
        for issue in errors[:10]:
            print(f"  {issue.file}:{issue.line} - {issue.message}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")
        print("\nFix these issues before committing, or use --no-verify to skip.")
        return 1
    
    warnings = [i for i in all_issues if i.severity == "warning"]
    if warnings:
        print(f"\n⚠️  {len(warnings)} warning(s) found (non-blocking)")
        for issue in warnings[:5]:
            print(f"  {issue.file}:{issue.line} - {issue.message}")
    
    print("✅ Quality gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
