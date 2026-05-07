"""Shared pytest fixtures for brokersv2 tests."""

import pytest
from decimal import Decimal
from datetime import date

from brokersv2.domain.instrument.models import CanonicalInstrument
from brokersv2.core.types import Exchange, Segment, InstrumentType, OptionType


@pytest.fixture
def equity_instrument():
    """Sample equity instrument."""
    return CanonicalInstrument.create_equity(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        lot_size=1,
        tick_size=Decimal("0.01"),
    )


@pytest.fixture
def option_instrument():
    """Sample option instrument."""
    return CanonicalInstrument.create_option(
        symbol="NIFTY",
        exchange=Exchange.NSE,
        expiry=date(2024, 4, 25),
        strike=Decimal("25000"),
        option_type=OptionType.CALL,
        lot_size=25,
    )


@pytest.fixture
def future_instrument():
    """Sample future instrument."""
    return CanonicalInstrument.create_future(
        symbol="NIFTY",
        exchange=Exchange.NSE,
        expiry=date(2024, 5, 30),
        lot_size=25,
    )