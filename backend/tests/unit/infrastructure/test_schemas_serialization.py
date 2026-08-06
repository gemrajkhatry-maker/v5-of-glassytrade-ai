"""DTO serialization contract tests — AMT/position/portfolio payload trim.

Task 1: AMT Strategy Cleanup — cut dead UI payload. The AMT DTO must drop
the dead fields while keeping the 5 LLM-consumed keys + ``signal`` and every
field the frontend renders.
"""

from __future__ import annotations

from app.domain.trading.models.aggregates import Portfolio
from app.domain.trading.models.entities import Position
from app.domain.trading.models.enums import Side, Source
from app.domain.trading.models.value_objects import AMTResult
from app.infrastructure.serialization.schemas import (
    amt_result_to_dto,
    portfolio_to_dto,
    position_to_dto,
)


def test_amt_dto_drops_dead_fields():
    result = AMTResult(
        market_state="TRENDING_UP",
        poc=100,
        value_area_high=105,
        value_area_low=95,
        aggression=0.6,
    )
    dto = amt_result_to_dto(result, llm_thinking="", llm_json="{}")
    for dead in (
        "devPoc",
        "devVah",
        "devVal",
        "cushionTier",
        "sessionPnl",
        "openingType",
        "mtfAlignment",
        "hourlyVah",
        "hourlyVal",
        "dayType",
        "cvdSource",
        "bimodalActivePole",
        "llmJson",
        "vah",
        "val",
    ):
        assert dead not in dto
    # keep the 5 LLM-consumed DTO keys + signal (trade_journal)
    for keep in (
        "aggression",
        "cvdSlope",
        "ofi",
        "deltaNormalizedOption",
        "marketState",
        "signal",
    ):
        assert keep in dto


def test_amt_dto_drops_telemetry_only_fields():
    result = AMTResult(
        market_state="TRENDING_UP",
        poc=100,
        value_area_high=105,
        value_area_low=95,
        aggression=0.6,
    )
    dto = amt_result_to_dto(result, llm_thinking="", llm_json="{}")
    telemetry = (
        "dayType",
        "liquiditySweep",
        "cushionTier",
        "sessionPnl",
        "bubbleRetests",
        "cvdSource",
        "bimodalActivePole",
        "underlyingPrice",
        "optionType",
        "openingType",
        "hourlyVah",
        "hourlyVal",
        "mtfAlignment",
    )
    for dead in telemetry:
        assert dead not in dto
    # The AMT DTO model must not declare telemetry fields either.
    from app.infrastructure.serialization.schemas import AMTAnalysisDTO

    declared_aliases = {
        field.alias or name for name, field in AMTAnalysisDTO.model_fields.items()
    }
    for dead in telemetry:
        assert dead not in declared_aliases


def test_amt_dto_keeps_frontend_rendered_fields():
    result = AMTResult(
        market_state="BALANCED",
        poc=100,
        value_area_high=105,
        value_area_low=95,
        session_vwap=101.5,
        vwap_upper_2=104.0,
        vwap_lower_2=99.0,
        daily_poc=100,
        hourly_poc=101,
    )
    dto = amt_result_to_dto(result, llm_thinking="", llm_json="{}")
    for keep in (
        "marketState",
        "poc",
        "valueAreaHigh",
        "valueAreaLow",
        "lvns",
        "hvns",
        "aggression",
        "setup",
        "profile",
        "aggressivePrints",
        "cvdSlope",
        "cvdDivergence",
        "profileShape",
        "profileType",
        "sessionVwap",
        "vwapUpper1",
        "vwapLower1",
        "vwapUpper2",
        "vwapLower2",
        "vwapDeviationSigmas",
        "balanceRatio",
        "legProfile",
        "legLvns",
        "legPoc",
        "legVah",
        "legVal",
        "hasDisplacement",
        "ofi",
        "marketStructure",
        "structureConfidence",
        "ibHigh",
        "ibLow",
        "ibComplete",
        "priorPoc",
        "priorVah",
        "priorVal",
        "gapType",
        "openingBias",
        "acceptanceAbove",
        "acceptanceBelow",
        "rejectionAtHigh",
        "rejectionAtLow",
        "priceVelocity",
        "breakDirection",
        "breakType",
        "breakLevel",
        "pocSignal",
        "pocVsPrice",
        "lvnPlay",
        "isSecondDrive",
        "absorptionSide",
        "absorptionRangeRatio",
        "absorptionVolRatio",
        "swingDelta",
        "dailyVah",
        "dailyVal",
        "dailyPoc",
        "hourlyPoc",
        "signal",
    ):
        assert keep in dto
    assert "llmThinking" in dto


def test_position_dto_drops_lot_size():
    p = Position(
        id="p1",
        symbol="S",
        side=Side.LONG,
        source=Source.AMT,
        entry_price=100,
        size=2,
        stop_loss=95,
        take_profit=110,
        entry_time="t",
        metadata={"option_lot_size": 25},
    )
    d = position_to_dto(p)
    assert "lotSize" not in d
    assert d["entryPrice"] == 100


def test_portfolio_dto_drops_history():
    pf = Portfolio.create_default()
    d = portfolio_to_dto(pf)
    assert "history" not in d
    assert d["balance"] > 0
