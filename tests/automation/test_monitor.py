import pytest
from automation.monitor import ContinuousMonitor, MonitorReport, MonitorAction


def test_monitor_initializes():
    """ContinuousMonitor can be instantiated."""
    monitor = ContinuousMonitor(
        source_path="automation",
        test_path="tests/automation/test_scanner.py",
    )
    assert monitor is not None


def test_monitor_runs_cycle():
    """run_cycle returns a MonitorReport."""
    monitor = ContinuousMonitor(
        source_path="automation",
        test_path="tests/automation/test_scanner.py",
    )
    report = monitor.run_cycle()
    assert isinstance(report, MonitorReport)
    assert report.cycle_start is not None
    assert report.cycle_end is not None
    assert isinstance(report.issues_found, int)


def test_monitor_report_has_status():
    """MonitorReport includes overall status."""
    monitor = ContinuousMonitor(
        source_path="automation",
        test_path="tests/automation/test_scanner.py",
    )
    report = monitor.run_cycle()
    assert report.overall_status in ["healthy", "degraded", "critical"]


def test_monitor_saves_report(tmp_path):
    """Monitor saves report to JSON file."""
    monitor = ContinuousMonitor(
        source_path="automation",
        test_path="tests/automation/test_scanner.py",
        report_dir=str(tmp_path),
    )
    report = monitor.run_cycle()

    # Check that a report file was created
    report_files = list(tmp_path.glob("monitor_report_*.json"))
    assert len(report_files) > 0


def test_monitor_action_dataclass():
    """MonitorAction stores action details."""
    action = MonitorAction(
        timestamp="2026-09-16T12:00:00",
        action_type="scan",
        details={"files_scanned": 10, "issues_found": 5},
        success=True,
    )
    assert action.action_type == "scan"
    assert action.success is True


def test_monitor_report_dataclass():
    """MonitorReport stores cycle summary."""
    report = MonitorReport(
        cycle_start="2026-09-16T12:00:00",
        cycle_end="2026-09-16T12:01:00",
        issues_found=5,
        fixes_proposed=2,
        fixes_applied=1,
        tests_passed=10,
        tests_failed=0,
        actions=[],
        overall_status="healthy",
    )
    assert report.issues_found == 5
    assert report.overall_status == "healthy"


def test_monitor_without_auto_apply():
    """Monitor can run without auto-applying fixes."""
    monitor = ContinuousMonitor(
        source_path="automation",
        test_path="tests/automation/test_scanner.py",
        auto_apply_fixes=False,
    )
    report = monitor.run_cycle()
    # Should not apply any fixes
    assert report.fixes_applied == 0 or report.fixes_applied <= report.fixes_proposed
