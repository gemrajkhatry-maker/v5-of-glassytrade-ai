"""Round-trip tests for DTO ↔ domain model serialization."""

from __future__ import annotations

import pytest
from app.domain.trading.models.enums import Side, Source, SignalType, SetupType, PositionStatus
from app.domain.trading.models.value_objects import (
    OHLC, OrderBook, OrderBookLevel,
    StrategyStats, FootprintLevel, FootprintCandle,
    AMTResult, VolumeProfileLevel, AggressivePrint,
)
from app.domain.fabio_ai.models.predictions import (
    ModelWeights, FactorBreakdown, AIAnalysisResult,
)
from app.domain.trading.models.entities import Signal, Position
from app.domain.trading.models.aggregates import Portfolio
from app.infrastructure.serialization.schemas import (
    ohlc_to_dto, dto_to_ohlc, OHLCDataDTO,
    portfolio_to_dto, position_to_dto, signal_to_dto,
    amt_result_to_dto, stats_to_dto, footprint_to_dto,
    dto_to_order_book, OrderBookDTO, OrderBookLevelDTO,
    dto_to_weights, ModelWeightsDTO,
)


class TestOHLCRoundTrip:
    def test_domain_to_dto_and_back(self):
        original = OHLC(
            time="2026-01-01T00:00:00Z", open=100, high=105,
            low=95, close=102, volume=1000, vwap=101,
            taker_buy_volume=600, delta=200,
        )
        dto_dict = ohlc_to_dto(original)
        assert dto_dict["takerBuyVolume"] == 600  # camelCase key
        assert dto_dict["time"] == "2026-01-01T00:00:00Z"

        # DTO back to domain
        dto = OHLCDataDTO(**dto_dict)
        restored = dto_to_ohlc(dto)
        assert restored.time == original.time
        assert restored.open == original.open
        assert restored.close == original.close
        assert restored.taker_buy_volume == original.taker_buy_volume

    def test_dto_camelcase_alias(self):
        dto = OHLCDataDTO(
            time="t", open=1, high=2, low=0.5, close=1.5,
            volume=100, vwap=1.3, takerBuyVolume=60, delta=20,
        )
        d = dto.model_dump(by_alias=True)
        assert "takerBuyVolume" in d
        assert d["takerBuyVolume"] == 60


class TestOrderBookRoundTrip:
    def test_none_returns_none(self):
        assert dto_to_order_book(None) is None

    def test_round_trip(self):
        dto = OrderBookDTO(
            bids=[OrderBookLevelDTO(price=99, quantity=1000)],
            asks=[OrderBookLevelDTO(price=101, quantity=500)],
        )
        domain_ob = dto_to_order_book(dto)
        assert len(domain_ob.bids) == 1
        assert domain_ob.bids[0].price == 99
        assert domain_ob.asks[0].quantity == 500


class TestWeightsRoundTrip:
    def test_round_trip(self):
        dto = ModelWeightsDTO(
            trend=0.3, momentum=0.2, delta=0.2,
            orderBook=0.2, volatility=0.1,
        )
        domain_w = dto_to_weights(dto)
        assert domain_w.trend == 0.3
        assert abs(sum([domain_w.trend, domain_w.momentum, domain_w.delta,
                        domain_w.order_book, domain_w.volatility]) - 1.0) < 0.001


class TestPositionSerialization:
    def test_to_dto(self):
        p = Position(
            id="test-id", symbol="BTCUSDT", side=Side.LONG,
            source=Source.AMT, entry_price=50000, size=1.0,
            stop_loss=49000, take_profit=52000, entry_time="t",
        )
        d = position_to_dto(p)
        assert d["id"] == "test-id"
        assert d["side"] == "LONG"
        assert d["source"] == "AMT"
        assert d["entryPrice"] == 50000  # camelCase
        assert d["stopLoss"] == 49000

    def test_closed_position_to_dto(self):
        p = Position(
            id="p1", symbol="S", side=Side.SHORT,
            source=Source.PREDICTION, entry_price=100, size=2,
            stop_loss=110, take_profit=80, entry_time="t",
        )
        p.close(90, "t2", "Take Profit (Full)")
        d = position_to_dto(p)
        assert d["status"] == "CLOSED"
        assert d["exitPrice"] == 90
        assert d["closeReason"] == "Take Profit (Full)"


class TestPortfolioSerialization:
    def test_empty_portfolio(self):
        p = Portfolio.create_default()
        d = portfolio_to_dto(p)
        from app.domain.trading.models.aggregates import INITIAL_CAPITAL
        assert d["balance"] == INITIAL_CAPITAL
        assert d["positions"] == []
        assert d["closedTrades"] == []


class TestSignalSerialization:
    def test_none(self):
        assert signal_to_dto(None) is None

    def test_signal(self):
        s = Signal(
            type=SignalType.BUY, price=100, reason="test",
            stop_loss=95, take_profit=110, timestamp="t",
            setup=SetupType.TREND_MODEL, source=Source.AMT,
        )
        d = signal_to_dto(s)
        assert d["type"] == "BUY"
        assert d["stopLoss"] == 95  # camelCase


class TestAMTResultSerialization:
    def test_basic(self):
        result = AMTResult(
            market_state="TRENDING_UP", poc=100,
            value_area_high=105, value_area_low=95,
            lvns=(97.0,), hvns=(100.0,),
            aggression=0.6,
        )
        d = amt_result_to_dto(result)
        assert d["marketState"] == "TRENDING_UP"
        assert d["poc"] == 100
        assert d["valueAreaHigh"] == 105
        assert d["lvns"] == [97.0]


class TestStatsSerialization:
    def test_basic(self):
        stats = StrategyStats(
            total_trades=10, wins=7, losses=3,
            win_rate=0.7, net_profit=5000,
            avg_profit=500, largest_win=2000, largest_loss=-800,
        )
        d = stats_to_dto(stats)
        assert d["totalTrades"] == 10
        assert d["winRate"] == 0.7
        assert d["netProfit"] == 5000
        assert d["largestLoss"] == -800


class TestFootprintSerialization:
    def test_candle(self):
        fp = FootprintCandle(
            time="t",
            levels=(
                FootprintLevel(price=100, bid=500, ask=700, delta=200, imbalance=True),
            ),
            poc_price=100, total_delta=200, step_price=0.5,
        )
        d = footprint_to_dto(fp)
        assert d["pocPrice"] == 100
        assert d["totalDelta"] == 200
        assert len(d["levels"]) == 1
        assert d["levels"][0]["imbalance"] is True
