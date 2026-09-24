# tests/quant/decision/test_context_builder_behavior.py
"""Tests for DecisionContextBuilder (Task 3).

Verifies that:
1. Market regime (IMBALANCED) alone does not fabricate setup approval.
2. DTO setup evidence fields map accurately into SetupEvidence.
3. Stale or incomplete evidence leaves setup_evidence incomplete.
"""

import pytest

from quant.decision.context_builder import DecisionContextBuilder
from quant.decision.gates_edge import gate_triple_a_edge
from quant.contracts.enums import MarketState
from quant.contracts.value_objects import AMTResult
from quant.amt.snapshot import analysis_snapshot_from_result
from quant.bars import Bar


class DummyRisk:
    equity = 1_000_000.0
    risk_per_trade_pct = 0.01
    halted = False
    consecutive_losses = 0


def _dummy_bar(close=100.5):
    return Bar(
        time="2026-08-19T10:00:00+05:30",
        open=100.0,
        high=101.0,
        low=99.0,
        close=close,
        volume=1000.0,
        buy_volume=600.0,
        sell_volume=400.0,
        delta=200.0,
    )


def test_build_from_snapshot_does_not_need_camel_dto():
    result = AMTResult(
        market_state="BALANCED",
        poc=100.0,
        value_area_high=102.0,
        value_area_low=98.0,
        session_vwap=100.0,
        cvd_slope=1.5,
        cvd_divergence="NONE",
    )
    snap = analysis_snapshot_from_result(result, "2026-09-22T10:00:00+05:30")
    ctx = DecisionContextBuilder().build(
        bar=_dummy_bar(),
        symbol="NIFTY",
        market="NSE",
        contract_expiry=None,
        tick_size=0.05,
        bar_index=20,
        warm_bars=0,
        cooldown_remaining_sec=0.0,
        risk_state=DummyRisk(),
        snapshot=snap,
        amt_dto={},  # empty dto must not wipe typed fields
    )
    assert ctx.poc == 100.0
    assert ctx.vah == 102.0
    assert ctx.cvd_slope == 1.5


def test_imbalanced_context_has_no_complete_setup_without_sequence():
    builder = DecisionContextBuilder()
    dto = {
        "marketState": "IMBALANCED",
        "ofi": 0.5,
        "valueAreaHigh": 99.0,
        "valueAreaLow": 95.0,
    }
    ctx = builder.build(
        bar=_dummy_bar(),
        symbol="NIFTY",
        market="NSE",
        contract_expiry=None,
        tick_size=0.05,
        bar_index=20,
        warm_bars=0,
        cooldown_remaining_sec=0.0,
        risk_state=DummyRisk(),
        amt_dto=dto,
    )
    assert ctx.market_state == MarketState.IMBALANCED
    assert ctx.setup_evidence is None or not ctx.setup_evidence.is_complete()


def test_va_fade_dto_rejection_maps_to_complete_setup():
    """VA_FADE maps from real rejectionAtHigh/rejectionAtLow DTO keys.

    Regression: acceptance was hardcoded True via ``get("acceptance") or True``,
    so VA_FADE evidence could never complete (needs ``not acceptance``).
    """
    builder = DecisionContextBuilder()
    dto = {
        "marketState": "BALANCED",
        "valueAreaHigh": 101.0,
        "valueAreaLow": 99.0,
        "poc": 100.0,
        "cvdSlope": -1.2,
        "rejectionAtHigh": True,
        "acceptanceAbove": False,
    }
    bar = _dummy_bar()
    # Close back INSIDE the VA after the VAH rejection wick — fade incomplete
    # while price is still ABOVE_VAH.
    bar = Bar(
        time=bar.time, open=bar.open, high=bar.high, low=bar.low,
        close=100.4, volume=bar.volume, buy_volume=bar.buy_volume,
        sell_volume=bar.sell_volume, delta=bar.delta,
    )
    ctx = builder.build(
        bar=bar,
        symbol="NIFTY",
        market="NSE",
        contract_expiry=None,
        tick_size=0.05,
        bar_index=20,
        warm_bars=0,
        cooldown_remaining_sec=0.0,
        risk_state=DummyRisk(),
        amt_dto=dto,
    )
    assert ctx.setup_evidence is not None
    assert ctx.setup_evidence.setup_type == "VA_FADE"
    assert ctx.setup_evidence.acceptance is False
    assert ctx.setup_evidence.rejection is True
    assert ctx.setup_evidence.is_complete() is True


