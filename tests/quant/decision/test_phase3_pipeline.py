"""Phase 3 pipeline & decision verification tests.

Covers:
1. Market-aware CVD slope conflict guards in gates_edge.py
2. Setup paths (TRIPLE_A, SECOND_DRIVE, LVN_SNIPER, INITIATIVE, SQUEEZE)
3. DecisionContextBuilder market propagation and direction resolution
4. Prior session profile loading and persistence (AMTEngine / QuantEngine)
"""

from unittest.mock import MagicMock
from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.context_builder import DecisionContextBuilder
from quant.decision.gates_edge import gate_triple_a_edge
from quant.decision.setup_state import SetupEvidence
from quant.session_levels import SessionLevelStore
from quant.amt_engine import AMTEngine
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway


def _bar(close=100.0):
    return Bar(
        time="2026-08-28T10:00:00+05:30",
        open=close - 1.2,
        high=close + 0.5,
        low=close - 1.5,
        close=close,
        volume=500.0,
        buy_volume=300.0,
        sell_volume=200.0,
        delta=100.0,
    )


def test_decision_context_builder_propagates_market_and_direction():
    """Verify DecisionContextBuilder propagates market and uses MCX-aware CVD threshold."""
    builder = DecisionContextBuilder()
    amt_dto_mcx = {
        "marketState": "BALANCED",
        "cvdSlope": 0.35,  # 0.35 < MCX threshold 0.5 (looser) → no LONG
        "poc": 100.0,
        "valueAreaHigh": 102.0,
        "valueAreaLow": 98.0,
    }
    risk_state = MagicMock()
    risk_state.halted = False
    risk_state.consecutive_losses = 0
    risk_state.consecutive_wins = 0
    risk_state.equity = 100000.0
    risk_state.risk_per_trade_pct = 0.01

    ctx_mcx = builder.build(
        bar=_bar(100.0),
        symbol="CRUDEOIL 19 SEP 7400 CALL",
        market="MCX",
        contract_expiry=None,
        tick_size=1.0,
        bar_index=20,
        warm_bars=20,
        cooldown_remaining_sec=0.0,
        risk_state=risk_state,
        amt_dto=amt_dto_mcx,
    )
    assert ctx_mcx.market == "MCX"
    # matches Gate-3 veto (gates_edge) + pipeline doc; was inverted:
    # MCX is now the looser market (0.5), so 0.35 does not clear it.
    assert ctx_mcx.agent_direction is None

    # In NSE, cvdSlope 0.35 in BALANCED triggers LONG (NSE tighter: needs > 0.3)
    amt_dto_nse = {
        "marketState": "BALANCED",
        "cvdSlope": 0.35,
        "poc": 100.0,
        "valueAreaHigh": 102.0,
        "valueAreaLow": 98.0,
    }
    ctx_nse = builder.build(
        bar=_bar(100.0),
        symbol="NIFTY 28 AUG 24500 CALL",
        market="NSE",
        contract_expiry=None,
        tick_size=0.05,
        bar_index=20,
        warm_bars=20,
        cooldown_remaining_sec=0.0,
        risk_state=risk_state,
        amt_dto=amt_dto_nse,
    )
    assert ctx_nse.market == "NSE"
    assert ctx_nse.agent_direction == "LONG"


