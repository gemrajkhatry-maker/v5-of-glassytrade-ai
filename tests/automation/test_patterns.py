from automation.quality.patterns import PatternDetector


def test_detect_bare_except():
    """Bare except clauses are detected."""
    detector = PatternDetector()
    code = """
def bad_function():
    try:
        x = 1 / 0
    except:
        pass
"""
    issues = detector.detect_patterns("test.py", code)
    assert any(i.rule == "pattern.bare_except" for i in issues)


def test_detect_silent_except_pass():
    """Silent except:pass is detected."""
    detector = PatternDetector()
    code = """
def bad_function():
    try:
        x = 1 / 0
    except Exception:
        pass
"""
    issues = detector.detect_patterns("test.py", code)
    assert any(i.rule == "pattern.silent_except_pass" for i in issues)


def test_detect_mutable_defaults():
    """Mutable default arguments are detected."""
    detector = PatternDetector()
    code = """
def bad_function(items=[]):
    return items
"""
    issues = detector.detect_patterns("test.py", code)
    assert any(i.rule == "pattern.mutable_default" for i in issues)


def test_detect_unused_imports():
    """Unused imports are detected."""
    detector = PatternDetector()
    code = """
import os
import sys

def function():
    return os.getcwd()
"""
    issues = detector.detect_patterns("test.py", code)
    # sys is unused
    assert any(i.rule == "pattern.unused_import" and "sys" in i.message for i in issues)


def test_no_false_positives_on_clean_code():
    """Clean code produces no pattern issues."""
    detector = PatternDetector()
    code = """
import os

def good_function():
    try:
        return os.getcwd()
    except OSError as e:
        print(f"Error: {e}")
        return None
"""
    issues = detector.detect_patterns("test.py", code)
    # Should have no issues (os is used, except has logging)
    assert len(issues) == 0


def test_pattern_detector_handles_syntax_errors():
    """Invalid Python doesn't crash the detector."""
    detector = PatternDetector()
    code = "def broken(:\n    pass"
    issues = detector.detect_patterns("test.py", code)
    assert isinstance(issues, list)


def test_scanner_integrates_pattern_detection():
    """CodeQualityScanner includes pattern detection in scan()."""
    from automation.quality.scanner import CodeQualityScanner

    scanner = CodeQualityScanner("automation/config/quality_rules.yaml")
    # Create a test file with patterns
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write("""
def bad(items=[]):
    try:
        pass
    except:
        pass
""")
        temp_path = f.name

    try:
        report = scanner.scan(temp_path)
        # Should find mutable_default and bare_except
        assert any(i.rule == "pattern.mutable_default" for i in report.issues)
        assert any(i.rule == "pattern.bare_except" for i in report.issues)
    finally:
        os.unlink(temp_path)
