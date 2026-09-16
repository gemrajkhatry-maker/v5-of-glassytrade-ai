import subprocess
import re
from dataclasses import dataclass
from typing import List, Dict, Optional
from pathlib import Path


@dataclass
class FileCoverage:
    """Coverage data for a single file."""
    file: str
    total_lines: int
    covered_lines: int
    missing_lines: List[int]
    coverage_percent: float


@dataclass
class CoverageReport:
    """Overall coverage analysis."""
    total_coverage: float
    files: List[FileCoverage]
    low_coverage_files: List[FileCoverage]
    threshold: float


class CoverageAnalyzer:
    """Analyzes test coverage and identifies gaps."""
    
    def __init__(
        self,
        source_path: str = "quant",
        test_path: str = "tests",
        coverage_threshold: float = 80.0,
    ):
        self.source_path = source_path
        self.test_path = test_path
        self.coverage_threshold = coverage_threshold
    
    def analyze(self) -> CoverageReport:
        """Run coverage analysis and return report."""
        # Run pytest with coverage
        cmd = [
            "python", "-m", "pytest", self.test_path,
            f"--cov={self.source_path}",
            "--cov-report=term-missing",
            "-q"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        # Parse coverage output
        files = self._parse_coverage_output(result.stdout)
        total_coverage = self._calculate_total_coverage(files)
        low_coverage = [f for f in files if f.coverage_percent < self.coverage_threshold]
        
        return CoverageReport(
            total_coverage=total_coverage,
            files=files,
            low_coverage_files=low_coverage,
            threshold=self.coverage_threshold,
        )
    
    def _parse_coverage_output(self, output: str) -> List[FileCoverage]:
        """Parse pytest-cov output to extract file coverage."""
        files = []
        
        # Look for lines like: quant/engine/scanner.py    50     10    80%   15-25, 30-35
        pattern = r'(\S+\.py)\s+(\d+)\s+(\d+)\s+(\d+)%\s*(.*)'
        
        for line in output.split('\n'):
            match = re.match(pattern, line)
            if match:
                file_path = match.group(1)
                total = int(match.group(2))
                missing_count = int(match.group(3))
                percent = int(match.group(4))
                missing_str = match.group(5).strip()
                
                # Parse missing line numbers
                missing_lines = self._parse_missing_lines(missing_str)
                covered = total - missing_count
                
                files.append(FileCoverage(
                    file=file_path,
                    total_lines=total,
                    covered_lines=covered,
                    missing_lines=missing_lines,
                    coverage_percent=float(percent),
                ))
        
        return files
    
    def _parse_missing_lines(self, missing_str: str) -> List[int]:
        """Parse missing line ranges like '15-25, 30-35'."""
        if not missing_str:
            return []
        
        lines = []
        for part in missing_str.split(','):
            part = part.strip()
            if '-' in part:
                start, end = part.split('-')
                lines.extend(range(int(start), int(end) + 1))
            elif part.isdigit():
                lines.append(int(part))
        
        return sorted(lines)
    
    def _calculate_total_coverage(self, files: List[FileCoverage]) -> float:
        """Calculate overall coverage percentage."""
        if not files:
            return 0.0
        
        total_lines = sum(f.total_lines for f in files)
        covered_lines = sum(f.covered_lines for f in files)
        
        if total_lines == 0:
            return 0.0
        
        return (covered_lines / total_lines) * 100
    
    def get_uncovered_functions(self, file_path: str) -> List[str]:
        """Get list of uncovered functions in a file (simplified)."""
        # This would require parsing the source and mapping to coverage
        # For now, return empty list
        return []
