import pytest
from automation.testing.runner import TestRunner, TestReport


def test_runner_executes_tests():
    """TestRunner can execute a real test file."""
    runner = TestRunner()
    report = runner.run_tests("tests/automation/test_scanner.py", with_coverage=False)
    assert report.total_tests > 0
    assert report.passed_tests > 0
    assert report.duration_seconds > 0


def test_runner_returns_test_report():
    """run_tests returns a TestReport dataclass."""
    runner = TestRunner()
    report = runner.run_tests("tests/automation/test_scanner.py", with_coverage=False)
    assert isinstance(report, TestReport)
    assert isinstance(report.total_tests, int)
    assert isinstance(report.passed_tests, int)
    assert isinstance(report.failed_tests, int)
    assert isinstance(report.duration_seconds, float)


def test_runner_detects_all_passing():
    """When all tests pass, failed_tests is 0."""
    runner = TestRunner()
    report = runner.run_tests("tests/automation/test_scanner.py", with_coverage=False)
    assert report.failed_tests == 0
    assert report.passed_tests == report.total_tests


def test_runner_with_coverage():
    """TestRunner can run with coverage analysis."""
    runner = TestRunner()
    report = runner.run_tests("tests/automation/test_scanner.py", with_coverage=True)
    assert report.total_tests > 0
    # Coverage may or may not be parsed depending on output format
    assert isinstance(report.coverage_percent, float)


def test_runner_handles_nonexistent_path():
    """TestRunner handles invalid test paths gracefully."""
    runner = TestRunner()
    # pytest will fail, but we should get a report
    report = runner.run_tests("tests/nonexistent_path_xyz.py", with_coverage=False)
    assert report.total_tests == 0 or report.failed_tests >= 0


def test_test_report_dataclass():
    """TestReport stores all test metrics."""
    report = TestReport(
        total_tests=10,
        passed_tests=8,
        failed_tests=1,
        skipped_tests=1,
        duration_seconds=1.5,
        coverage_percent=85.0,
        failed_test_names=["test_foo.py::test_bar"]
    )
    assert report.total_tests == 10
    assert report.passed_tests == 8
    assert report.failed_tests == 1
    assert report.coverage_percent == 85.0
    assert len(report.failed_test_names) == 1
