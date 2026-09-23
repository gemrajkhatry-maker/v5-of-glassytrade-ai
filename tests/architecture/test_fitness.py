"""
Architecture Fitness Functions — automated guardians of Clean Architecture.

These tests enforce structural constraints that must never be violated.
DO NOT skip or delete these tests.
"""
import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
QUANT_DIR = ROOT / "quant"


def _python_files(directory: Path):
    return [p for p in directory.rglob('*.py') if '__pycache__' not in str(p) and 'test' not in p.name]


def _imports_in_file(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'))
    except SyntaxError:
        return []
    result = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.append(node.module)
    return result


class TestDomainIsolation:
    FORBIDDEN_IN_QUANT = ['brokers', 'backend', 'uvicorn', 'fastapi', 'sqlalchemy']
    ALLOWED_FILES = {'constants.py'}  # legitimately reads backend/config/base.yaml via file IO

    def test_quant_does_not_import_brokers_or_backend(self):
        violations = []
        for py_file in _python_files(QUANT_DIR):
            if py_file.name in self.ALLOWED_FILES:
                continue
            for imp in _imports_in_file(py_file):
                for forbidden in self.FORBIDDEN_IN_QUANT:
                    if imp == forbidden or imp.startswith(forbidden + '.'):
                        violations.append(f'{py_file.relative_to(ROOT)}: imports {imp}')
        assert not violations, 'Domain (quant/) imports infrastructure:\\n' + '\\n'.join(violations)

    def test_no_environment_branching_in_quant(self):
        pattern = re.compile(r'["\'](?:live|paper|backtest|replay)["\']', re.IGNORECASE)
        violations = []
        for py_file in _python_files(QUANT_DIR):
            for i, line in enumerate(py_file.read_text(encoding='utf-8').splitlines(), 1):
                if pattern.search(line) and 'if ' in line:
                    violations.append(f'{py_file.relative_to(ROOT)}:{i}: {line.strip()}')
        assert not violations, 'Environment branches in domain:\\n' + '\\n'.join(violations)


class TestTradingInvariants:
    def test_value_area_pct_is_fabio_canonical(self):
        sys.path.insert(0, str(ROOT / 'backend'))
        sys.path.insert(0, str(ROOT))
        from quant.contracts.constants import VALUE_AREA_PCT
        assert VALUE_AREA_PCT == pytest.approx(0.682), (
            f'VALUE_AREA_PCT={VALUE_AREA_PCT} — must match Fabio AMT spec §5.1 rule 3 '
            '(VA = 68.2% of total volume). A wider VA reclassifies imbalanced conditions '
            'as balanced, which changes trade selection.'
        )

    def test_min_rr_is_fabio_minimum(self):
        sys.path.insert(0, str(ROOT / 'backend'))
        sys.path.insert(0, str(ROOT))
        from quant.contracts.constants import MIN_RR_RATIO
        assert MIN_RR_RATIO >= 1.5, f'MIN_RR={MIN_RR_RATIO} — Fabio requires >= 1.5'

    def test_gate_count_is_four(self):
        sys.path.insert(0, str(ROOT / 'backend'))
        sys.path.insert(0, str(ROOT))
        from quant.decision.result import GATE_NAMES
        assert len(GATE_NAMES) == 4, f'Expected 4 gates, found {len(GATE_NAMES)}'
        assert all(GATE_NAMES.values()), 'All gate names must be non-empty strings'

    def test_signal_reason_string_is_current(self):
        """Ensure the '7 gates' ghost string is not reintroduced."""
        signal_file = ROOT / 'quant' / 'decision' / 'signal_builder.py'
        content = signal_file.read_text()
        assert '7 gates' not in content, (
            "Stale '7 gates' string found in signal_builder.py — must be '4 gates'"
        )
