"""Unit tests for LayaDecisionAdvisor — High-Fidelity AMT Parameter Ingestion & MLX Heads."""

import pytest
from unittest.mock import MagicMock, patch
from quant.decision.context import DecisionContext
from quant.decision.laya_advisor import LayaDecisionAdvisor, get_laya_advisor
from quant.bars import Bar


def test_laya_advisor_initialization():
    advisor = LayaDecisionAdvisor(enabled=False)
    assert not advisor.enabled
    res = advisor.evaluate_auction_snapshot("CRUDEOIL OCT FUT", "PRIMARY", "BALANCED", 6200.0, 6200.0, 6220.0, 6180.0, 0.0, "NONE", "D", 0.05)
    assert res["status"] == "disabled"


def test_laya_advisor_from_context_warmup_guard():
    advisor = LayaDecisionAdvisor(enabled=True)
    # Mock initialized agent so it doesn't fail on warmup
    advisor._agent = MagicMock()
    
    ctx = DecisionContext(
        symbol="CRUDEOIL OCT FUT",
        bar_index=5,
        warmup_complete=False,
        bar=Bar(open=6200.0, high=6210.0, low=6190.0, close=6205.0, volume=100.0),
    )
    res = advisor.evaluate_from_context(ctx)
    assert res["status"] == "warmup_pending"
    assert res["action"] == "FLAT"
    assert res["setup"] == "NO_EDGE"


def test_laya_advisor_evaluates_with_all_rich_parameters():
    advisor = LayaDecisionAdvisor(enabled=True)
    mock_agent = MagicMock()
    mock_agent.predict.return_value = {
        "answers": {
            "action": {
                "choice": "BUY (Enter Long)",
                "probabilities": {
                    "BUY (Enter Long)": 0.88,
                    "SELL (Enter Short)": 0.04,
                    "HOLD (Wait / No Edge)": 0.08,
                },
                "confidence": 0.88,
            },
            "setup": {
                "choice": "Triple-A (Absorption + Accumulation Breakout)",
                "probabilities": {
                    "Triple-A (Absorption + Accumulation Breakout)": 0.65,
                    "VA-Fade (Value Area Mean Reversion)": 0.10,
                    "Second-Drive (Failed Probe Return)": 0.05,
                    "LVN-Sniper (Low Volume Node Rejection)": 0.10,
                    "No Edge / Random Chop": 0.10,
                },
            },
            "conviction_score": {
                "score": 3.42,
            },
            "execution_gate": {
                "choice": "PERMITTED (Risk limits cleared)",
                "probabilities": {
                    "PERMITTED (Risk limits cleared)": 0.96,
                    "BLOCKED (Risk halted or cooldown active)": 0.04,
                },
            },
            "trade_permitted": {
                "noul": 0.96,
                "p_true": 0.96,
            },
        }
    }
    advisor._agent = mock_agent

    ctx = DecisionContext(
        symbol="CRUDEOIL OCT FUT",
        market="MCX",
        bar_index=25,
        warmup_complete=True,
        bar=Bar(open=6210.0, high=6250.0, low=6205.0, close=6245.0, volume=2500.0, vwap=6205.0),
        session_phase="US_CORE_SESSION",
        poc=6185.0,
        vah=6210.0,
        val=6150.0,
        session_vwap=6205.0,
        vwap_std=20.0,
        vwap_upper_2=6245.0,
        vwap_lower_2=6165.0,
        cvd_slope=0.52,
        cvd_divergence="",
        norm_delta=1500.0,
        obi=0.42,
        absorption_side="BUY",
        stacked_imbalance_direction="BUY",
        stacked_imbalance_magnitude=4,
        stacked_imbalance_price_low=6235.0,
        stacked_imbalance_price_high=6244.0,
        nearest_buy_print_below=6220.0,
        nearest_sell_print_above=0.0,
        triple_a_phase="AGGRESSION",
        triple_a_signal="BUY",
        break_direction="UP",
        break_type="INITIATIVE",
        leg_lvn=6205.0,
        prior_poc=6185.0,
        npoc_above=6320.0,
        balance_ratio=0.25,
        profile_shape="P",
        squeeze_detected=True,
        squeeze_direction="UP",
        squeeze_trapped_level=6215.0,
        pullback_confirmed=True,
        drive_number=1,
        bid=6244.0,
        ask=6245.0,
        risk_halted=False,
        cooldown_remaining_sec=0,
        consecutive_losses=0,
        consecutive_wins=2,
        setup_grade="A+",
    )

    res = advisor.evaluate_from_context(ctx)

    assert res["status"] == "ok"
    assert res["action"] == "ENTER_LONG"
    assert res["setup"] == "TRIPLE_A"
    assert res["conviction_score"] == 3.42
    assert res["trade_permitted_p"] == 0.96
    assert res["execution_gate"] == "PERMITTED"
    assert "TRIPLE_A" in res["thesis"]
    assert "ENTER_LONG" in res["thesis"]

    # Verify that predict received the rich prompt with all sections
    called_prompt, called_schema = mock_agent.predict.call_args[0]
    assert "[MARKET & CONTRACT]" in called_prompt
    assert "CRUDEOIL OCT FUT" in called_prompt
    assert "MCX" in called_prompt
    assert "[AUCTION MARKET STRUCTURE]" in called_prompt
    assert "ABOVE Value Area High" in called_prompt
    assert "[VOLUME & ORDER FLOW MICROSTRUCTURE]" in called_prompt
    assert "CVD slope +0.52" in called_prompt
    assert "OBI +0.42" in called_prompt
    assert "Stacked Footprint Bubble: 4" in called_prompt
    assert "Nearest institutional buy wall support floor: 6220.00" in called_prompt
    assert "[FABIO AMT SETUP CONFLUENCE]" in called_prompt
    assert "Triple-A Machine: AGGRESSION" in called_prompt
    assert "Naked POC Target Above: 6320.00" in called_prompt
    assert "[RISK & EXECUTION CLEARANCE]" in called_prompt
    assert "Risk Clearance: NORMAL" in called_prompt


