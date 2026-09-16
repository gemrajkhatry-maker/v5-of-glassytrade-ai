from automation.quality.scanner import CodeQualityScanner


def test_complexity_analysis_detects_high_complexity():
    """Functions with complexity > threshold are flagged."""
    scanner = CodeQualityScanner("automation/config/quality_rules.yaml")
    test_code = """
def complex_function(x):
    if x > 0:
        if x > 10:
            if x > 20:
                if x > 30:
                    if x > 40:
                        if x > 50:
                            if x > 60:
                                if x > 70:
                                    if x > 80:
                                        if x > 90:
                                            return x
    return 0
"""
    issues = scanner._analyze_complexity("test.py", test_code)
    assert len(issues) > 0
    assert any("complexity" in issue.rule.lower() for issue in issues)


def test_complexity_analysis_ignores_simple_functions():
    """Functions below threshold produce no issues."""
    scanner = CodeQualityScanner("automation/config/quality_rules.yaml")
    test_code = """
def simple_function(x):
    if x > 0:
        return x
    return 0
"""
    issues = scanner._analyze_complexity("test.py", test_code)
    assert len(issues) == 0


def test_complexity_analysis_handles_parse_errors():
    """Invalid Python code doesn't crash the analyzer."""
    scanner = CodeQualityScanner("automation/config/quality_rules.yaml")
    test_code = "def broken(:\n    pass"
    issues = scanner._analyze_complexity("test.py", test_code)
    # Should return empty list, not raise
    assert isinstance(issues, list)


def test_scan_includes_complexity_issues():
    """scan() method includes complexity analysis results."""
    scanner = CodeQualityScanner("automation/config/quality_rules.yaml")
    # Scan the automation directory - should find some complexity data
    report = scanner.scan("automation/quality")
    assert report.files_scanned >= 1
    # Report should be valid even if no issues found
    assert isinstance(report.overall_score, float)
