"""Certification dataset — hand-labeled sessions with expected outcomes.

Each session has:
- ticks: scripted market data
- expected_market_state: BALANCED or IMBALANCED
- expected_action: TRADE_LONG, TRADE_SHORT, or NO_TRADE
- description: human-readable explanation

This is the ground truth. Future changes must not alter certified results
without explanation.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from quant.brokers.gateway import Tick
from tests.quant.test_golden_replay import Scenario


def _t(epoch_sec: int) -> str:
    return str(epoch_sec)


@dataclass
class CertScenario:
    name: str
    scenario: Scenario
    expected_market_state: str  # "BALANCED" | "IMBALANCED"
    expected_action: str  # "TRADE_LONG" | "TRADE_SHORT" | "NO_TRADE"
    description: str


# ---------------------------------------------------------------------------
# Certification scenarios
# ---------------------------------------------------------------------------

def cert_balanced_chop() -> CertScenario:
    """Price oscillates inside VA — must stay BALANCED and NOT trade."""
    ticks = []
    t0 = 1_787_664_600
    for i in range(240):
        price = 100.0 + 0.05 * (i % 12 - 6) / 6  # ±0.05 wiggle
        vol = 10.0
        ticks.append(Tick(_t(t0 + i), round(price, 4), vol, vol * 0.5, vol * 0.5))
    return CertScenario(
        name="balanced_chop",
        scenario=Scenario("balanced_chop", ticks, interval_seconds=1),
        expected_market_state="BALANCED",
        expected_action="NO_TRADE",
        description="Price oscillates inside VA — must stay BALANCED and NOT trade",
    )


def cert_trend_displacement() -> CertScenario:
    """Displacement without Triple-A AGGRESSION — must NOT trade.

    The system correctly requires confirmed Triple-A AGGRESSION (absorption →
    accumulation → aggression) before entering. Displacement alone is not
    an entry signal — this prevents chasing unconfirmed breakouts.
    """
    ticks = []
    t0 = 1_787_664_600
    sec = t0
    # Quiet accumulation
    for i in range(60):
        price = 100.0 + 0.02 * ((i % 4) - 1.5)
        vol = 8.0
        ticks.append(Tick(_t(sec), round(price, 4), vol, vol / 2, vol / 2))
        sec += 1
    # Displacement UP (but no confirmed Triple-A AGGRESSION)
    price = 100.05
    for i in range(50):
        price += 0.06
        vol = 30.0 + i
        ticks.append(Tick(_t(sec), round(price, 4), vol, vol * 0.85, vol * 0.15))
        sec += 1
    return CertScenario(
        name="trend_displacement_no_aggression",
        scenario=Scenario("trend_displacement_no_aggression", ticks, interval_seconds=1),
        expected_market_state="IMBALANCED",
        expected_action="NO_TRADE",
        description="Displacement without Triple-A AGGRESSION — must NOT trade (correct behavior)",
    )


def cert_stop_out() -> CertScenario:
    """Displacement without Triple-A AGGRESSION — must NOT trade.

    The stop_out scenario from golden replay also doesn't produce a trade
    because the system correctly requires confirmed Triple-A AGGRESSION
    (absorption → accumulation → aggression) before entering. The short
    displacement leg alone is not an entry signal.
    """
    ticks = []
    t0 = 1_787_664_600
    sec = t0
    # Build VA high
    for i in range(60):
        price = 102.0 + 0.02 * ((i % 4) - 1.5)
        vol = 8.0
        ticks.append(Tick(_t(sec), round(price, 4), vol, vol / 2, vol / 2))
        sec += 1
    # Displacement DOWN (but no confirmed Triple-A AGGRESSION)
    price = 101.95
    for i in range(12):
        price -= 0.06
        vol = 28.0 + i
        ticks.append(Tick(_t(sec), round(price, 4), vol, vol * 0.15, vol * 0.85))
        sec += 1
    # Adverse reversal (not an entry signal without Triple-A)
    for i in range(25):
        price += 0.09
        vol = 35.0
        ticks.append(Tick(_t(sec), round(price, 4), vol, vol * 0.9, vol * 0.1))
        sec += 1
    return CertScenario(
        name="stop_out_no_aggression",
        scenario=Scenario("stop_out_no_aggression", ticks, interval_seconds=1),
        expected_market_state="IMBALANCED",
        expected_action="NO_TRADE",
        description="Displacement without Triple-A AGGRESSION — must NOT trade (correct behavior)",
    )


# ---------------------------------------------------------------------------
# All certification scenarios
# ---------------------------------------------------------------------------

CERTIFICATION_SCENARIOS = [
    cert_balanced_chop(),
    cert_trend_displacement(),
    cert_stop_out(),
]
