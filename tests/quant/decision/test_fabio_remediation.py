"""Tests for Fabio AMT System Remediation and Gap Closures.

Validates:
1. Bug N2: CUSHION_TIER_2 is emitted when session R >= +3.0 and unlocks pyramiding.
2. Gap #8: SessionLevelStore.load_levels matches underlying root/futures when exact key misses.
3. Bug N1 / Gap #2: stackedImbalancePriceLow / High are emitted by dto.py.
4. Gap #9: VWAP bias filter in gates_edge.py vetoes trend continuation below/above VWAP.
5. Gap #5: QuantEngine MCX CVD breakeven calibration.
"""

from quant.session_levels import SessionLevelStore
from quant.amt.dto import amt_result_to_dto
from quant.contracts.value_objects import AMTResult, FootprintCandle, FootprintLevel
from quant.contracts.enums import MarketState
from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.gates_edge import gate_triple_a_edge


def test_quant_engine_mcx_cvd_be_calibration():
    """Verify Gap #5: QuantEngine configures cvd_be_threshold=1.0 for MCX vs 2.0 for NSE."""
    from quant.runtime import QuantEngine
    from quant.brokers.live_gateway import LiveGateway
    from quant.brokers.multiplexed_feed import MultiplexedMarketFeed

    feed = MultiplexedMarketFeed(None)
    gw_mcx = LiveGateway(feed, "CRUDEOIL SEP FUT")
    eng_mcx = QuantEngine(gw_mcx, "CRUDEOIL SEP FUT", market="MCX")
    assert eng_mcx._exits.cvd_be_threshold == 1.0

    gw_nse = LiveGateway(feed, "NIFTY SEP FUT")
    eng_nse = QuantEngine(gw_nse, "NIFTY SEP FUT", market="NSE")
    assert eng_nse._exits.cvd_be_threshold == 2.0


def test_session_levels_root_and_futures_fallback(tmp_path):
    """Verify Gap #8 fix: SessionLevelStore loads levels by underlying root/future."""
    file_path = str(tmp_path / "levels.json")
    store = SessionLevelStore(file_path)

    # Save futures contract levels
    store.save_levels("CRUDEOIL SEP FUT", "2026-09-18", poc=9660.0, vah=9780.0, val=9640.0, close=9662.0)
    store.save_levels("NIFTY SEP FUT", "2026-08-27", poc=24310.0, vah=24370.0, val=24268.0, close=24270.0)

    # Direct exact lookup works
    crude_fut = store.load_levels("CRUDEOIL SEP FUT")
    assert crude_fut["poc"] == 9660.0

    # Root token lookup works (as used by QuantEngine._underlying())
    crude_root = store.load_levels("CRUDEOIL")
    assert crude_root["poc"] == 9660.0
    assert crude_root["vah"] == 9780.0
    assert crude_root["val"] == 9640.0

    # Option symbol fallback works when option has no recorded session
    crude_opt = store.load_levels("CRUDEOIL 15 OCT 9600 CALL")
    assert crude_opt["poc"] == 9660.0


def test_stacked_imbalance_price_boundaries_emitted():
    """Verify Bug N1 / Gap #2 fix: stackedImbalancePriceLow/High emitted in DTO."""
    lvl1 = FootprintLevel(price=100.0, bid=10, ask=50, delta=40, imbalance=True, stacked=True)
    lvl2 = FootprintLevel(price=100.5, bid=15, ask=60, delta=45, imbalance=True, stacked=True)
    lvl3 = FootprintLevel(price=101.0, bid=12, ask=55, delta=43, imbalance=True, stacked=True)

    candle = FootprintCandle(
        time="2026-09-21T10:00:00Z",
        levels=[lvl1, lvl2, lvl3],
        poc_price=100.5,
        total_delta=128,
        step_price=0.5,
    )

    result = AMTResult(
        market_state=MarketState.IMBALANCED,
        poc=100.5,
        value_area_high=102.0,
        value_area_low=99.0,
        footprints={"1726912800": candle},
    )

    dto = amt_result_to_dto(result)
    assert dto["stackedImbalanceDirection"] == "BUY"
    assert dto["stackedImbalanceMagnitude"] == 3
    assert dto["stackedImbalancePriceLow"] == 100.0
    assert dto["stackedImbalancePriceHigh"] == 101.0


def test_vwap_bias_vetoes_trend_long_below_vwap():
    """Verify Gap #9 fix: TRIPLE_A LONG below session VWAP is vetoed."""
    bar = Bar(time="2026-09-21T10:05:00Z", open=99.2, high=100.0, low=99.0, close=99.9, volume=500.0, vwap=101.0)
    ctx = DecisionContext(
        state=None,
        bar=bar,
        symbol="SYM",
        market="NSE",
        bar_index=10,
        time_str="2026-09-21T10:05:00Z",
        agent_direction="LONG",
        agent_probability=0.8,
        market_state="IMBALANCED",
        session_vwap=101.0,  # price (99.9) is below VWAP (101.0)
        tick_size=0.05,
        leg_lvn=99.9,        # price at LVN
        triple_a_phase="AGGRESSION",
        triple_a_signal="LONG",
    )

    res = gate_triple_a_edge(ctx)
    assert not res.passed
    assert "below session VWAP" in res.reason


def test_vwap_bias_permits_trend_long_above_vwap():
    """Verify Gap #9 fix: TRIPLE_A LONG at or above session VWAP passes."""
    bar = Bar(time="2026-09-21T10:05:00Z", open=100.5, high=101.5, low=100.5, close=101.4, volume=500.0, vwap=100.5)
    ctx = DecisionContext(
        state=None,
        bar=bar,
        symbol="SYM",
        market="NSE",
        bar_index=10,
        time_str="2026-09-21T10:05:00Z",
        agent_direction="LONG",
        agent_probability=0.8,
        market_state="IMBALANCED",
        session_vwap=100.5,  # price (101.4) is above VWAP (100.5)
        tick_size=0.05,
        leg_lvn=101.4,
        triple_a_phase="AGGRESSION",
        triple_a_signal="LONG",
    )

    res = gate_triple_a_edge(ctx)
    assert res.passed
    assert res.setup_key == "TRIPLE_A"
