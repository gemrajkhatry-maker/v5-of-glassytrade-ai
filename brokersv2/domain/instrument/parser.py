"""
Symbol parsing for options and futures.

This module provides parsers that convert symbol strings like:
- NIFTY24APR25000CE → CanonicalInstrument
- RELIANCE → CanonicalInstrument
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Tuple

from brokersv2.core.types import (
    Exchange,
    Segment,
    InstrumentType,
    OptionType,
    Symbol,
)
from .models import CanonicalInstrument


# Month mapping for expiry parsing
MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4,
    "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
    "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def parse_option_symbol(symbol: str, exchange: Exchange = Exchange.NSE) -> Optional[CanonicalInstrument]:
    """
    Parse option symbol like NIFTY24APR25000CE.
    
    Format: UNDERLYING[YY][MMM][STRIKE][CE|PE]
    Examples: NIFTY24APR25000CE, BANKNIFTY2460000CE
    
    Returns None if not a valid option symbol.
    """
    symbol = symbol.upper()
    
    # Pattern: UNDERLYING + YY + MMM + STRIKE + CE/PE
    # Strike can be 3-6 digits, possibly with decimals
    pattern = r'^([A-Z]+)(\d{2})([A-Z]{3})(\d+(?:\.\d+)?)(CE|PE)$'
    match = re.match(pattern, symbol)
    
    if not match:
        return None
    
    underlying, year_short, month, strike_str, opt_type = match.groups()
    
    # Parse year (assume 20YY)
    year = 2000 + int(year_short)
    
    # Parse month
    month_num = MONTH_MAP.get(month.upper())
    if not month_num:
        return None
    
    # Parse strike
    strike = Decimal(strike_str)
    
    # Determine the actual expiry date (last Thursday for NSE)
    expiry = _last_thursday_of_month(year, month_num)
    
    # Create canonical instrument
    return CanonicalInstrument.create_option(
        symbol=underlying,
        exchange=exchange,
        expiry=expiry,
        strike=strike,
        option_type=OptionType.CALL if opt_type == "CE" else OptionType.PUT,
    )


def parse_future_symbol(symbol: str, exchange: Exchange = Exchange.NSE) -> Optional[CanonicalInstrument]:
    """
    Parse future symbol like NIFTY24APR.
    
    Format: UNDERLYING[YY][MMM]
    Examples: NIFTY24APR, BANKNIFTY24JUN
    
    Returns None if not a valid future symbol.
    """
    symbol = symbol.upper()
    
    # Pattern: UNDERLYING + YY + MMM (no strike)
    pattern = r'^([A-Z]+)(\d{2})([A-Z]{3})$'
    match = re.match(pattern, symbol)
    
    if not match:
        return None
    
    underlying, year_short, month = match.groups()
    
    # Parse year
    year = 2000 + int(year_short)
    
    # Parse month
    month_num = MONTH_MAP.get(month.upper())
    if not month_num:
        return None
    
    # Determine the actual expiry date
    expiry = _last_thursday_of_month(year, month_num)
    
    return CanonicalInstrument.create_future(
        symbol=underlying,
        exchange=exchange,
        expiry=expiry,
    )


def _last_thursday_of_month(year: int, month: int) -> date:
    """Calculate the last Thursday of a given month."""
    # Start from the last day of the month
    if month == 12:
        next_month = datetime(year + 1, 1, 1)
    else:
        next_month = datetime(year, month + 1, 1)
    
    last_day = date(next_month.year, next_month.month, 1)
    # The day before the 1st of next month is the last day
    import calendar
    last_day = date(year, month, calendar.monthrange(year, month)[1])
    
    # Find the last Thursday
    # weekday(): Monday = 0, Thursday = 3
    days_back = (last_day.weekday() - 3) % 7
    if days_back == 0:
        days_back = 7  # Go back a full week to get the LAST Thursday
    
    from datetime import timedelta
    return last_day - timedelta(days=days_back)


def parse_symbol(symbol: str, exchange: Exchange = Exchange.NSE) -> Optional[CanonicalInstrument]:
    """
    Parse any instrument symbol and return a CanonicalInstrument.
    
    Tries option parsing first, then future, then equity.
    """
    # Try option first
    result = parse_option_symbol(symbol, exchange)
    if result:
        return result
    
    # Try future
    result = parse_future_symbol(symbol, exchange)
    if result:
        return result
    
    # Fall back to equity
    if re.match(r'^[A-Z]{2,20}$', symbol.upper()):
        return CanonicalInstrument.create_equity(
            symbol=symbol.upper(),
            exchange=exchange,
        )
    
    return None