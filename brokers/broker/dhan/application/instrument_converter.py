"""
Instrument conversion utilities for the Dhan broker.

Split out of ``converters.py`` (WS4): converts between Dhan instrument /
option-chain representations and broker-agnostic entities. All functions
are stateless; ``converters.DhanConverter`` re-exposes them as staticmethods.
"""

from typing import Any, Dict

from shared.entities.models import Instrument, OptionChain
from brokers.broker.types import Exchange, OptionType

from brokers.broker.dhan.domain import (
    DhanInstrument,
    DhanOptionChain,
    ExchangeSegment,
    OptionType as DhanOptionType,
)
from brokers.broker.dhan.domain.segment_mapping import (
    exchange_to_segment_name,
    segment_name_to_exchange,
)


# =============================================================================
# String Mapping Table (module-level, frozen by convention - treat as read-only)
# =============================================================================

# Dhan option type -> broker-agnostic OptionType.
# Unknown values default to OptionType.CALL (previous explicit fallback).
DHAN_OPTION_TYPE_MAP: Dict[DhanOptionType, OptionType] = {
    DhanOptionType.CALL: OptionType.CALL,
    DhanOptionType.PUT: OptionType.PUT,
}


def to_instrument(dhan_instrument: DhanInstrument) -> Instrument:
    """
    Convert DhanInstrument to broker-agnostic Instrument.

    Args:
        dhan_instrument: Dhan-specific instrument entity.

    Returns:
        Broker-agnostic Instrument entity.

    Example:
        >>> instrument = DhanConverter.to_instrument(dhan_inst)
        >>> print(instrument.symbol)  # "NIFTY"
    """
    # Map exchange segment to Exchange enum
    exchange = _segment_to_exchange(dhan_instrument.exchange_segment)

    # Map option type
    option_type = None
    if dhan_instrument.option_type:
        option_type = _map_option_type(dhan_instrument.option_type)

    return Instrument(
        symbol=dhan_instrument.symbol,
        exchange=exchange,
        security_id=dhan_instrument.security_id,
        option_type=option_type,
        strike=dhan_instrument.strike,
        expiry=dhan_instrument.expiry_date,
    )


def from_instrument(instrument: Instrument) -> Dict[str, Any]:
    """
    Convert Instrument to Dhan API lookup parameters.

    Args:
        instrument: Broker-agnostic Instrument entity.

    Returns:
        Dictionary with Dhan lookup parameters.

    Example:
        >>> params = DhanConverter.from_instrument(instrument)
        >>> # Use for API lookup
    """
    return {
        "symbol": instrument.symbol,
        "exchange_segment": _exchange_to_segment(instrument.exchange),
        "security_id": instrument.security_id,
    }


def to_option_chain(
    dhan_chain: DhanOptionChain, exchange: Exchange = Exchange.NFO
) -> OptionChain:
    """
    Convert DhanOptionChain to broker-agnostic OptionChain.

    Args:
        dhan_chain: Dhan-specific option chain entity.
        exchange: Exchange for the underlying.

    Returns:
        Broker-agnostic OptionChain entity.

    Example:
        >>> chain = DhanConverter.to_option_chain(dhan_chain)
        >>> print(chain.underlying.symbol)  # "NIFTY"
    """
    # Create underlying instrument
    underlying = Instrument(
        symbol=dhan_chain.underlying,
        exchange=exchange,
        security_id="",
    )

    # Build calls and puts dictionaries
    calls: Dict[float, Instrument] = {}
    puts: Dict[float, Instrument] = {}

    for strike, (call_opt, put_opt) in dhan_chain.strikes.items():
        # Add call option
        if call_opt and call_opt.instrument:
            calls[strike] = to_instrument(call_opt.instrument)
        elif call_opt:
            calls[strike] = Instrument(
                symbol=f"{dhan_chain.underlying}{strike}CE",
                exchange=exchange,
                security_id="",
                option_type=OptionType.CALL,
                strike=strike,
                expiry=dhan_chain.expiry,
            )

        # Add put option
        if put_opt and put_opt.instrument:
            puts[strike] = to_instrument(put_opt.instrument)
        elif put_opt:
            puts[strike] = Instrument(
                symbol=f"{dhan_chain.underlying}{strike}PE",
                exchange=exchange,
                security_id="",
                option_type=OptionType.PUT,
                strike=strike,
                expiry=dhan_chain.expiry,
            )

    # Calculate ATM strike and step size from the DhanOptionChain
    atm_strike = (
        dhan_chain.atm_strike
        if hasattr(dhan_chain, "atm_strike")
        else (
            min(
                dhan_chain.strikes.keys(),
                key=lambda s: abs(s - dhan_chain.spot_price),
            )
            if dhan_chain.strikes
            else 0.0
        )
    )
    step_size = getattr(dhan_chain, "step_size", 50.0)

    return OptionChain(
        underlying=underlying,
        expiry=dhan_chain.expiry,
        spot_price=dhan_chain.spot_price,
        atm_strike=atm_strike,
        step_size=step_size,
        calls=calls,
        puts=puts,
    )


# =============================================================================
# Private Helpers
# =============================================================================


def _segment_to_exchange(segment: ExchangeSegment) -> Exchange:
    """Convert ExchangeSegment to Exchange enum."""
    segment_name = segment.name if hasattr(segment, "name") else str(segment)
    return segment_name_to_exchange(segment_name)


def _exchange_to_segment(exchange: Exchange) -> str:
    """Convert Exchange enum to Dhan segment string."""
    return exchange_to_segment_name(exchange)


def _map_option_type(dhan_option_type: DhanOptionType) -> OptionType:
    """Map Dhan option type to broker-agnostic OptionType."""
    return DHAN_OPTION_TYPE_MAP.get(dhan_option_type, OptionType.CALL)  # Default: CALL
