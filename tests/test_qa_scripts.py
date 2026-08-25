# tests/test_qa_scripts.py
"""Test that QA sanity scripts execute cleanly (Task 10)."""

import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)


def _run_qa_script(rel_path: str) -> subprocess.CompletedProcess:
    script = Path(_REPO_ROOT) / rel_path
    # The scripts import `quant.*` directly — they need the repo root on
    # sys.path. Inheriting the parent env keeps any venv PYTHONPATH intact.
    env = dict(os.environ)
    env["PYTHONPATH"] = _REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, env=env,
        cwd=_REPO_ROOT,
    )


def test_qa_sanity_components_script():
    res = _run_qa_script("tests/qa/qa_sanity_components.py")
    assert res.returncode == 0, f"qa_sanity_components.py failed:\n{res.stderr}\n{res.stdout}"


def test_qa_sanity_full_infra_script():
    res = _run_qa_script("tests/qa/qa_sanity_full_infra.py")
    assert res.returncode == 0, f"qa_sanity_full_infra.py failed:\n{res.stderr}\n{res.stdout}"
