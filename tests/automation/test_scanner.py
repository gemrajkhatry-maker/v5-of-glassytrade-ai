from automation.quality.scanner import CodeQualityScanner, QualityReport, QualityIssue


def test_scanner_initializes_with_config():
    """Scanner loads config and reports rules_loaded=True."""
    scanner = CodeQualityScanner(config_path="automation/config/quality_rules.yaml")
    assert scanner is not None
    assert scanner.rules_loaded is True


def test_scanner_loads_rules_from_yaml():
    """Scanner parses YAML config correctly."""
    scanner = CodeQualityScanner(config_path="automation/config/quality_rules.yaml")
    assert "rules" in scanner.rules
    assert "complexity" in scanner.rules["rules"]
    assert scanner.rules["rules"]["complexity"]["max_cyclomatic"] == 10


def test_scanner_scan_returns_quality_report():
    """scan() returns a QualityReport dataclass."""
    scanner = CodeQualityScanner(config_path="automation/config/quality_rules.yaml")
    report = scanner.scan("automation/quality/scanner.py")
    assert isinstance(report, QualityReport)
    assert report.files_scanned >= 1
    assert isinstance(report.issues, list)
    assert isinstance(report.overall_score, float)


def test_scanner_scan_directory():
    """scan() can scan a directory of Python files."""
    scanner = CodeQualityScanner(config_path="automation/config/quality_rules.yaml")
    report = scanner.scan("automation/quality")
    assert report.files_scanned >= 1  # At least scanner.py and __init__.py


def test_quality_issue_dataclass():
    """QualityIssue stores issue details."""
    issue = QualityIssue(
        file="test.py",
        line=10,
        rule="complexity.cyclomatic",
        severity="warning",
        message="Function too complex"
    )
    assert issue.file == "test.py"
    assert issue.line == 10
    assert issue.rule == "complexity.cyclomatic"


def test_quality_report_dataclass():
    """QualityReport stores scan results."""
    report = QualityReport(
        issues=[],
        files_scanned=5,
        rules_violated=0,
        overall_score=100.0
    )
    assert report.files_scanned == 5
    assert report.overall_score == 100.0