def test_second_drive_dto_maps_to_complete_setup():
    """SECOND_DRIVE maps from real isSecondDrive + driveNumber + departed keys."""
    builder = DecisionContextBuilder()
    dto = {
        "marketState": "IMBALANCED",
        "valueAreaHigh": 99.0,
        "valueAreaLow": 95.0,
        "ofi": 0.5,
        "isSecondDrive": True,
        "driveNumber": 2,
        "departed": True,
        "rejectionAtHigh": True,
        "cvdSlope": 1.5,
    }
    ctx = builder.build(
        bar=_dummy_bar(),
        symbol="NIFTY",
        market="NSE",
        contract_expiry=None,
        tick_size=0.05,
        bar_index=20,
        warm_bars=0,
        cooldown_remaining_sec=0.0,
        risk_state=DummyRisk(),
        amt_dto=dto,
    )
    assert ctx.setup_evidence is not None
    assert ctx.setup_evidence.setup_type == "SECOND_DRIVE"
    assert ctx.setup_evidence.d1_rejected is True
    assert ctx.setup_evidence.is_complete() is True


def test_leg_lvn_derived_from_nearest_leg_lvns():
    """leg_lvn is the LVN nearest current price (no phantom legLvn key)."""
    builder = DecisionContextBuilder()
    dto = {
        "marketState": "IMBALANCED",
        "legLvns": [100.1, 102.0, 98.0],
        "absorptionSide": "SELL_ABSORBED",
        "cvdSlope": 1.5,
    }
    ctx = builder.build(
        bar=_dummy_bar(),  # close = 100.5 -> nearest LVN is 100.1
        symbol="NIFTY",
        market="NSE",
        contract_expiry=None,
        tick_size=0.05,
        bar_index=20,
        warm_bars=0,
        cooldown_remaining_sec=0.0,
        risk_state=DummyRisk(),
        amt_dto=dto,
    )
    assert ctx.leg_lvn == 100.1
    assert ctx.setup_evidence.level == 100.1


def test_context_builder_populates_bid_ask_from_order_book():
    from quant.contracts.value_objects import OrderBook, OrderBookLevel

    ob = OrderBook(bids=(OrderBookLevel(99.9, 10.0),), asks=(OrderBookLevel(100.1, 10.0),))
    ctx = DecisionContextBuilder().build(
        bar=_dummy_bar(close=100.0), symbol="S", market="NSE", contract_expiry=None,
        tick_size=0.05, bar_index=20, warm_bars=15, cooldown_remaining_sec=0,
        risk_state=DummyRisk(), amt_dto={}, order_book=ob,
    )
    assert ctx.bid == 99.9
    assert ctx.ask == 100.1


def test_gate1_rejects_wide_spread():
    from quant.contracts.value_objects import OrderBook, OrderBookLevel
    from quant.decision.gate_session_phase import gate_session_phase

    # Spread must exceed 4% of close (4% of 100.5 = 4.02) to be rejected
    ob = OrderBook(bids=(OrderBookLevel(100.0, 10.0),), asks=(OrderBookLevel(105.0, 10.0),))
    ctx = DecisionContextBuilder().build(
        bar=_dummy_bar(close=100.5), symbol="S", market="NSE", contract_expiry=None,
        tick_size=0.05, bar_index=20, warm_bars=15, cooldown_remaining_sec=0,
        risk_state=DummyRisk(), amt_dto={}, order_book=ob,
    )
    result = gate_session_phase(ctx)
    assert not result.passed
    assert "spread" in result.reason.lower()


def test_orderflow_delta_ratio_is_not_used_as_option_greek_delta():
    ctx = DecisionContextBuilder().build(
        bar=_dummy_bar(close=100.0), symbol="S", market="NSE", contract_expiry=None,
        tick_size=0.05, bar_index=20, warm_bars=15, cooldown_remaining_sec=0,
        risk_state=DummyRisk(), amt_dto={"deltaNormalizedOption": 0.15},
    )
    assert ctx.option_delta is None


