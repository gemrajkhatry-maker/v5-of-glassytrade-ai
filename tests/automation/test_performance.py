from automation.performance.detector import (
    PerformanceDetector,
    BenchmarkResult,
    PerformanceReport,
)


def test_performance_detector_initializes():
    """PerformanceDetector can be instantiated."""
    detector = PerformanceDetector()
    assert detector is not None
    assert detector.regression_threshold == 0.10


def test_benchmark_result_dataclass():
    """BenchmarkResult stores measurement data."""
    result = BenchmarkResult(
        name="test_function",
        mean_seconds=0.001,
        stddev_seconds=0.0001,
        rounds=100,
    )
    assert result.name == "test_function"
    assert result.mean_seconds == 0.001


def test_performance_report_dataclass():
    """PerformanceReport stores analysis results."""
    report = PerformanceReport(
        timestamp="2026-09-16T12:00:00",
        benchmarks=[],
        regressions=["test_foo: 15% slower"],
        improvements=[],
        baseline_path="baseline.json",
    )
    assert len(report.regressions) == 1


def test_detector_saves_baseline(tmp_path):
    """Detector can save baseline to file."""
    baseline_path = tmp_path / "baseline.json"
    detector = PerformanceDetector(baseline_path=str(baseline_path))
    
    benchmarks = [
        BenchmarkResult("test_a", 0.001, 0.0001, 100),
        BenchmarkResult("test_b", 0.002, 0.0002, 100),
    ]
    
    detector.save_baseline(benchmarks)
    assert baseline_path.exists()


def test_detector_loads_baseline(tmp_path):
    """Detector can load baseline from file."""
    baseline_path = tmp_path / "baseline.json"
    detector = PerformanceDetector(baseline_path=str(baseline_path))
    
    benchmarks = [BenchmarkResult("test_a", 0.001, 0.0001, 100)]
    detector.save_baseline(benchmarks)
    
    assert detector.has_baseline()


def test_detector_detects_regression(tmp_path):
    """Detector identifies performance regressions."""
    baseline_path = tmp_path / "baseline.json"
    detector = PerformanceDetector(
        baseline_path=str(baseline_path),
        regression_threshold=0.10,
    )
    
    # Save baseline
    old_benchmarks = [BenchmarkResult("test_a", 0.001, 0.0001, 100)]
    detector.save_baseline(old_benchmarks)
    
    # Current is 20% slower
    current = [BenchmarkResult("test_a", 0.0012, 0.0001, 100)]
    report = detector.compare_with_baseline(current)
    
    assert len(report.regressions) == 1
    assert "slower" in report.regressions[0]


def test_detector_detects_improvement(tmp_path):
    """Detector identifies performance improvements."""
    baseline_path = tmp_path / "baseline.json"
    detector = PerformanceDetector(
        baseline_path=str(baseline_path),
        regression_threshold=0.10,
    )
    
    # Save baseline
    old_benchmarks = [BenchmarkResult("test_a", 0.001, 0.0001, 100)]
    detector.save_baseline(old_benchmarks)
    
    # Current is 20% faster
    current = [BenchmarkResult("test_a", 0.0008, 0.0001, 100)]
    report = detector.compare_with_baseline(current)
    
    assert len(report.improvements) == 1
    assert "faster" in report.improvements[0]


def test_detector_no_baseline_returns_empty(tmp_path):
    """Detector handles missing baseline gracefully."""
    baseline_path = tmp_path / "nonexistent.json"
    detector = PerformanceDetector(baseline_path=str(baseline_path))
    
    current = [BenchmarkResult("test_a", 0.001, 0.0001, 100)]
    report = detector.compare_with_baseline(current)
    
    assert len(report.regressions) == 0
    assert len(report.improvements) == 0
