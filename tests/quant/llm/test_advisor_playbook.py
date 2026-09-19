"""Fabio AMT Playbook — full advisor narrative validation (11 scenarios)."""

import pytest
from quant.bars import Bar
from quant.contracts.enums import MarketState
from quant.decision.context import DecisionContext
from quant.llm.advisor import LLMAdvisor


def _bar(close=141.0, low=None, high=None, volume=90000, delta=8000):
    return Bar(
        time="2026-08-25T11:00:00+05:30",
        open=close - 2.0,
        high=high if high is not None else close + 3.0,
        low=low if low is not None else close - 4.0,
        close=close, volume=volume, delta=delta,
    )


@pytest.fixture()
def adv():
    a = LLMAdvisor(emit_fn=None)
    yield a
    a.shutdown()


def test_triple_a_aggression_long(adv):
    """A1: State machine A->A->A + cluster close above absorption -> ENTER_LONG TRIPLE_A."""
    ctx = DecisionContext(
        symbol="NIFTY 25 AUG 24200 CALL", bar=_bar(close=141.0),
        market_state=MarketState.BALANCED, poc=130.0, vah=150.0, val=115.0,
        cvd_slope=3.2, absorption_side="BUY",
        triple_a_phase="AGGRESSION", triple_a_signal="LONG", agent_direction="LONG",
        session_phase="PRIMARY_TREND", allow_trend=True,
        vwap_upper_2=160.0, vwap_lower_2=110.0, vwap_std=1.2,
    )
    out = adv._rule_based_narrative(ctx)
    assert out["action"] == "ENTER_LONG"
    assert out["setup"] == "TRIPLE_A"
    assert out["confidence"] == "High"
    assert "AGGRESSION" in out["rationale"]
    assert "NIFTY 25 AUG 24200 CALL" in out["rationale"]


def test_second_drive_reclaim_long(adv):
    """A2: D1 rejected, D2 re-test confirms failed auction -> ENTER_LONG."""
    ctx = DecisionContext(
        symbol="NIFTY 25 AUG 24200 CALL", bar=_bar(close=126.0),
        market_state=MarketState.BALANCED, poc=130.0, vah=150.0, val=115.0,
        cvd_slope=1.8, absorption_side="BUY",
        triple_a_phase="", triple_a_signal="",
        drive_entry_valid=True, drive_number=2, agent_direction="LONG",
        session_phase="PRIMARY_TREND", allow_trend=True,
        vwap_upper_2=160.0, vwap_lower_2=110.0,
    )
    out = adv._rule_based_narrative(ctx)
    assert out["action"] == "ENTER_LONG"
    assert out["setup"] == "SECOND_DRIVE_D2"
    assert "Second Drive" in out["rationale"]
    assert "D1 level rejected" in out["rationale"]


def test_va_fade_long_below_val(adv):
    """A3: Price below VAL, buyer CVD rejecting probe -> ENTER_LONG VA_FADE, target POC."""
    ctx = DecisionContext(
        symbol="NIFTY 25 AUG 24200 PUT", bar=_bar(close=33.5, low=33.0),
        market_state=MarketState.BALANCED, poc=45.0, vah=65.0, val=34.5,
        cvd_slope=2.1, absorption_side="",
        triple_a_phase="", agent_direction="LONG",
        session_phase="PRIMARY_TREND", allow_trend=True, allow_reversion=True,
    )
    out = adv._rule_based_narrative(ctx)
    assert out["action"] == "ENTER_LONG"
    assert out["setup"] == "VA_FADE"
    assert out["confidence"] == "Medium"
    assert "VAL" in out["rationale"]
    assert "POC" in out["rationale"]


def test_anti_climax_block_overextension(adv):
    """A4: Price beyond VWAP +2sigma -> FLAT, climax block message."""
    ctx = DecisionContext(
        symbol="NIFTY 25 AUG 24200 CALL", bar=_bar(close=191.0),
        market_state=MarketState.IMBALANCED, poc=145.0, vah=175.0, val=130.0,
        cvd_slope=8.5, absorption_side="BUY",
        triple_a_phase="AGGRESSION", triple_a_signal="LONG", agent_direction="LONG",
        vwap_upper_2=180.0, vwap_lower_2=120.0, vwap_std=2.3,
    )
    out = adv._rule_based_narrative(ctx)
    assert out["action"] == "FLAT"
    assert "climax" in out["rationale"].lower() or "overextended" in out["rationale"].lower()