def test_aggression_without_acceptance_is_not_triple_a_evidence():
    """Certification defect E3: AGGRESSION phase alone must NOT fabricate
    acceptance=True. Triple-A completeness requires the A/R engine's
    acceptance flag (acceptanceAbove for LONG, acceptanceBelow for SHORT)."""
    builder = DecisionContextBuilder()

    # Long aggression without acceptanceAbove -> no TRIPLE_A evidence.
    ev_long = builder._build_setup_evidence(
        {"tripleAPhase": "AGGRESSION", "tripleASignal": "LONG",
         "cvdSlope": 0.6, "acceptanceAbove": False},
        agent_direction="LONG", nearest_leg_lvn=0.0)
    assert not (ev_long and ev_long.setup_type == "TRIPLE_A" and ev_long.acceptance), \
        "AGGRESSION must not claim acceptance without A/R-engine confirmation"

    # Short aggression without acceptanceBelow -> no TRIPLE_A evidence.
    ev_short = builder._build_setup_evidence(
        {"tripleAPhase": "AGGRESSION", "tripleASignal": "SHORT",
         "cvdSlope": -0.6, "acceptanceBelow": False},
        agent_direction="SHORT", nearest_leg_lvn=0.0)
    assert not (ev_short and ev_short.setup_type == "TRIPLE_A" and ev_short.acceptance), \
        "AGGRESSION must not claim acceptance without A/R-engine confirmation"


def test_aggression_with_real_acceptance_keeps_triple_a():
    """Real acceptance from the A/R engine still completes Triple-A."""
    builder = DecisionContextBuilder()

    ev_long = builder._build_setup_evidence(
        {"tripleAPhase": "AGGRESSION", "tripleASignal": "LONG",
         "cvdSlope": 0.6, "acceptanceAbove": True},
        agent_direction="LONG", nearest_leg_lvn=0.0)
    assert ev_long is not None and ev_long.setup_type == "TRIPLE_A"
    assert ev_long.acceptance and ev_long.aggression

    ev_short = builder._build_setup_evidence(
        {"tripleAPhase": "AGGRESSION", "tripleASignal": "SHORT",
         "cvdSlope": -0.6, "acceptanceBelow": True},
        agent_direction="SHORT", nearest_leg_lvn=0.0)
    assert ev_short is not None and ev_short.setup_type == "TRIPLE_A"
    assert ev_short.acceptance and ev_short.aggression


def test_aggression_acceptance_is_direction_sensitive():
    """acceptanceAbove must NOT satisfy a SHORT Triple-A (and vice versa)."""
    builder = DecisionContextBuilder()

    # acceptanceAbove present but direction is SHORT -> no acceptance.
    ev = builder._build_setup_evidence(
        {"tripleAPhase": "AGGRESSION", "tripleASignal": "SHORT",
         "acceptanceAbove": True, "acceptanceBelow": False},
        agent_direction="SHORT", nearest_leg_lvn=0.0)
    assert not (ev and ev.acceptance), \
        "LONG acceptance flag must not satisfy a SHORT Triple-A"

    # acceptanceBelow present but direction is LONG -> no acceptance.
    ev = builder._build_setup_evidence(
        {"tripleAPhase": "AGGRESSION", "tripleASignal": "LONG",
         "acceptanceAbove": False, "acceptanceBelow": True},
        agent_direction="LONG", nearest_leg_lvn=0.0)
    assert not (ev and ev.acceptance), \
        "SHORT acceptance flag must not satisfy a LONG Triple-A"


