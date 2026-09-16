import pytest
from automation.coverage.analyzer import (
    CoverageAnalyzer,
    FileCoverage,
    CoverageReport,
)


def test_coverage_analyzer_initializes():
    """CoverageAnalyzer can be instantiated."""
    analyzer = CoverageAnalyzer()
    assert analyzer is not None
    assert analyzer.coverage_threshold == 80.0


def test_file_coverage_dataclass():
    """FileCoverage stores file coverage data."""
    fc = FileCoverage(
        file="test.py",
        total_lines=100,
        covered_lines=80,
        missing_lines=[1, 2, 3],
        coverage_percent=80.0,
    )
    assert fc.file == "test.py"
    assert fc.coverage_percent == 80.0


def test_coverage_report_dataclass():
    """CoverageReport stores overall coverage data."""
    report = CoverageReport(
        total_coverage=85.0,
        files=[],
        low_coverage_files=[],
        threshold=80.0,
    )
    assert report.total_coverage == 85.0


def test_analyzer_parses_missing_lines():
    """Analyzer parses missing line ranges correctly."""
    analyzer = CoverageAnalyzer()
    
    lines = analyzer._parse_missing_lines("15-25, 30, 35-40")
    assert 15 in lines
    assert 25 in lines
    assert 30 in lines
    assert 35 in lines
    assert 40 in lines
    assert len(lines) == 18  # 11 + 1 + 6


def test_analyzer_handles_empty_missing():
    """Analyzer handles empty missing lines."""
    analyzer = CoverageAnalyzer()
    lines = analyzer._parse_missing_lines("")
    assert lines == []


def test_analyzer_calculates_total_coverage():
    """Analyzer calculates total coverage correctly."""
    analyzer = CoverageAnalyzer()
    
    files = [
        FileCoverage("a.py", 100, 80, [], 80.0),
        FileCoverage("b.py", 100, 90, [], 90.0),
    ]
    
    total = analyzer._calculate_total_coverage(files)
    assert total == 85.0  # (80 + 90) / 200 * 100


def test_analyzer_identifies_low_coverage():
    """Analyzer identifies files below threshold."""
    analyzer = CoverageAnalyzer(coverage_threshold=80.0)
    
    files = [
        FileCoverage("a.py", 100, 90, [], 90.0),
        FileCoverage("b.py", 100, 70, [], 70.0),
        FileCoverage("c.py", 100, 85, [], 85.0),
    ]
    
    report = CoverageReport(
        total_coverage=81.67,
        files=files,
        low_coverage_files=[f for f in files if f.coverage_percent < 80.0],
        threshold=80.0,
    )
    
    assert len(report.low_coverage_files) == 1
    assert report.low_coverage_files[0].file == "b.py"


def test_analyzer_parses_coverage_output():
    """Analyzer parses pytest-cov output format."""
    analyzer = CoverageAnalyzer()
    
    output = """
Name                           Stmts   Miss  Cover   Missing
------------------------------------------------------------
quant/engine/scanner.py           50     10    80%   15-25
quant/engine/runner.py            30      5    83%   10-15
------------------------------------------------------------
TOTAL                             80     15    81%
"""
    
    files = analyzer._parse_coverage_output(output)
    assert len(files) == 2
    assert files[0].file == "quant/engine/scanner.py"
    assert files[0].coverage_percent == 80.0
    assert 15 in files[0].missing_lines