def test_contested_bubble_zone_stays_flat(adv):
    """A5: Both BUY+SELL stacked imbalances -> FLAT, contested message."""
    ctx = DecisionContext(
        symbol="BANKNIFTY 25 AUG 57500 CALL", bar=_bar(close=109.5),
        market_state=MarketState.BALANCED, poc=110.0, vah=130.0, val=90.0,
        cvd_slope=-0.3, absorption_side="",
        triple_a_phase="AGGRESSION", triple_a_signal="LONG", agent_direction="LONG",
        contested_bubble_zone=True, session_phase="PRIMARY_TREND",
    )
    out = adv._rule_based_narrative(ctx)
    assert out["action"] == "FLAT"
    assert "contested" in out["rationale"].lower()
    assert "BANKNIFTY 25 AUG 57500 CALL" in out["rationale"]


def test_cvd_conflict_blocks_long(adv):
    """A6: Bearish CVD vs intended LONG -> FLAT, order flow mismatch message."""
    ctx = DecisionContext(
        symbol="NIFTY AUG FUT", bar=_bar(close=24158.0),
        market_state=MarketState.BALANCED, poc=24155.0, vah=24185.0, val=24120.0,
        cvd_slope=-2.8, absorption_side="",
        triple_a_phase="AGGRESSION", triple_a_signal="LONG", agent_direction="LONG",
        session_phase="PRIMARY_TREND",
    )
    out = adv._rule_based_narrative(ctx)
    assert out["action"] == "FLAT"
    assert "order flow" in out["rationale"].lower() or "cvd" in out["rationale"].lower()


def test_initiative_upside_breakout(adv):
    """A7: INITIATIVE break UP above VAH with CVD momentum -> ENTER_LONG BREAKOUT."""
    ctx = DecisionContext(
        symbol="NIFTY AUG FUT", bar=_bar(close=24205.0),
        market_state=MarketState.IMBALANCED, poc=24155.0, vah=24185.0, val=24120.0,
        cvd_slope=4.5, absorption_side="",
        triple_a_phase="", agent_direction="LONG",
        break_direction="UP", break_type="INITIATIVE",
        session_phase="PRIMARY_TREND", allow_trend=True,
        vwap_upper_2=24250.0, vwap_lower_2=24050.0,
    )
    out = adv._rule_based_narrative(ctx)
    assert out["action"] == "ENTER_LONG"
    assert out["setup"] == "BREAKOUT"
    assert out["confidence"] == "High"
    assert "VAH" in out["rationale"]


def test_dead_market_stays_flat(adv):
    """A8: DEAD market state -> FLAT, volume collapsed message."""
    ctx = DecisionContext(
        symbol="FINNIFTY 25 AUG 26150 CALL", bar=_bar(close=50.1, volume=200, delta=10),
        market_state=MarketState.DEAD, poc=50.0, vah=60.0, val=40.0,
        cvd_slope=0.1, absorption_side="",
        triple_a_phase="AGGRESSION", triple_a_signal="LONG", agent_direction="LONG",
        session_phase="PRIMARY_TREND",
    )
    out = adv._rule_based_narrative(ctx)
    assert out["action"] == "FLAT"
    assert out["confidence"] == "Low"
    assert "DEAD" in out["rationale"] or "volume collapsed" in out["rationale"].lower()


def test_va_fade_short_above_vah(adv):
    """A9: Price above VAH, seller CVD rejecting -> ENTER_SHORT VA_FADE."""
    ctx = DecisionContext(
        symbol="NIFTY AUG FUT", bar=_bar(close=24200.0, high=24205.0),
        market_state=MarketState.BALANCED, poc=24155.0, vah=24185.0, val=24120.0,
        cvd_slope=-2.5, absorption_side="",
        triple_a_phase="", agent_direction="SHORT",
        session_phase="PRIMARY_TREND", allow_reversion=True,
    )
    out = adv._rule_based_narrative(ctx)
    assert out["action"] == "ENTER_SHORT"
    assert out["setup"] == "VA_FADE"
    assert "VAH" in out["rationale"]
    assert "POC" in out["rationale"]


