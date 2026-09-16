import subprocess
import time
import re
from dataclasses import dataclass
from typing import List


@dataclass
class TestReport:
    total_tests: int
    passed_tests: int
    failed_tests: int
    skipped_tests: int
    duration_seconds: float
    coverage_percent: float
    failed_test_names: List[str]


class TestRunner:
    def run_tests(self, test_path: str, with_coverage: bool = True) -> TestReport:
        """Run pytest on the specified path and return a structured report."""
        start_time = time.time()

        cmd = ["python", "-m", "pytest", test_path, "-v", "--tb=short"]
        if with_coverage:
            cmd.extend(["--cov=quant", "--cov-report=term-missing", "--no-cov-on-fail"])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        duration = time.time() - start_time

        # Parse pytest output
        total, passed, failed, skipped = self._parse_test_counts(result.stdout)
        coverage = self._parse_coverage(result.stdout) if with_coverage else 0.0
        failed_names = self._parse_failed_names(result.stdout)

        return TestReport(
            total_tests=total,
            passed_tests=passed,
            failed_tests=failed,
            skipped_tests=skipped,
            duration_seconds=duration,
            coverage_percent=coverage,
            failed_test_names=failed_names
        )

    def _parse_test_counts(self, output: str) -> tuple:
        """Parse test counts from pytest output."""
        # Look for patterns like "5 passed", "2 failed", "1 skipped"
        total = 0
        passed = 0
        failed = 0
        skipped = 0

        # Match summary line like "=== 5 passed, 2 failed, 1 skipped in 0.5s ==="
        summary_match = re.search(r'=\s*(.+?)\s*in\s*[\d.]+s\s*=', output)
        if summary_match:
            summary = summary_match.group(1)
            passed_match = re.search(r'(\d+)\s+passed', summary)
            failed_match = re.search(r'(\d+)\s+failed', summary)
            skipped_match = re.search(r'(\d+)\s+skipped', summary)

            passed = int(passed_match.group(1)) if passed_match else 0
            failed = int(failed_match.group(1)) if failed_match else 0
            skipped = int(skipped_match.group(1)) if skipped_match else 0
            total = passed + failed + skipped

        return total, passed, failed, skipped

    def _parse_coverage(self, output: str) -> float:
        """Parse coverage percentage from pytest output."""
        # Look for "Total coverage: XX.X%" or similar
        coverage_match = re.search(r'Total.*?(\d+)%', output)
        if coverage_match:
            return float(coverage_match.group(1))

        # Alternative: look for line like "quant/engine/scanner.py    50     10    80%"
        # Take the last percentage found
        percentages = re.findall(r'(\d+)%', output)
        if percentages:
            return float(percentages[-1])

        return 0.0

    def _parse_failed_names(self, output: str) -> List[str]:
        """Parse names of failed tests from pytest output."""
        failed = []
        # Look for lines like "FAILED tests/test_foo.py::test_bar"
        for match in re.finditer(r'FAILED\s+(\S+)', output):
            failed.append(match.group(1))
        return failed
