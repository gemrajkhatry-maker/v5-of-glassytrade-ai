import json
import subprocess
import re
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict
from pathlib import Path
from datetime import datetime


@dataclass
class BenchmarkResult:
    """A single benchmark measurement."""
    name: str
    mean_seconds: float
    stddev_seconds: float
    rounds: int


@dataclass
class PerformanceReport:
    """Performance analysis results."""
    timestamp: str
    benchmarks: List[BenchmarkResult]
    regressions: List[str]
    improvements: List[str]
    baseline_path: str


class PerformanceDetector:
    """Detects performance regressions using pytest-benchmark."""
    
    def __init__(
        self,
        baseline_path: str = "automation/performance/baseline.json",
        regression_threshold: float = 0.10,  # 10% slowdown
    ):
        self.baseline_path = Path(baseline_path)
        self.regression_threshold = regression_threshold
        self.baseline_path.parent.mkdir(parents=True, exist_ok=True)
    
    def run_benchmarks(self, test_path: str) -> List[BenchmarkResult]:
        """Run pytest-benchmark and parse results."""
        cmd = [
            "python", "-m", "pytest", test_path,
            "--benchmark-only",
            "--benchmark-json=/tmp/bench_results.json",
            "-q"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        # Parse JSON output
        try:
            with open("/tmp/bench_results.json") as f:
                data = json.load(f)
            
            benchmarks = []
            for bench in data.get("benchmarks", []):
                benchmarks.append(BenchmarkResult(
                    name=bench["name"],
                    mean_seconds=bench["stats"]["mean"],
                    stddev_seconds=bench["stats"]["stddev"],
                    rounds=bench["stats"]["rounds"],
                ))
            return benchmarks
        except Exception:
            return []
    
    def compare_with_baseline(
        self, current: List[BenchmarkResult]
    ) -> PerformanceReport:
        """Compare current results against baseline."""
        timestamp = datetime.now().isoformat()
        regressions = []
        improvements = []
        
        baseline = self._load_baseline()
        
        for bench in current:
            if bench.name in baseline:
                old_mean = baseline[bench.name]
                change = (bench.mean_seconds - old_mean) / old_mean
                
                if change > self.regression_threshold:
                    regressions.append(
                        f"{bench.name}: {change*100:.1f}% slower "
                        f"({old_mean*1000:.2f}ms → {bench.mean_seconds*1000:.2f}ms)"
                    )
                elif change < -self.regression_threshold:
                    improvements.append(
                        f"{bench.name}: {abs(change)*100:.1f}% faster "
                        f"({old_mean*1000:.2f}ms → {bench.mean_seconds*1000:.2f}ms)"
                    )
        
        return PerformanceReport(
            timestamp=timestamp,
            benchmarks=current,
            regressions=regressions,
            improvements=improvements,
            baseline_path=str(self.baseline_path),
        )
    
    def save_baseline(self, benchmarks: List[BenchmarkResult]) -> None:
        """Save current results as the new baseline."""
        data = {b.name: b.mean_seconds for b in benchmarks}
        with open(self.baseline_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    def _load_baseline(self) -> Dict[str, float]:
        """Load baseline from file."""
        if not self.baseline_path.exists():
            return {}
        
        with open(self.baseline_path) as f:
            return json.load(f)
    
    def has_baseline(self) -> bool:
        """Check if a baseline exists."""
        return self.baseline_path.exists()