def test_all_setup_paths_pass_gate3():
    """Verify setup paths (TRIPLE_A, SECOND_DRIVE, LVN_SNIPER, INITIATIVE, SQUEEZE) pass Gate 3."""
    # 1. SetupEvidence path (TRIPLE_A) — certificate must be complete
    ev = SetupEvidence(
        setup_type="TRIPLE_A",
        direction="LONG",
        absorption=True,
        accumulation=True,
        aggression=True,
        acceptance=True,
        cvd_agrees=True,
        breakout_beyond_cluster=True,
        lvn_proximity_ok=True,
        price=100.0,
        session_vwap=99.0,
    )
    ctx_ev = DecisionContext(
        bar=_bar(100.0),
        symbol="CRUDEOIL",
        market="MCX",
        agent_direction="LONG",
        setup_evidence=ev,
        cvd_slope=0.2,
    )
    res_ev = gate_triple_a_edge(ctx_ev)
    assert res_ev.passed and "TRIPLE_A confirmed" in res_ev.reason

    # 2. Triple-A AGGRESSION path
    ctx_aaa = DecisionContext(
        bar=_bar(100.0),
        symbol="NIFTY",
        market="NSE",
        agent_direction="LONG",
        triple_a_phase="AGGRESSION",
        triple_a_signal="LONG",
        cvd_slope=0.8,
        vwap_upper_2=105.0,
        session_vwap=99.0,
        absorption_cluster_high=99.5,
        absorption_cluster_low=98.5,
        absorption_side="SELL_ABSORBED",
        leg_lvn=100.0,
    )
    res_aaa = gate_triple_a_edge(ctx_aaa)
    assert res_aaa.passed and "Triple-A AGGRESSION" in res_aaa.reason

    # 3. Second Drive path
    ctx_sd = DecisionContext(
        bar=_bar(100.0),
        symbol="NIFTY",
        market="NSE",
        agent_direction="LONG",
        drive_entry_valid=True,
        cvd_slope=0.4,
    )
    res_sd = gate_triple_a_edge(ctx_sd)
    assert res_sd.passed and "Second Drive reclaim confirmed" in res_sd.reason

    # 4. LVN Sniper path
    ctx_lvn = DecisionContext(
        bar=_bar(100.0),
        symbol="CRUDEOIL",
        market="MCX",
        agent_direction="LONG",
        leg_lvn=100.0,
        tick_size=0.05,
        absorption_side="SELL_ABSORBED",
        cvd_slope=0.1,
    )
    res_lvn = gate_triple_a_edge(ctx_lvn)
    assert res_lvn.passed and "LVN Sniper LONG" in res_lvn.reason

    # 5. Initiative breakout path
    ctx_init = DecisionContext(
        bar=_bar(100.0),
        symbol="NIFTY",
        market="NSE",
        agent_direction="LONG",
        break_type="INITIATIVE",
        break_direction="UP",
        cvd_slope=0.3,
    )
    res_init = gate_triple_a_edge(ctx_init)
    assert res_init.passed and "Initiative upside breakout confirmed" in res_init.reason

    # 6. Squeeze retest path
    ctx_sq = DecisionContext(
        bar=_bar(100.0),
        symbol="NATURALGAS",
        market="MCX",
        agent_direction="LONG",
        squeeze_direction="LONG",
        squeeze_trapped_level=100.0,
        tick_size=0.1,
        cvd_slope=0.2,
    )
    res_sq = gate_triple_a_edge(ctx_sq)
    assert res_sq.passed and "Squeeze LONG retest" in res_sq.reason


def test_amt_engine_and_quant_engine_prior_profile_lifecycle():
    """Verify prior profile can be set, loaded from dated SessionLevelStore,
    and persisted across QuantEngine/AMTEngine."""
    store = SessionLevelStore()
    amt = AMTEngine(
        symbol="CRUDEOIL",
        market="MCX",
        session_levels=store,
    )
    amt.set_prior_profile(poc=7450.0, vah=7500.0, val=7400.0, close=7440.0)
    assert amt._prior["poc"] == 7450.0
    assert amt._prior["vah"] == 7500.0
    assert amt._prior["val"] == 7400.0

    symbol = "CRUDEOIL 19 DEC 7450 CALL"
    store.save_levels(symbol, "2026-09-18", 7450.0, 7500.0, 7400.0, close=7440.0)
    gw = SyntheticGateway([])
    engine = QuantEngine(
        gateway=gw,
        symbol=symbol,
        market="MCX",
        session_levels=store,
    )
    mock_storage = MagicMock()
    engine.attach_storage(mock_storage)
    assert engine._amt_engine._prior["poc"] == 7450.0

    # Test persist_prior_profile still projects to storage for operators
    engine._amt_engine._last_amt_dto = {
        "poc": 7480.0,
        "valueAreaHigh": 7520.0,
        "valueAreaLow": 7440.0,
    }
    engine.persist_prior_profile()
    mock_storage.kv_set.assert_any_call(
        f"prior_profile:{symbol}",
        {"poc": 7480.0, "vah": 7520.0, "val": 7440.0},
    )
    assert any(
        call.args and str(call.args[0]).startswith("kernel_state:")
        for call in mock_storage.kv_set.call_args_list
    )