def test_options_scalping_suppresses_short_direction():
    """Option contracts must be buy-only (LONG) and never naked shorted."""
    from quant.decision.signal_builder import SignalBuilder
    from quant.decision.decision_service import DecisionService
    builder = DecisionContextBuilder()
    dto = {
        "marketState": "BALANCED",
        "ofi": -0.8,
        "tripleASignal": "SHORT",
        "acceptanceBelow": True,
        "valueAreaHigh": 350.0,
        "valueAreaLow": 300.0,
        "poc": 320.0,
    }
    opt_sym = "CRUDEOIL 17 SEP 8650 PUT"
    ctx = builder.build(
        bar=_dummy_bar(close=360.0),
        symbol=opt_sym,
        market="MCX",
        contract_expiry=None,
        tick_size=0.05,
        bar_index=20,
        warm_bars=50,
        cooldown_remaining_sec=0.0,
        risk_state=DummyRisk(),
        amt_dto=dto,
    )
    # 1. ContextBuilder sets agent_direction to None for options if otherwise SHORT
    assert ctx.agent_direction is None

    # 2. SignalBuilder rejects SHORT if force-tested on options
    sig_builder = SignalBuilder()
    sig, drop_why = sig_builder.build_or_reason(ctx, pipeline_results=[])
    assert sig is None

    # 3. DecisionService never approves SHORT on options
    dec = DecisionService().evaluate(ctx)
    assert not dec.approved or (dec.signal and dec.signal.type == "LONG")


def test_dead_market_state_is_enum_not_string():
    from types import SimpleNamespace
    from quant.contracts.enums import MarketState
    from quant.decision.context_builder import DecisionContextBuilder
    bar = SimpleNamespace(close=100.0, high=101.0, low=99.0,
                          time="2026-09-10T10:00:00+05:30")
    risk = SimpleNamespace(halted=False, consecutive_losses=0,
                           equity=100000.0, risk_per_trade_pct=0.05)
    ctx = DecisionContextBuilder().build(
        bar=bar, symbol="NIFTY", market="NSE", contract_expiry=None,
        tick_size=0.05, bar_index=20, warm_bars=0,
        cooldown_remaining_sec=0.0, risk_state=risk,
        amt_dto={"marketState": "DEAD"})
    assert ctx.market_state == MarketState.DEAD
    # MarketState is a str-Enum so == also matches the raw "DEAD" string;
    # identity pins the type contract (DecisionContext.market_state: MarketState).
    assert ctx.market_state is MarketState.DEAD


def test_initiative_up_with_lagging_negative_cvd_stays_long():
    """INITIATIVE UP + lagging persisted negative CVD must not trap to SHORT
    when the breakout bar's own delta is buying (post-absorption lag)."""
    builder = DecisionContextBuilder()
    dto = {
        "marketState": "IMBALANCED",
        "breakType": "INITIATIVE",
        "breakDirection": "UP",
        "cvdSlope": -6.72,  # persisted slope stuck negative through absorption
        "normDelta": 0.9,   # this bar is aggressive buying
        "valueAreaHigh": 102.0,
        "valueAreaLow": 98.0,
        "sessionVwap": 100.0,
        "vwapUpper1": 101.0,
        "vwapLower1": 99.0,
    }
    direction = builder._resolve_direction(
        dto, close_px=100.6, vah=102.0, val=98.0,
        obi=0.0, ofi=0.0, vwap_upper_1=101.0, vwap_lower_1=99.0,
        market="NSE",
    )
    assert direction == "LONG", (
        "INITIATIVE UP with buying delta must resolve LONG, got "
        f"{direction!r} (lagging CVD must not force SHORT)"
    )


def test_initiative_up_with_fresh_sell_delta_traps_to_short():
    """True exhaustion trap: INITIATIVE UP, CVD opposing, and this bar sells."""
    builder = DecisionContextBuilder()
    dto = {
        "marketState": "IMBALANCED",
        "breakType": "INITIATIVE",
        "breakDirection": "UP",
        "cvdSlope": -6.72,
        "normDelta": -0.8,  # breakout bar itself is selling
        "valueAreaHigh": 102.0,
        "valueAreaLow": 98.0,
        "sessionVwap": 100.0,
    }
    direction = builder._resolve_direction(
        dto, close_px=100.2, vah=102.0, val=98.0,
        obi=0.0, ofi=0.0, vwap_upper_1=101.0, vwap_lower_1=99.0,
        market="NSE",
    )
    assert direction == "SHORT"


def _triple_a_bar(direction: str, close: float | None = None):
    if direction == "SHORT":
        close = 99.2 if close is None else close
        return Bar(
            time="2026-08-19T10:00:00+05:30",
            open=100.0,
            high=100.2,
            low=99.0,
            close=close,
            volume=1000.0,
            buy_volume=400.0,
            sell_volume=600.0,
            delta=-200.0,
        )
    close = 100.8 if close is None else close
    return Bar(
        time="2026-08-19T10:00:00+05:30",
        open=100.0,
        high=101.0,
        low=99.8,
        close=close,
        volume=1000.0,
        buy_volume=600.0,
        sell_volume=400.0,
        delta=200.0,
    )


