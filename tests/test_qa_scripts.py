# tests/test_qa_scripts.py
"""Test that QA sanity scripts execute cleanly (Task 10)."""

import subprocess
import sys
from pathlib import Path


def test_qa_sanity_components_script():
    script = Path(__file__).resolve().parent.parent / "qa_sanity_components.py"
    res = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert res.returncode == 0, f"qa_sanity_components.py failed:\n{res.stderr}\n{res.stdout}"


def test_qa_sanity_full_infra_script():
    script = Path(__file__).resolve().parent.parent / "qa_sanity_full_infra.py"
    res = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert res.returncode == 0, f"qa_sanity_full_infra.py failed:\n{res.stderr}\n{res.stdout}"