def test_opening_noise_always_flat(adv):
    """A10: OPENING_NOISE phase -> FLAT regardless of CVD or absorption."""
    ctx = DecisionContext(
        symbol="NIFTY 25 AUG 24200 CALL", bar=_bar(close=135.0),
        market_state=MarketState.BALANCED, poc=130.0, vah=150.0, val=115.0,
        cvd_slope=9.0, absorption_side="BUY",
        triple_a_phase="AGGRESSION", triple_a_signal="LONG", agent_direction="LONG",
        session_phase="OPENING_NOISE",
    )
    out = adv._rule_based_narrative(ctx)
    assert out["action"] == "FLAT"
    assert out["confidence"] == "Low"
    assert "warmup" in out["rationale"].lower() or "opening" in out["rationale"].lower()


def test_option_symbol_preserved_in_all_narratives(adv):
    """A11: Full option contract name must appear in output, not root_token stripped name."""
    symbol = "BANKNIFTY 25 AUG 57500 CALL"
    ctx = DecisionContext(
        symbol=symbol, bar=_bar(close=109.5),
        market_state=MarketState.BALANCED, poc=110.0, vah=130.0, val=90.0,
        cvd_slope=0.5, absorption_side="", session_phase="PRIMARY_TREND",
    )
    out = adv._rule_based_narrative(ctx)
    assert out["symbol"] == symbol
    assert symbol in out["rationale"] or symbol in out.get("symbol", "")
    assert "BANKNIFTY" in out["rationale"]


# ── Position Management Tests (Fabio Overseer Mode) ──────────────────────────
def test_position_management_hold_healthy_trend(adv):
    """When position is open and order flow confirms, model emits HOLD with position details."""
    ctx = DecisionContext(
        symbol="NIFTY 25 AUG 24200 CALL", bar=_bar(close=145.0),
        market_state=MarketState.IMBALANCED, poc=130.0, vah=150.0, val=115.0,
        cvd_slope=3.5,
        position_open=True,
        position_side="LONG",
        position_entry_price=135.0,
        position_size=50.0,
        position_unrealized_pnl=500.0,
        position_sl=125.0,
        position_tp=160.0,
        position_bars_held=3,
        session_phase="PRIMARY_TREND",
    )
    out = adv._rule_based_narrative(ctx)
    assert out["action"] == "HOLD"
    assert out["direction"] == "LONG"
    assert out["setup"] == "MANAGE_POSITION"
    assert "Holding NIFTY 25 AUG 24200 CALL LONG" in out["rationale"]
    assert "135.0" in out["rationale"]


def test_position_management_take_profit_target(adv):
    """When price reaches TP, model advises TAKE_PROFIT."""
    ctx = DecisionContext(
        symbol="NIFTY 25 AUG 24200 CALL", bar=_bar(close=160.5),
        market_state=MarketState.IMBALANCED, poc=130.0, vah=150.0, val=115.0,
        cvd_slope=2.0,
        position_open=True,
        position_side="LONG",
        position_entry_price=135.0,
        position_size=50.0,
        position_unrealized_pnl=1275.0,
        position_sl=145.0,
        position_tp=160.0,
        position_bars_held=6,
        session_phase="PRIMARY_TREND",
    )
    out = adv._rule_based_narrative(ctx)
    assert out["action"] == "TAKE_PROFIT"
    assert "Target reached" in out["rationale"] or "Take profit" in out["rationale"]


def test_position_management_tighten_sl_on_opposing_flow(adv):
    """When opposing order flow occurs against active trade, model advises TIGHTEN_SL."""
    ctx = DecisionContext(
        symbol="NIFTY 25 AUG 24200 CALL", bar=_bar(close=140.0),
        market_state=MarketState.BALANCED, poc=130.0, vah=150.0, val=115.0,
        cvd_slope=-3.5, absorption_side="SELL_ABSORBED",
        position_open=True,
        position_side="LONG",
        position_entry_price=135.0,
        position_size=50.0,
        position_sl=125.0,
        position_tp=160.0,
        session_phase="PRIMARY_TREND",
    )
    out = adv._rule_based_narrative(ctx)
    assert out["action"] == "TIGHTEN_SL"
    assert "Opposing order flow" in out["rationale"] or "Tighten SL" in out["rationale"]

