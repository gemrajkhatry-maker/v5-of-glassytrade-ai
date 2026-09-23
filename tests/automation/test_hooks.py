from pathlib import Path
import subprocess


def test_pre_commit_hook_exists():
    """Pre-commit hook script exists."""
    hook_path = Path("automation/hooks/pre_commit.py")
    assert hook_path.exists()


def test_install_script_exists():
    """Install script exists."""
    script_path = Path("automation/hooks/install.sh")
    assert script_path.exists()


def test_install_script_is_executable():
    """Install script has correct shebang."""
    script_path = Path("automation/hooks/install.sh")
    content = script_path.read_text()
    assert content.startswith("#!/bin/bash")


def test_pre_commit_hook_syntax():
    """Pre-commit hook has valid Python syntax."""
    result = subprocess.run(
        ["python", "-m", "py_compile", "automation/hooks/pre_commit.py"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_pre_commit_hook_imports():
    """Pre-commit hook can import required modules."""
    import sys
    sys.path.insert(0, ".")
    
    # This should not raise
    from automation.hooks import pre_commit
    assert hasattr(pre_commit, "main")