def test_laya_advisor_position_management_role():
    advisor = LayaDecisionAdvisor(enabled=True)
    mock_agent = MagicMock()
    mock_agent.predict.return_value = {
        "answers": {
            "management_action": {
                "choice": "HOLD (Trend Intact)",
                "probabilities": {
                    "HOLD (Trend Intact)": 0.92,
                    "TIGHTEN_SL (Move Stop Higher)": 0.04,
                    "TAKE_PROFIT (Target Hit / Scale Out)": 0.02,
                    "EXIT (Thesis Flipped / Adverse Flow)": 0.02,
                },
                "confidence": 0.92,
            },
            "position_verdict": {
                "choice": "RUNNING_WELL (Flow Confirms)",
                "probabilities": {
                    "RUNNING_WELL (Flow Confirms)": 0.85,
                },
            },
            "holding_conviction": {
                "score": 3.65,
            },
            "execution_gate": {
                "choice": "PERMITTED (Risk limits cleared)",
                "probabilities": {
                    "PERMITTED (Risk limits cleared)": 0.98,
                    "BLOCKED (Risk halted or cooldown active)": 0.02,
                },
            },
            "trade_permitted": {
                "noul": 0.98,
            },
        }
    }
    advisor._agent = mock_agent

    ctx = DecisionContext(
        symbol="CRUDEOIL OCT FUT",
        market="MCX",
        bar_index=30,
        warmup_complete=True,
        position_open=True,
        position_side="LONG",
        position_entry_price=6200.0,
        position_sl=6215.0,  # Risk-free
        position_tp=6320.0,
        position_bars_held=5,
        position_unrealized_pnl=45.0,
        bar=Bar(open=6230.0, high=6250.0, low=6225.0, close=6245.0, volume=1800.0, vwap=6210.0),
        session_phase="US_CORE_SESSION",
        poc=6185.0,
        vah=6210.0,
        val=6150.0,
        session_vwap=6210.0,
        vwap_std=20.0,
        cvd_slope=0.48,
        obi=0.35,
    )

    res = advisor.evaluate_from_context(ctx)

    assert res["status"] == "ok"
    assert res["role"] == "POSITION_MANAGEMENT"
    assert res["action"] == "HOLD"
    assert res["setup"] == "POSITION_MGMT"
    assert res["position_verdict"] == "RUNNING_WELL"
    assert res["active_position"]["side"] == "LONG"
    assert res["active_position"]["isRiskFree"] is True
    assert res["conviction_score"] == 3.65
    assert "Position Manager" in res["thesis"]
    assert "HOLD" in res["thesis"]

    # Verify that predict received the POSITION_MANAGEMENT prompt
    called_prompt, called_schema = mock_agent.predict.call_args[0]
    assert "Role: POSITION_MANAGEMENT" in called_prompt
    assert "[ACTIVE POSITION UNDER MANAGEMENT]" in called_prompt
    assert "Position Side: LONG" in called_prompt
    assert "RISK-FREE" in called_prompt
    assert "management_action" in called_schema

