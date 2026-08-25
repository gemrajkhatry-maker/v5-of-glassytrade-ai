"""
Dhan Application Converters - Data conversion utilities.

This module is a thin facade over the per-entity converter modules:

- ``instrument_converter``: Instrument / option-chain conversions
- ``quote_converter``: Quote / Tick / depth / market-data conversions
- ``order_converter``: Order entities and place-order payloads
- ``portfolio_converter``: Position conversions

It keeps the historical ``DhanConverter`` API intact by re-exposing every
conversion as a staticmethod, so all existing call sites keep working
unchanged. The mapping tables live next to the conversions that use them;
the exchange-name table stays here alongside ``to_segment``.

Example:
    >>> from brokers.broker.dhan.application import DhanConverter
    >>> from brokers.broker.dhan.domain import DhanQuote
    >>>
    >>> # Convert DhanQuote to broker-agnostic Quote
    >>> quote = DhanConverter.to_quote(dhan_quote)
"""

from typing import Dict, Optional

from brokers.broker.types import Exchange

from brokers.broker.dhan.domain.segment_mapping import (
    exchange_to_segment_name,
)

from brokers.broker.dhan.application import (
    instrument_converter,
    order_converter,
    portfolio_converter,
    quote_converter,
)


# =============================================================================
# String Mapping Tables (module-level, frozen by convention - treat as read-only)
#
# Single source of truth for Dhan API string <-> internal enum conversions.
# Each table preserves the exact default/fallthrough semantics of the
# if/elif chains it replaced; the defaults are documented inline.
# The order-type/order-status/option-type tables live in their per-entity
# modules (order_converter, instrument_converter) and are re-exported below.
# =============================================================================

# User-friendly exchange name -> internal segment code.
# Unknown keys fall through unchanged (see to_segment). Includes both
# user-friendly names and internal codes (identity-mapped).
DHAN_STRING_TO_SEGMENT: Dict[str, str] = {
    "NSE": "NSE_EQ",
    "BSE": "BSE_EQ",
    "NFO": "NSE_FNO",
    "BFO": "BSE_FNO",
    "MCX": "MCX_COMM",
    "INDEX": "IDX_I",
    "CDS": "NSE_CURRENCY",
    # Also support internal codes directly
    "NSE_EQ": "NSE_EQ",
    "BSE_EQ": "BSE_EQ",
    "NSE_FNO": "NSE_FNO",
    "BSE_FNO": "BSE_FNO",
    "MCX_COMM": "MCX_COMM",
    "IDX_I": "IDX_I",
    "NSE_CURRENCY": "NSE_CURRENCY",
}

# Re-exports of the per-entity mapping tables (backward compatibility).
DHAN_ORDER_TYPE_MAP = order_converter.DHAN_ORDER_TYPE_MAP
DHAN_ORDER_STATUS_MAP = order_converter.DHAN_ORDER_STATUS_MAP
ORDER_TYPE_TO_DHAN = order_converter.ORDER_TYPE_TO_DHAN
DHAN_OPTION_TYPE_MAP = instrument_converter.DHAN_OPTION_TYPE_MAP


# =============================================================================
# Helper Functions (for backward compatibility with dhanhq_custom)
# =============================================================================


def to_segment(exchange: Optional[str]) -> Optional[str]:
    """
    Convert user-friendly exchange to internal segment code.

    This function provides backward compatibility with dhanhq_custom.src.exchange.to_segment.

    Args:
        exchange: Exchange enum, string, or None

    Returns:
        Internal segment code (e.g., 'NSE_EQ', 'NSE_FNO') or None

    Example:
        >>> from brokers.broker.dhan.application import to_segment
        >>> to_segment("NSE")
        'NSE_EQ'
        >>> to_segment("NFO")
        'NSE_FNO'
        >>> to_segment("MCX")
        'MCX_COMM'
    """
    if exchange is None:
        return None

    # Handle Exchange enum
    if isinstance(exchange, Exchange):
        return exchange_to_segment_name(exchange)

    # Handle string: direct lookup; unknown names pass through unchanged
    # (preserves the original .get(exchange_upper, exchange_upper) behavior).
    exchange_upper = str(exchange).upper().strip()
    return DHAN_STRING_TO_SEGMENT.get(exchange_upper, exchange_upper)


# =============================================================================
# Dhan Converter (facade over per-entity converter modules)
# =============================================================================


class DhanConverter:
    """
    Convert between Dhan domain entities and broker-agnostic entities.

    This class provides static methods for converting:
    - DhanInstrument -> Instrument
    - DhanQuote -> Quote
    - DhanTick -> Tick
    - DhanOrder -> Order
    - DhanPosition -> Position
    - DhanOptionChain -> OptionChain
    - OrderRequest -> Dhan API order payload

    All methods are stateless and can be called directly on the class.
    Implementations live in the per-entity converter modules and are
    re-exposed here verbatim (same functions, signatures and docstrings).

    Example:
        >>> # Convert a Dhan quote
        >>> quote = DhanConverter.to_quote(dhan_quote)
        >>>
        >>> # Convert an order request
        >>> payload = DhanConverter.from_order_request(order_request)
    """

    # =========================================================================
    # To Broker-Agnostic Entities
    # =========================================================================

    to_instrument = staticmethod(instrument_converter.to_instrument)
    to_quote = staticmethod(quote_converter.to_quote)
    to_tick = staticmethod(quote_converter.to_tick)
    to_order = staticmethod(order_converter.to_order)
    to_position = staticmethod(portfolio_converter.to_position)
    to_option_chain = staticmethod(instrument_converter.to_option_chain)

    # =========================================================================
    # From Broker-Agnostic Entities (for API calls)
    # =========================================================================

    from_order_request = staticmethod(order_converter.from_order_request)
    from_instrument = staticmethod(instrument_converter.from_instrument)

    # =========================================================================
    # From Raw API Responses
    # =========================================================================

    quote_from_api_response = staticmethod(quote_converter.quote_from_api_response)
    tick_from_ws_message = staticmethod(quote_converter.tick_from_ws_message)
    depth_from_api_response = staticmethod(quote_converter.depth_from_api_response)
    order_from_api_response = staticmethod(order_converter.order_from_api_response)
    position_from_api_response = staticmethod(
        portfolio_converter.position_from_api_response
    )

    # =========================================================================
    # Private Helpers (kept reachable via the class for backward compatibility)
    # =========================================================================

    _segment_to_exchange = staticmethod(instrument_converter._segment_to_exchange)
    _exchange_to_segment = staticmethod(instrument_converter._exchange_to_segment)
    _map_option_type = staticmethod(instrument_converter._map_option_type)
    _map_order_type_from_dhan = staticmethod(
        order_converter._map_order_type_from_dhan
    )
    _map_order_status_from_dhan = staticmethod(
        order_converter._map_order_status_from_dhan
    )
