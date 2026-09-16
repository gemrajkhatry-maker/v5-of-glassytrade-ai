from automation.fixes.generator import FixGenerator, FixProposal
from automation.quality import QualityIssue


def test_fix_generator_initializes():
    """FixGenerator can be instantiated."""
    generator = FixGenerator()
    assert generator is not None


def test_fix_unused_import():
    """FixGenerator can remove unused imports."""
    generator = FixGenerator()
    source = """import os
import sys

def function():
    return os.getcwd()
"""
    issue = QualityIssue(
        file="test.py",
        line=2,
        rule="pattern.unused_import",
        severity="info",
        message="Import 'sys' appears unused"
    )
    
    proposals = generator.generate_fixes([issue], source)
    assert len(proposals) == 1
    assert "sys" not in proposals[0].fixed_code
    assert "import os" in proposals[0].fixed_code


def test_fix_mutable_default_list():
    """FixGenerator can fix mutable list defaults."""
    generator = FixGenerator()
    source = """def function(items=[]):
    return items
"""
    issue = QualityIssue(
        file="test.py",
        line=1,
        rule="pattern.mutable_default",
        severity="error",
        message="Function 'function' has mutable default argument"
    )
    
    proposals = generator.generate_fixes([issue], source)
    assert len(proposals) == 1
    assert "items=None" in proposals[0].fixed_code
    assert "if items is None" in proposals[0].fixed_code


def test_fix_proposal_is_safe():
    """FixProposal.is_safe returns True for high confidence."""
    issue = QualityIssue("test.py", 1, "test", "info", "test")
    proposal = FixProposal(
        issue=issue,
        original_code="x",
        fixed_code="y",
        description="test",
        confidence=0.95
    )
    assert proposal.is_safe is True


def test_fix_proposal_not_safe_low_confidence():
    """FixProposal.is_safe returns False for low confidence."""
    issue = QualityIssue("test.py", 1, "test", "info", "test")
    proposal = FixProposal(
        issue=issue,
        original_code="x",
        fixed_code="y",
        description="test",
        confidence=0.5
    )
    assert proposal.is_safe is False


def test_generator_skips_non_fixable_rules():
    """FixGenerator skips rules that can't be auto-fixed."""
    generator = FixGenerator()
    source = "x = 1"
    issue = QualityIssue(
        file="test.py",
        line=1,
        rule="complexity.cyclomatic",  # Not auto-fixable
        severity="warning",
        message="Too complex"
    )
    
    proposals = generator.generate_fixes([issue], source)
    assert len(proposals) == 0


def test_apply_fix_writes_file(tmp_path):
    """apply_fix writes the fixed code to a file."""
    generator = FixGenerator()
    
    test_file = tmp_path / "test.py"
    test_file.write_text("import os\nimport sys\n")
    
    issue = QualityIssue(
        file=str(test_file),
        line=2,
        rule="pattern.unused_import",
        severity="info",
        message="Import 'sys' appears unused"
    )
    
    source = test_file.read_text()
    proposals = generator.generate_fixes([issue], source)
    assert len(proposals) == 1
    
    result = generator.apply_fix(proposals[0], str(test_file))
    assert result is True
    
    fixed_content = test_file.read_text()
    assert "sys" not in fixed_content
