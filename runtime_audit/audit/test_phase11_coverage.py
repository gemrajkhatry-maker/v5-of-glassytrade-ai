"""PHASE 11 — coverage audit over the REAL pipeline + dead-code cross-check.

Run:  PYTHONPATH=backend:. .venv/bin/python -m pytest runtime_audit/audit/test_phase11_coverage.py -q -s

1. Runs `pytest tests/quant/runtime --cov=quant --cov-report=term-missing` as a
   subprocess and parses per-module coverage for critical-path modules.
2. Re-runs the AST dead-code scan (runtime_audit/audit/dead_code_scan.py) and
   cross-checks the known-dead list for zero-importer status TODAY.
3. Emits explicit FAIL lines for any critical module with coverage < 70%.
Writes: runtime_audit/out/coverage_report.txt (+ dead_code_report.txt via scan)
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CRITICAL_MODULES = [
    "quant/runtime.py",
    "quant/multi_engine.py",
    "quant/state.py",
    "quant/ws_adapter.py",
]
CRITICAL_PREFIXES = ["quant/decision/", "quant/execution/"]
THRESHOLD = 70.0


def run_coverage() -> str:
    cmd = [
        ".venv/bin/python", "-m", "pytest", "tests/quant/runtime", "-q",
        "--cov=quant", "--cov-report=term-missing",
    ]
    env = {"PYTHONPATH": "backend:.", "PATH": "/usr/bin:/bin:/usr/local/bin",
           "HOME": str(Path.home())}
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          env=env, timeout=900)
    return proc.stdout + "\n" + proc.stderr


def parse_coverage(text: str) -> dict[str, tuple[int, int, float]]:
    """module -> (stmts, miss, cover%)"""
    out = {}
    pat = re.compile(
        r"^(quant/[\w/]+\.py)\s+(\d+)\s+(\d+)\s+(\d+)%", re.M
    )
    for m in pat.finditer(text):
        out[m.group(1)] = (int(m.group(2)), int(m.group(3)), float(m.group(4)))
    return out


def is_critical(module: str) -> bool:
    if module in CRITICAL_MODULES:
        return True
    return any(module.startswith(p) for p in CRITICAL_PREFIXES)


def main() -> None:
    print("[phase11] running coverage over tests/quant/runtime ...")
    raw = run_coverage()
    (ROOT / "runtime_audit/out/coverage_raw.txt").write_text(raw)
    cov = parse_coverage(raw)

    lines = []
    lines.append("=" * 78)
    lines.append("COVERAGE REPORT — tests/quant/runtime over quant/* (real pipeline)")
    lines.append("=" * 78)
    lines.append(f"{'module':<46}{'stmts':>7}{'miss':>7}{'cover%':>9}  verdict")
    lines.append("-" * 78)
    fails = []
    for mod in sorted(cov):
        stmts, miss, pct = cov[mod]
        verdict = ""
        if is_critical(mod):
            verdict = "PASS" if pct >= THRESHOLD else "FAIL (<70%)"
            if pct < THRESHOLD:
                fails.append((mod, pct))
        lines.append(f"{mod:<46}{stmts:>7}{miss:>7}{pct:>8.0f}%  {verdict}")
    total = re.search(r"^TOTAL\s+\d+\s+\d+\s+(\d+)%", raw, re.M)
    lines.append("-" * 78)
    if total:
        lines.append(f"TOTAL: {total.group(1)}%")
    lines.append("")
    lines.append("## EXPLICIT FAIL LINES (critical-path modules below 70%)")
    if not fails:
        lines.append("  (none)")
    for mod, pct in fails:
        lines.append(f"FAIL: {mod} coverage {pct:.0f}% < {THRESHOLD:.0f}% threshold")

    report = "\n".join(lines)
    (ROOT / "runtime_audit/out/coverage_report.txt").write_text(report)
    print(report)

    # Dead-code cross-check (writes dead_code_report.txt too).
    print("\n[phase11] running AST dead-code scan ...")
    sys.path.insert(0, str(ROOT / "runtime_audit/audit"))
    import dead_code_scan  # noqa: E402
    dead_code_scan.main()


def test_phase11_coverage_and_dead_code():
    main()


if __name__ == "__main__":
    main()
