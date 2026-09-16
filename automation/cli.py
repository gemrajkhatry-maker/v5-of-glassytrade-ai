#!/usr/bin/env python3
"""CLI interface for the automated code review system."""

import argparse
import json
import sys
from pathlib import Path

from automation.quality.scanner import CodeQualityScanner
from automation.testing.runner import TestRunner
from automation.orchestrator import QualityOrchestrator
from automation.monitor import ContinuousMonitor
from automation.fixes.generator import FixGenerator


def cmd_scan(args):
    """Run quality scan."""
    scanner = CodeQualityScanner(args.config)
    report = scanner.scan(args.path)

    print(f"\nQuality Scan Report")
    print(f"=" * 50)
    print(f"Files scanned: {report.files_scanned}")
    print(f"Issues found: {len(report.issues)}")
    print(f"Overall score: {report.overall_score:.1f}")

    if report.issues:
        print(f"\nIssues:")
        for issue in report.issues[:20]:  # Show first 20
            print(f"  [{issue.severity}] {issue.file}:{issue.line} - {issue.message}")
        if len(report.issues) > 20:
            print(f"  ... and {len(report.issues) - 20} more")

    return 0 if report.overall_score >= 70 else 1


def cmd_test(args):
    """Run tests."""
    runner = TestRunner()
    report = runner.run_tests(args.path, with_coverage=args.coverage)

    print(f"\nTest Report")
    print(f"=" * 50)
    print(f"Total tests: {report.total_tests}")
    print(f"Passed: {report.passed_tests}")
    print(f"Failed: {report.failed_tests}")
    print(f"Skipped: {report.skipped_tests}")
    print(f"Duration: {report.duration_seconds:.2f}s")

    if report.coverage_percent > 0:
        print(f"Coverage: {report.coverage_percent:.1f}%")

    if report.failed_test_names:
        print(f"\nFailed tests:")
        for name in report.failed_test_names[:10]:
            print(f"  - {name}")

    return 0 if report.failed_tests == 0 else 1


def cmd_monitor(args):
    """Run monitoring cycle."""
    monitor = ContinuousMonitor(
        source_path=args.source,
        test_path=args.tests,
        auto_apply_fixes=args.auto_fix,
        report_dir=args.report_dir,
    )

    print("Running monitoring cycle...")
    report = monitor.run_cycle()

    print(f"\nMonitoring Report")
    print(f"=" * 50)
    print(f"Status: {report.overall_status}")
    print(f"Issues found: {report.issues_found}")
    print(f"Fixes proposed: {report.fixes_proposed}")
    print(f"Fixes applied: {report.fixes_applied}")
    print(f"Tests passed: {report.tests_passed}")
    print(f"Tests failed: {report.tests_failed}")

    return 0 if report.overall_status == "healthy" else 1


def cmd_gate(args):
    """Run quality gate."""
    orchestrator = QualityOrchestrator(
        min_quality_score=args.min_score,
        min_test_pass_rate=args.min_pass_rate,
    )

    print("Running quality gate...")
    report = orchestrator.run_quality_gate(
        source_path=args.source,
        test_path=args.tests,
        run_tests=not args.no_tests,
    )

    print(f"\nQuality Gate Report")
    print(f"=" * 50)
    print(f"Verdict: {report.verdict}")
    print(f"Overall score: {report.overall_score:.1f}")
    print(f"Summary: {report.summary}")

    if args.json:
        print(f"\nJSON output:")
        print(json.dumps(report.to_dict(), indent=2))

    return 0 if report.passed else 1


def cmd_fixes(args):
    """Show available fixes."""
    scanner = CodeQualityScanner(args.config)
    report = scanner.scan(args.path)

    fixer = FixGenerator()

    # Group issues by file
    issues_by_file = {}
    for issue in report.issues:
        if issue.file not in issues_by_file:
            issues_by_file[issue.file] = []
        issues_by_file[issue.file].append(issue)

    total_proposals = 0
    for filepath, issues in issues_by_file.items():
        try:
            source = Path(filepath).read_text()
            proposals = fixer.generate_fixes(issues, source)
            total_proposals += len(proposals)

            if proposals:
                print(f"\n{filepath}:")
                for p in proposals:
                    safe = "safe" if p.is_safe else "review needed"
                    print(f"  [{safe}] {p.description}")
        except Exception:
            continue

    print(f"\nTotal fixable issues: {total_proposals}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Automated Code Review System",
        prog="automation-cli",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # scan command
    scan_parser = subparsers.add_parser("scan", help="Run quality scan")
    scan_parser.add_argument("path", nargs="?", default="quant", help="Path to scan")
    scan_parser.add_argument("--config", default="automation/config/quality_rules.yaml")
    scan_parser.set_defaults(func=cmd_scan)

    # test command
    test_parser = subparsers.add_parser("test", help="Run tests")
    test_parser.add_argument("path", nargs="?", default="tests/automation")
    test_parser.add_argument("--coverage", action="store_true")
    test_parser.set_defaults(func=cmd_test)

    # monitor command
    monitor_parser = subparsers.add_parser("monitor", help="Run monitoring cycle")
    monitor_parser.add_argument("--source", default="quant")
    monitor_parser.add_argument("--tests", default="tests")
    monitor_parser.add_argument("--auto-fix", action="store_true")
    monitor_parser.add_argument("--report-dir", default="automation/reports")
    monitor_parser.set_defaults(func=cmd_monitor)

    # gate command
    gate_parser = subparsers.add_parser("gate", help="Run quality gate")
    gate_parser.add_argument("--source", default="quant")
    gate_parser.add_argument("--tests", default="tests/automation")
    gate_parser.add_argument("--min-score", type=float, default=70.0)
    gate_parser.add_argument("--min-pass-rate", type=float, default=100.0)
    gate_parser.add_argument("--no-tests", action="store_true")
    gate_parser.add_argument("--json", action="store_true")
    gate_parser.set_defaults(func=cmd_gate)

    # fixes command
    fixes_parser = subparsers.add_parser("fixes", help="Show available fixes")
    fixes_parser.add_argument("path", nargs="?", default="quant")
    fixes_parser.add_argument("--config", default="automation/config/quality_rules.yaml")
    fixes_parser.set_defaults(func=cmd_fixes)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
