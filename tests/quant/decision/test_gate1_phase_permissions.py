"""Gate 1 must honor the session table's trend/reversion permissions.

Regression guard for the midday veto dropped in commit ae0d832: the
phase table (quant/amt/session/context.py) still computes allow_trend /
allow_reversion, but no decision-gate consumer survived the
consolidation. tests/integration/test_fabio_india_scenarios.py
documents the intended behavior; these unit tests pin it at the gate
level so WS2 refactors cannot silently re-sever the wire.
"""

from datetime import datetime

import pytest

from quant.amt.session.context import get_session_info
from quant.contracts.enums import MarketState
from quant.decision.context import DecisionContext
from quant.decision.gates_session_position import gate_session_phase
from quant.decision.result import GateResult  # noqa: F401  (re-export check)
from quant.decision.setup_state import SetupEvidence


def _make_bar(time_iso: str):
    from quant.bars import Bar

    return Bar(
        time=time_iso,
        open=24700.0,
        high=24730.0,
        low=24690.0,
        close=24720.0,
        volume=2000.0,
        buy_volume=1250.0,
        sell_volume=750.0,
    )


_EVIDENCE = SetupEvidence(
    setup_type="TRIPLE_A",
    direction="LONG",
    absorption=True,
    accumulation=True,
    aggression=True,
    acceptance=True,
    cvd_agrees=True,
)


def _ctx(bar_time: str, setup_type: str = "TRIPLE_A") -> DecisionContext:
    info = get_session_info(bar_time, market="NSE")
    evidence = (
        _EVIDENCE
        if setup_type == "TRIPLE_A"
        else SetupEvidence(
            setup_type="VA_FADE",
            direction="SHORT",
            rejection=True,
            cvd_agrees=True,
        )
    )
    return DecisionContext(
        bar=_make_bar(bar_time),
        symbol="NIFTY",
        session_open=True,
        warmup_complete=True,
        position_open=False,
        agent_direction=evidence.direction,
        agent_probability=0.80,
        market_state=MarketState.IMBALANCED,
        setup_evidence=evidence,
        vah=24650.0,
        val=24550.0,
        poc=24600.0,
        allow_trend=info.allow_trend,
        allow_reversion=info.allow_reversion,
    )


def test_primary_window_allows_momentum_setup():
    result = gate_session_phase(_ctx("2026-08-19T10:45:00+05:30"))
    assert result.passed is True


def test_midday_blocks_momentum_setup():
    """12:45 IST is Phase 3 (allow_trend=False): TRIPLE_A must be blocked."""
    result = gate_session_phase(_ctx("2026-08-19T12:45:00+05:30"))
    assert result.passed is False
    assert "SESSION_PHASE" in result.reason or "trend" in result.reason.lower()


def test_midday_allows_reversion_setup():
    """Phase 3 favors mean reversion: VA_FADE passes the phase permission."""
    ctx = _ctx("2026-08-19T12:45:00+05:30", setup_type="VA_FADE")
    result = gate_session_phase(ctx)
    assert result.passed is True


def test_phase_table_and_gate_agree_on_vocabulary():
    """The permission fields the gate reads are populated by the table."""
    midday = get_session_info("2026-08-19T12:45:00+05:30", market="NSE")
    primary = get_session_info("2026-08-19T10:45:00+05:30", market="NSE")
    assert (midday.allow_trend, midday.allow_reversion) == (False, True)
    assert (primary.allow_trend, primary.allow_reversion) == (True, True)


@pytest.mark.parametrize(
    "time_iso,expected",
    [
        ("2026-08-19T09:20:00+05:30", False),  # Phase 1 opening noise
        ("2026-08-19T15:30:00+05:30", False),  # post close
    ],
)
def test_closed_windows_block_everything(time_iso: str, expected: bool):
    info = get_session_info(time_iso, market="NSE")
    assert info.allow_entry is expected
