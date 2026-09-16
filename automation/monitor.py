import time
import json
from dataclasses import dataclass, asdict
from typing import List, Optional
from pathlib import Path
from datetime import datetime

from automation.quality import QualityIssue
from automation.quality.scanner import CodeQualityScanner
from automation.testing.runner import TestRunner
from automation.fixes.generator import FixGenerator, FixProposal
from automation.orchestrator import QualityOrchestrator


@dataclass
class MonitorAction:
    """An action taken by the monitor."""
    timestamp: str
    action_type: str  # "scan", "fix_applied", "test_run", "issue_detected"
    details: dict
    success: bool


@dataclass
class MonitorReport:
    """Summary of a monitoring cycle."""
    cycle_start: str
    cycle_end: str
    issues_found: int
    fixes_proposed: int
    fixes_applied: int
    tests_passed: int
    tests_failed: int
    actions: List[MonitorAction]
    overall_status: str  # "healthy", "degraded", "critical"


class ContinuousMonitor:
    """Continuous monitoring and self-healing loop."""

    def __init__(
        self,
        source_path: str = "quant",
        test_path: str = "tests",
        scanner_config: str = "automation/config/quality_rules.yaml",
        auto_apply_fixes: bool = False,
        report_dir: str = "automation/reports",
    ):
        self.source_path = source_path
        self.test_path = test_path
        self.scanner_config = scanner_config
        self.auto_apply_fixes = auto_apply_fixes
        self.report_dir = Path(report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)

        self._scanner = CodeQualityScanner(scanner_config)
        self._runner = TestRunner()
        self._fixer = FixGenerator()
        self._orchestrator = QualityOrchestrator(scanner_config)

    def run_cycle(self) -> MonitorReport:
        """Run one complete monitoring cycle."""
        cycle_start = datetime.now().isoformat()
        actions: List[MonitorAction] = []

        # Step 1: Run quality scan
        scan_action = self._run_scan()
        actions.append(scan_action)

        # Step 2: Extract issues
        issues = self._extract_issues(scan_action)

        # Step 3: Generate fixes
        fixes_proposed = 0
        fixes_applied = 0
        if issues:
            fix_action = self._generate_and_apply_fixes(issues)
            actions.append(fix_action)
            fixes_proposed = fix_action.details.get("proposals", 0)
            fixes_applied = fix_action.details.get("applied", 0)

        # Step 4: Run tests to verify
        test_action = self._run_tests()
        actions.append(test_action)

        cycle_end = datetime.now().isoformat()

        # Determine overall status
        tests_passed = test_action.details.get("passed", 0)
        tests_failed = test_action.details.get("failed", 0)

        if tests_failed > 0:
            overall_status = "critical"
        elif len(issues) > 10:
            overall_status = "degraded"
        else:
            overall_status = "healthy"

        report = MonitorReport(
            cycle_start=cycle_start,
            cycle_end=cycle_end,
            issues_found=len(issues),
            fixes_proposed=fixes_proposed,
            fixes_applied=fixes_applied,
            tests_passed=tests_passed,
            tests_failed=tests_failed,
            actions=actions,
            overall_status=overall_status,
        )

        # Save report
        self._save_report(report)

        return report

    def _run_scan(self) -> MonitorAction:
        """Run quality scan."""
        timestamp = datetime.now().isoformat()
        try:
            report = self._scanner.scan(self.source_path)
            return MonitorAction(
                timestamp=timestamp,
                action_type="scan",
                details={
                    "files_scanned": report.files_scanned,
                    "issues_found": len(report.issues),
                    "score": report.overall_score,
                },
                success=True,
            )
        except Exception as e:
            return MonitorAction(
                timestamp=timestamp,
                action_type="scan",
                details={"error": str(e)},
                success=False,
            )

    def _extract_issues(self, scan_action: MonitorAction) -> List[QualityIssue]:
        """Extract issues from scan action."""
        # Re-run scan to get actual issues (action only has summary)
        report = self._scanner.scan(self.source_path)
        return report.issues

    def _generate_and_apply_fixes(self, issues: List[QualityIssue]) -> MonitorAction:
        """Generate and optionally apply fixes."""
        timestamp = datetime.now().isoformat()

        # Group issues by file
        issues_by_file: dict = {}
        for issue in issues:
            if issue.file not in issues_by_file:
                issues_by_file[issue.file] = []
            issues_by_file[issue.file].append(issue)

        total_proposals = 0
        total_applied = 0

        for filepath, file_issues in issues_by_file.items():
            try:
                source = Path(filepath).read_text()
                proposals = self._fixer.generate_fixes(file_issues, source)
                total_proposals += len(proposals)

                if self.auto_apply_fixes:
                    for proposal in proposals:
                        if proposal.is_safe:
                            if self._fixer.apply_fix(proposal, filepath):
                                total_applied += 1
            except Exception:
                continue

        return MonitorAction(
            timestamp=timestamp,
            action_type="fix_applied" if total_applied > 0 else "issue_detected",
            details={
                "proposals": total_proposals,
                "applied": total_applied,
                "auto_apply": self.auto_apply_fixes,
            },
            success=True,
        )

    def _run_tests(self) -> MonitorAction:
        """Run test suite."""
        timestamp = datetime.now().isoformat()
        try:
            report = self._runner.run_tests(self.test_path, with_coverage=False)
            return MonitorAction(
                timestamp=timestamp,
                action_type="test_run",
                details={
                    "total": report.total_tests,
                    "passed": report.passed_tests,
                    "failed": report.failed_tests,
                    "duration": report.duration_seconds,
                },
                success=report.failed_tests == 0,
            )
        except Exception as e:
            return MonitorAction(
                timestamp=timestamp,
                action_type="test_run",
                details={"error": str(e)},
                success=False,
            )

    def _save_report(self, report: MonitorReport) -> None:
        """Save report to JSON file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = self.report_dir / f"monitor_report_{timestamp}.json"

        data = {
            "cycle_start": report.cycle_start,
            "cycle_end": report.cycle_end,
            "issues_found": report.issues_found,
            "fixes_proposed": report.fixes_proposed,
            "fixes_applied": report.fixes_applied,
            "tests_passed": report.tests_passed,
            "tests_failed": report.tests_failed,
            "overall_status": report.overall_status,
            "actions": [asdict(a) for a in report.actions],
        }

        with open(report_path, 'w') as f:
            json.dump(data, f, indent=2)
