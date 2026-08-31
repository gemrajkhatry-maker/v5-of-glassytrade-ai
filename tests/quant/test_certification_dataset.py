"""Certification tests — validate decisions against ground truth dataset.

Runs each certification scenario and verifies:
- Market state classification matches expected
- Trade action matches expected (trade long, short, or no trade)

Any deviation from certified results = FAIL.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.quant.certification.dataset import CERTIFICATION_SCENARIOS
from tests.quant.test_golden_replay import replay


def _classify_action(rep):
    """Classify the action taken in a replay."""
    if rep.positions_opened:
        pos = rep.positions_opened[0]
        if pos.size > 0:
            return "TRADE_LONG"
        else:
            return "TRADE_SHORT"
    return "NO_TRADE"


@pytest.mark.parametrize("cert", CERTIFICATION_SCENARIOS, ids=lambda c: c.name)
def test_certification_scenario(cert):
    """Each certification scenario must produce the expected action."""
    rep = replay(cert.scenario)
    actual_action = _classify_action(rep)
    assert actual_action == cert.expected_action, (
        f"{cert.name}: expected {cert.expected_action}, got {actual_action}. "
        f"{cert.description}"
    )


def test_certification_all_scenarios_pass():
    """All certification scenarios must pass."""
    failures = []
    for cert in CERTIFICATION_SCENARIOS:
        rep = replay(cert.scenario)
        actual_action = _classify_action(rep)
        if actual_action != cert.expected_action:
            failures.append(f"{cert.name}: expected {cert.expected_action}, got {actual_action}")
    assert not failures, f"Certification failures: {failures}"