def _build_triple_a_context(
    direction: str = "LONG",
    *,
    cluster_high: float = 100.5,
    cluster_low: float = 99.5,
    cvd_slope: float = 1.0,
    leg_lvns: list[float] | None = None,
    close: float | None = None,
):
    dto = {
        "marketState": "BALANCED",
        "tripleAPhase": "AGGRESSION",
        "tripleASignal": direction,
        "absorptionSide": "SELL_ABSORBED" if direction == "LONG" else "BUY_ABSORBED",
        "acceptanceAbove": direction == "LONG",
        "acceptanceBelow": direction == "SHORT",
        "cvdSlope": cvd_slope,
        "absorptionClusterHigh": cluster_high,
        "absorptionClusterLow": cluster_low,
        "sessionVwap": 100.0,
        "valueAreaHigh": 101.0,
        "valueAreaLow": 99.0,
    }
    if leg_lvns is not None:
        dto["legLvns"] = leg_lvns
    return DecisionContextBuilder().build(
        bar=_triple_a_bar(direction, close),
        symbol="NIFTY",
        market="NSE",
        contract_expiry=None,
        tick_size=0.05,
        bar_index=20,
        warm_bars=0,
        cooldown_remaining_sec=0.0,
        risk_state=DummyRisk(),
        amt_dto=dto,
    )


def test_builder_accepts_no_lvn_triple_a_and_gate_uses_real_evidence():
    ctx = _build_triple_a_context()
    assert ctx.setup_evidence is not None
    assert ctx.setup_evidence.level == 0.0
    assert ctx.setup_evidence.is_complete() is True
    result = gate_triple_a_edge(ctx)
    assert result.passed is True
    assert result.setup_key == "TRIPLE_A"


@pytest.mark.parametrize(
    ("cluster_high", "cluster_low"),
    [
        (0.0, 0.0),
        (100.5, 0.0),
        (0.0, 99.5),
        (99.0, 100.0),
    ],
)
def test_builder_rejects_missing_or_invalid_long_cluster(cluster_high, cluster_low):
    ctx = _build_triple_a_context(
        cluster_high=cluster_high,
        cluster_low=cluster_low,
        leg_lvns=[100.6],
    )
    assert ctx.setup_evidence is None or ctx.setup_evidence.is_complete() is False
    assert gate_triple_a_edge(ctx).passed is False


@pytest.mark.parametrize(
    ("cluster_high", "cluster_low"),
    [
        (0.0, 0.0),
        (100.5, 0.0),
        (0.0, 99.5),
        (100.0, 99.0),
    ],
)
def test_builder_rejects_missing_or_invalid_short_cluster(cluster_high, cluster_low):
    ctx = _build_triple_a_context(
        "SHORT",
        cluster_high=cluster_high,
        cluster_low=cluster_low,
        leg_lvns=[99.4],
    )
    assert ctx.setup_evidence is None or ctx.setup_evidence.is_complete() is False
    assert gate_triple_a_edge(ctx).passed is False


@pytest.mark.parametrize(
    ("direction", "cvd_slope"),
    [
        ("LONG", -0.1),
        ("LONG", 0.0),
        ("SHORT", 0.1),
        ("SHORT", 0.0),
    ],
)
def test_builder_rejects_non_directional_triple_a_cvd(direction, cvd_slope):
    ctx = _build_triple_a_context(
        direction,
        cvd_slope=cvd_slope,
        leg_lvns=[100.6] if direction == "LONG" else [99.4],
    )
    assert ctx.setup_evidence is None or ctx.setup_evidence.is_complete() is False
    assert gate_triple_a_edge(ctx).passed is False


def test_builder_rejects_close_inside_triple_a_cluster():
    ctx = _build_triple_a_context(leg_lvns=[100.6], close=100.5)
    assert ctx.setup_evidence is None or ctx.setup_evidence.is_complete() is False
    assert gate_triple_a_edge(ctx).passed is False
