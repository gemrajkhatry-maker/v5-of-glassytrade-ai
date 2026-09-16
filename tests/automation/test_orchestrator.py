import pytest
from automation.orchestrator import QualityOrchestrator, QualityGateReport


def test_orchestrator_initializes():
    """QualityOrchestrator can be instantiated."""
    orchestrator = QualityOrchestrator()
    assert orchestrator is not None
    assert orchestrator.min_quality_score == 70.0


def test_orchestrator_runs_quality_gate():
    """run_quality_gate returns a QualityGateReport."""
    orchestrator = QualityOrchestrator()
    report = orchestrator.run_quality_gate(
        source_path="automation",
        test_path="tests/automation/test_scanner.py",
        run_tests=False,  # Skip tests for speed
    )
    assert isinstance(report, QualityGateReport)
    assert report.scanner_report is not None
    assert isinstance(report.overall_score, float)


def test_orchestrator_with_tests():
    """run_quality_gate can include test execution."""
    orchestrator = QualityOrchestrator()
    report = orchestrator.run_quality_gate(
        source_path="automation",
        test_path="tests/automation/test_scanner.py",
        run_tests=True,
    )
    assert report.test_report is not None
    assert report.test_report.total_tests > 0


def test_quality_gate_report_to_dict():
    """QualityGateReport can be serialized to dict."""
    orchestrator = QualityOrchestrator()
    report = orchestrator.run_quality_gate(
        source_path="automation",
        test_path="tests/automation/test_scanner.py",
        run_tests=False,
    )
    data = report.to_dict()
    assert "passed" in data
    assert "overall_score" in data
    assert "verdict" in data
    assert "scanner" in data


def test_orchestrator_calculates_verdict():
    """Orchestrator determines pass/fail based on thresholds."""
    orchestrator = QualityOrchestrator(min_quality_score=0.0)
    report = orchestrator.run_quality_gate(
        source_path="automation",
        test_path="tests/automation/test_scanner.py",
        run_tests=False,
    )
    # With min_quality_score=0, should pass
    assert report.passed is True
    assert report.verdict == "PASSED"


def test_orchestrator_fails_on_low_quality():
    """Orchestrator fails when quality score is below threshold."""
    orchestrator = QualityOrchestrator(min_quality_score=999.0)
    report = orchestrator.run_quality_gate(
        source_path="automation",
        test_path="tests/automation/test_scanner.py",
        run_tests=False,
    )
    assert report.passed is False
    assert report.verdict == "FAILED"
    assert "Quality score" in report.summary


def test_orchestrator_save_report(tmp_path):
    """Orchestrator can save report to JSON file."""
    orchestrator = QualityOrchestrator()
    report = orchestrator.run_quality_gate(
        source_path="automation",
        test_path="tests/automation/test_scanner.py",
        run_tests=False,
    )
    output_path = tmp_path / "quality_report.json"
    orchestrator.save_report(report, str(output_path))
    assert output_path.exists()

    import json
    with open(output_path) as f:
        data = json.load(f)
    assert data["passed"] == report.passed
