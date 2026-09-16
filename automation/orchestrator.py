from dataclasses import dataclass
from typing import List, Optional
from pathlib import Path
import json

from automation.quality.scanner import CodeQualityScanner, QualityReport
from automation.testing.runner import TestRunner, TestReport


@dataclass
class QualityGateReport:
    """Unified quality gate combining static analysis and test results."""
    passed: bool
    scanner_report: Optional[QualityReport]
    test_report: Optional[TestReport]
    overall_score: float
    verdict: str
    summary: str

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "passed": self.passed,
            "overall_score": self.overall_score,
            "verdict": self.verdict,
            "summary": self.summary,
            "scanner": {
                "files_scanned": self.scanner_report.files_scanned if self.scanner_report else 0,
                "issues_found": len(self.scanner_report.issues) if self.scanner_report else 0,
                "score": self.scanner_report.overall_score if self.scanner_report else 0.0,
            } if self.scanner_report else None,
            "tests": {
                "total": self.test_report.total_tests if self.test_report else 0,
                "passed": self.test_report.passed_tests if self.test_report else 0,
                "failed": self.test_report.failed_tests if self.test_report else 0,
                "coverage": self.test_report.coverage_percent if self.test_report else 0.0,
            } if self.test_report else None,
        }


class QualityOrchestrator:
    """Orchestrates all quality checks and produces a unified report."""

    def __init__(
        self,
        scanner_config: str = "automation/config/quality_rules.yaml",
        min_quality_score: float = 70.0,
        min_test_pass_rate: float = 100.0,
        min_coverage: float = 0.0,
    ):
        self.scanner_config = scanner_config
        self.min_quality_score = min_quality_score
        self.min_test_pass_rate = min_test_pass_rate
        self.min_coverage = min_coverage
        self._scanner: Optional[CodeQualityScanner] = None
        self._runner: Optional[TestRunner] = None

    @property
    def scanner(self) -> CodeQualityScanner:
        if self._scanner is None:
            self._scanner = CodeQualityScanner(self.scanner_config)
        return self._scanner

    @property
    def runner(self) -> TestRunner:
        if self._runner is None:
            self._runner = TestRunner()
        return self._runner

    def run_quality_gate(
        self,
        source_path: str = "quant",
        test_path: str = "tests/automation",
        run_tests: bool = True,
    ) -> QualityGateReport:
        """Run all quality checks and return unified report."""
        # Run static analysis
        scanner_report = self.scanner.scan(source_path)

        # Run tests
        test_report = None
        if run_tests:
            test_report = self.runner.run_tests(test_path, with_coverage=True)

        # Calculate verdict
        passed, verdict, summary = self._calculate_verdict(scanner_report, test_report)
        overall_score = self._calculate_overall_score(scanner_report, test_report)

        return QualityGateReport(
            passed=passed,
            scanner_report=scanner_report,
            test_report=test_report,
            overall_score=overall_score,
            verdict=verdict,
            summary=summary,
        )

    def _calculate_verdict(
        self,
        scanner_report: QualityReport,
        test_report: Optional[TestReport],
    ) -> tuple:
        """Determine pass/fail verdict based on thresholds."""
        failures = []

        # Check quality score
        if scanner_report.overall_score < self.min_quality_score:
            failures.append(
                f"Quality score {scanner_report.overall_score:.1f} "
                f"below threshold {self.min_quality_score:.1f}"
            )

        # Check test results
        if test_report:
            if test_report.total_tests > 0:
                pass_rate = (test_report.passed_tests / test_report.total_tests) * 100
                if pass_rate < self.min_test_pass_rate:
                    failures.append(
                        f"Test pass rate {pass_rate:.1f}% "
                        f"below threshold {self.min_test_pass_rate:.1f}%"
                    )

            if test_report.coverage_percent < self.min_coverage:
                failures.append(
                    f"Coverage {test_report.coverage_percent:.1f}% "
                    f"below threshold {self.min_coverage:.1f}%"
                )

        if failures:
            return False, "FAILED", "; ".join(failures)
        else:
            return True, "PASSED", "All quality checks passed"

    def _calculate_overall_score(
        self,
        scanner_report: QualityReport,
        test_report: Optional[TestReport],
    ) -> float:
        """Calculate weighted overall score."""
        scores = []
        weights = []

        # Quality score (weight: 1)
        scores.append(scanner_report.overall_score)
        weights.append(1.0)

        # Test pass rate (weight: 2)
        if test_report and test_report.total_tests > 0:
            pass_rate = (test_report.passed_tests / test_report.total_tests) * 100
            scores.append(pass_rate)
            weights.append(2.0)

        # Coverage (weight: 1)
        if test_report and test_report.coverage_percent > 0:
            scores.append(test_report.coverage_percent)
            weights.append(1.0)

        if not scores:
            return 0.0

        return sum(s * w for s, w in zip(scores, weights)) / sum(weights)

    def save_report(self, report: QualityGateReport, path: str) -> None:
        """Save report to JSON file."""
        with open(path, 'w') as f:
            json.dump(report.to_dict(), f, indent=2)
