"""Unit tests for TimesFM-enhanced OptionScannerService and OptionSelector."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import numpy as np
import pytest

from quant.amt.session.scanner import OptionScannerService
from quant.amt.session.selector import OptionSelector
from quant.decision.timesfm_agents import TimesFMForecast, TimesFMScanningAgent
from quant.decision.context import DecisionContext
from quant.bars import Bar


def _make_mock_option(
    ltp=120.0,
    bid=119.5,
    ask=120.5,
    volume=25000,
    oi=500000,
    delta=0.52,
    gamma=0.0015,
    theta=-12.0,
    iv=16.0,
    symbol="NIFTY 24500 CE",
):
    opt = MagicMock()
    opt.symbol = symbol
    opt.ltp = ltp
    opt.bid = bid
    opt.ask = ask
    opt.volume = volume
    opt.oi = oi
    opt.delta = delta
    opt.gamma = gamma
    opt.theta = theta
    opt.iv = iv
    return opt


def _make_forecast(curr_price=24500.0, target_drift=60.0, direction="LONG"):
    horizon = 32
    if direction == "LONG":
        p50 = np.linspace(curr_price, curr_price + target_drift, horizon)
    else:
        p50 = np.linspace(curr_price, curr_price - target_drift, horizon)
    p10 = p50 - 15.0
    p90 = p50 + 15.0
    return TimesFMForecast(
        horizon=horizon,
        p50_path=p50,
        p10_path=p10,
        p90_path=p90,
        q_spread=30.0,
        mean_forecast=float(p50[-1]),
        pct_change=(p50[-1] - curr_price) / curr_price,
        forecast_steps=[direction] * horizon,
        curr_price=curr_price,
        lat_ms=10.0,
    )


def test_scanner_detect_momentum_with_timesfm():
    scanner = OptionScannerService(MagicMock())
    chain = MagicMock()
    chain.calls = {24500.0: _make_mock_option(volume=1000)}
    chain.puts = {24500.0: _make_mock_option(volume=1000)}

    # Bullish TimesFM forecast
    bullish_fc = _make_forecast(direction="LONG")
    bias, strength, reason = scanner._detect_momentum(chain, 24500.0, 50, timesfm_forecast=bullish_fc)
    assert bias == "BULLISH"
    assert "TimesFM upward drift" in reason

    # Bearish TimesFM forecast
    bearish_fc = _make_forecast(direction="SHORT")
    bias, strength, reason = scanner._detect_momentum(chain, 24500.0, 50, timesfm_forecast=bearish_fc)
    assert bias == "BEARISH"
    assert "TimesFM downward drift" in reason


def test_scanner_score_contract_with_timesfm():
    bullish_fc = _make_forecast(direction="LONG")
    opt = _make_mock_option(ltp=150.0, delta=0.50, gamma=0.001, theta=-10.0)

    # Base score without TimesFM
    base_score, _, _ = OptionScannerService._score_contract(
        strike=24500, atm=24500, interval=50, oi=500000, vol=10000,
        opt=opt, ltp=150.0, bid=149.0, ask=151.0, underlying_upper="NIFTY",
        bias="BULLISH", opt_type="CE", timesfm_forecast=None,
    )

    # Score enriched with TimesFM
    tfm_score, _, _ = OptionScannerService._score_contract(
        strike=24500, atm=24500, interval=50, oi=500000, vol=10000,
        opt=opt, ltp=150.0, bid=149.0, ask=151.0, underlying_upper="NIFTY",
        bias="BULLISH", opt_type="CE", timesfm_forecast=bullish_fc,
    )

    assert tfm_score > base_score


def test_selector_select_strike_with_timesfm():
    selector = OptionSelector()
    bullish_fc = _make_forecast(curr_price=24500.0, target_drift=50.0, direction="LONG")

    chain = MagicMock()
    chain.atm_strike = 24500.0
    chain.expiry = datetime(2026, 3, 20, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    chain.calls = {
        24400.0: _make_mock_option(ltp=200.0, delta=0.65, gamma=0.0008, symbol="NIFTY 24400 CE"),
        24500.0: _make_mock_option(ltp=130.0, delta=0.52, gamma=0.0018, symbol="NIFTY 24500 CE"),
        24600.0: _make_mock_option(ltp=75.0, delta=0.35, gamma=0.0011, symbol="NIFTY 24600 CE"),
    }
    chain.puts = {}

    strike = selector.select_strike_with_timesfm(
        underlying="NIFTY",
        spot_price=24500.0,
        direction="LONG",
        forecast=bullish_fc,
        chain=chain,
    )

    assert strike in (24400, 24500)


def test_scanning_agent_with_chain_recommends_option():
    agent = TimesFMScanningAgent(target_horizon=32)
    forecast = _make_forecast(curr_price=8110.0, target_drift=30.0, direction="LONG")

    chain = MagicMock()
    chain.atm_strike = 8100.0
    chain.expiry = datetime(2026, 3, 20, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    chain.calls = {
        8100.0: _make_mock_option(ltp=120.0, delta=0.50, gamma=0.002, symbol="CRUDEOIL 8100 CE"),
    }
    chain.puts = {}

    bar = Bar("2026-09-08T16:00:00", 8105.0, 8115.0, 8105.0, 8110.0, 2000, 400)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        poc=8150.0,
        vah=8190.0,
        val=8109.0,
        cvd_slope=4.5,
        absorption_side="BUY",
        session_phase="PRIMARY",
        position_open=False,
    )

    res = agent.evaluate(ctx, forecast, chain=chain)
    assert res["action"] == "ENTER_LONG"
    assert res["recommendedOption"] is not None
    assert res["recommendedOption"]["symbol"] == "CRUDEOIL 8100 CE"
    assert res["recommendedOption"]["strike"] == 8100
    assert res["recommendedOption"]["optionType"] == "CE"


def test_scanner_fetch_historical_closes_sync_and_async():
    # Sync mock
    sync_broker = MagicMock()
    mock_candle1 = MagicMock()
    mock_candle1.close = 24510.0
    mock_candle2 = MagicMock()
    mock_candle2.close = 24520.0
    sync_broker.fetch_history.return_value = [mock_candle1, mock_candle2]

    scanner_sync = OptionScannerService(sync_broker)
    closes = scanner_sync._fetch_historical_closes("NIFTY SEP FUT", limit=32)
    assert closes == [24510.0, 24520.0]

    # Async mock
    async_broker = MagicMock()
    async def async_fetch(*args, **kwargs):
        return [mock_candle1, mock_candle2]
    async_broker.fetch_history = async_fetch

    scanner_async = OptionScannerService(async_broker)
    closes_async = scanner_async._fetch_historical_closes("NIFTY SEP FUT", limit=32)
    assert closes_async == [24510.0, 24520.0]


def test_scanner_build_scan_result_with_timesfm_enrichment():
    bullish_fc = _make_forecast(direction="LONG")
    opt = _make_mock_option(ltp=150.0, delta=0.52, gamma=0.0018, theta=-8.0)
    opt.symbol = "NIFTY 24500 CE"

    chain = MagicMock()
    chain.calls = {24500.0: opt}
    chain.puts = {}
    chain.atm_strike = 24500.0
    chain.expiry = datetime(2026, 3, 20, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    scanner = OptionScannerService(MagicMock())
    res = scanner._process_contract(
        u="NIFTY",
        opt_type="CE",
        strike=24500,
        atm=24500,
        interval=50,
        option_map=chain.calls,
        bullish_only=False,
        bias="BULLISH",
        bias_reason="TimesFM drift",
        chain=chain,
        is_mcx=False,
        median_vol=5000,
        big_move_mode=False,
        timesfm_forecast=bullish_fc,
    )

    assert res is not None
    assert res.symbol == "NIFTY 24500 CE"
    assert res.score > 0
    assert res.expected_roc > 0
    assert res.timesfm_edge > 0
    assert res.theta_viable is True


def test_scanning_agent_model_momentum_inside_value_area():
    """Verify that pure TimesFM directional forecast triggers MODEL_MOMENTUM setup inside VA."""
    agent = TimesFMScanningAgent(target_horizon=32)
    # Strong upward forecast: 8150 -> 8200 (+0.61% move)
    forecast = _make_forecast(curr_price=8150.0, target_drift=50.0, direction="LONG")

    # Bar right at POC (8150), far from VAL (8100) or VAH (8200) -> would be NO_EDGE in static logic
    bar = Bar("2026-09-08T16:00:00", 8148.0, 8152.0, 8147.0, 8150.0, 2500, 500)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        poc=8150.0,
        vah=8200.0,
        val=8100.0,
        cvd_slope=0.8,
        absorption_side=None,  # No absorption
        stacked_imbalance_direction=None,  # No stacked imbalance
        session_phase="PRIMARY",
        position_open=False,
    )

    res = agent.evaluate(ctx, forecast)
    assert res["action"] == "ENTER_LONG"
    assert res["setup"] == "MODEL_MOMENTUM"
    assert res["direction"] == "LONG"
    assert res["confidence"] == "High"
    assert all(g["passed"] for g in res["gateResults"])


def test_timesfm_strategy_model_momentum_entry():
    """Verify TimesFMTradingStrategy generates Signal for MODEL_MOMENTUM."""
    from quant.strategies.timesfm_strategy import TimesFMTradingStrategy

    strat = TimesFMTradingStrategy(target_horizon=32)
    forecast = _make_forecast(curr_price=8150.0, target_drift=50.0, direction="LONG")

    bar = Bar("2026-09-08T16:00:00", 8148.0, 8152.0, 8147.0, 8150.0, 2500, 500)
    ctx = DecisionContext(
        symbol="CRUDEOIL",
        bar=bar,
        poc=8150.0,
        vah=8200.0,
        val=8100.0,
        cvd_slope=0.8,
        session_phase="PRIMARY",
        position_open=False,
    )

    dec = strat.should_enter(ctx, forecast=forecast)
    assert dec.approved is True
    assert dec.signal is not None
    assert dec.signal.type == "LONG"
    assert dec.signal.reason == "MODEL_MOMENTUM"
    assert dec.signal.sl < 8150.0
    assert dec.signal.tp > 8150.0
