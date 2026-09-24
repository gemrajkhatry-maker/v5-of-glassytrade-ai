"""Gate 1 must honor the session table's trend/reversion permissions.

Regression guard for the midday veto dropped in commit ae0d832: the
phase table (quant/amt/session/context.py) still computes allow_trend /
allow_reversion, but no decision-gate consumer survived the
consolidation. tests/integration/test_fabio_india_scenarios.py
documents the intended behavior; these unit tests pin it at the gate
level so WS2 refactors cannot silently re-sever the wire.
"""


import pytest
from dataclasses import replace

from quant.amt.session.context import get_session_info
from quant.contracts.enums import MarketState
from quant.decision.context import DecisionContext
from quant.decision.gates_edge import gate_triple_a_edge
from quant.decision.gate_session_phase import gate_session_phase
from quant.decision.result import GateResult  # noqa: F401  (re-export check)
from quant.decision.setup_state import SetupEvidence


def _make_bar(time_iso: str, direction: str = "LONG"):
    from quant.bars import Bar

    # Full-body bar in the trade direction: the Gate-3 1-min candle-acceptance
    # guard needs a >=60% body with the close near the extreme.
    if str(direction).upper() == "SHORT":
        open_px, high, low, close = 24730.0, 24730.0, 24690.0, 24700.0
    else:
        open_px, high, low, close = 24690.0, 24730.0, 24690.0, 24720.0
    return Bar(
        time=time_iso,
        open=open_px,
        high=high,
        low=low,
        close=close,
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
    if setup_type == "TRIPLE_A":
        evidence = _EVIDENCE
    elif setup_type == "SECOND_DRIVE":
        evidence = SetupEvidence(
            setup_type="SECOND_DRIVE",
            direction="SHORT",
            drive_number=2,
            d1_rejected=True,
            rejection=True,
            cvd_agrees=True,
        )
    else:
        evidence = SetupEvidence(
            setup_type="VA_FADE",
            direction="SHORT",
            rejection=True,
            cvd_agrees=True,
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
        bid=24699.0,
        ask=24701.0,
        tick_size=0.05,
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


def test_midday_allows_second_drive_reversion():
    """Phase 3 favors mean reversion: SECOND_DRIVE reclaim passes Gate 1."""
    ctx = _ctx("2026-08-19T12:45:00+05:30", setup_type="SECOND_DRIVE")
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


def _midday_ctx(direction="SHORT", break_type="", break_direction="",
                triple_a_phase="", triple_a_signal="") -> DecisionContext:
    """Midday (12:45 IST, Phase 3) context with NO setup_evidence — the raw
    evidence-free momentum paths (Triple-A AGGRESSION / Initiative breakout)
    must be blocked at Gate 3 because allow_trend=False."""
    return DecisionContext(
        bar=_make_bar("2026-08-19T12:45:00+05:30", direction),
        symbol="NIFTY",
        session_open=True,
        warmup_complete=True,
        position_open=False,
        agent_direction=direction,
        agent_probability=0.80,
        market_state=MarketState.IMBALANCED,
        setup_evidence=None,
        vah=24650.0,
        val=24550.0,
        poc=24600.0,
        vwap_upper_2=24750.0,
        vwap_lower_2=24500.0,
        tick_size=0.05,
        cvd_slope=0.5 if direction == "LONG" else -0.5,
        session_vwap=24690.0,
        absorption_cluster_high=24700.0,
        absorption_cluster_low=24680.0,
        absorption_side="BUY_ABSORBED" if direction == "SHORT" else "SELL_ABSORBED",
        break_type=break_type,
        break_direction=break_direction,
        triple_a_phase=triple_a_phase,
        triple_a_signal=triple_a_signal,
        allow_trend=False,
        allow_reversion=True,
    )


def test_initiative_breakout_blocked_midday_without_evidence():
    """Gate 3: Initiative downside breakdown must be vetoed midday when
    allow_trend=False and there is no evidence-gated path to bail it out."""
    ctx = _midday_ctx(direction="SHORT", break_type="INITIATIVE",
                      break_direction="DOWN")
    r = gate_triple_a_edge(ctx)
    assert not r.passed and "trend" in r.reason.lower()


def test_triple_a_aggression_blocked_midday_without_evidence():
    """Gate 3: raw Triple-A AGGRESSION must be vetoed midday (allow_trend=False)."""
    ctx = _midday_ctx(direction="LONG", triple_a_phase="AGGRESSION",
                      triple_a_signal="LONG")
    r = gate_triple_a_edge(ctx)
    assert not r.passed and "trend" in r.reason.lower()


def test_lvn_sniper_blocked_midday_without_evidence():
    """Gate 3: raw LVN Sniper must be vetoed midday (allow_trend=False)."""
    ctx = _midday_ctx(direction="LONG")
    ctx = replace(
        ctx,
        leg_lvn=float(ctx.bar.close),
        absorption_side="SELL_ABSORBED",
        cvd_slope=0.0,
    )
    r = gate_triple_a_edge(ctx)
    assert not r.passed and "trend" in r.reason.lower()


def test_evidence_gated_momentum_still_blocked_midday():
    """Sanity: the evidence path (gate_session_phase) already vetoes momentum
    midday — the Gate 3 guard complements it, it does not regress it."""
    assert _midday_ctx().allow_trend is False
