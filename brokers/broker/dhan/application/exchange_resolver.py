"""
Dhan Exchange Resolver - Auto-detect exchange from symbol name.

This module provides logic to automatically determine the exchange
and segment based on the symbol name, following common conventions.

Enhanced with:
- Strike step sizes for indices and commodities (for option strike selection)
- Derivative detection from symbol name patterns (CALL/PUT/FUT)
- BSE F&O detection (SENSEX, BANKEX)
- MCX commodity auto-detection with step sizes
"""

import re
from dataclasses import dataclass
from typing import Optional

from brokers.broker.types import Exchange
from brokers.broker.dhan.domain import ExchangeSegment


# =============================================================================
# Known Symbol Sets for Auto-Exchange Detection
# =============================================================================

# Index → exchange mapping (determines NSE vs BSE)
INDEX_EXCHANGE_MAP: dict = {
    "NIFTY": "NSE",
    "NIFTY 50": "NSE",
    "BANKNIFTY": "NSE",
    "NIFTY BANK": "NSE",
    "FINNIFTY": "NSE",
    "NIFTY FIN SERVICE": "NSE",
    "MIDCPNIFTY": "NSE",
    "NIFTY MID SELECT": "NSE",
    "SENSEX": "BSE",
    "BANKEX": "BSE",
}

# Strike step sizes for indices
INDEX_STEP_SIZES: dict = {
    "NIFTY": 50,
    "NIFTY 50": 50,
    "BANKNIFTY": 100,
    "NIFTY BANK": 100,
    "FINNIFTY": 50,
    "NIFTY FIN SERVICE": 50,
    "MIDCPNIFTY": 25,
    "NIFTY MID SELECT": 25,
    "SENSEX": 100,
    "BANKEX": 100,
}

# MCX Commodity symbols → step sizes
MCX_COMMODITY_STEP_SIZES: dict = {
    "CRUDEOIL": 50,
    "CRUDEOILM": 50,
    "GOLD": 100,
    "GOLDM": 100,
    "SILVER": 500,
    "SILVERM": 500,
    "NATURALGAS": 5,
    "COPPER": 5,
    "ZINC": 1,
    "LEAD": 1,
    "ALUMINIUM": 5,
    "NICKEL": 50,
    "ALUMINI": 5,
}

# MCX Commodity symbols set (derived from step sizes dict)
MCX_COMMODITY_SYMBOLS: set = set(MCX_COMMODITY_STEP_SIZES.keys())

# NSE F&O Index symbols (derived from INDEX_EXCHANGE_MAP)
NSE_FNO_INDEX_SYMBOLS: set = set(INDEX_EXCHANGE_MAP.keys())

# BSE-specific index symbols
BSE_INDEX_SYMBOLS: set = {"SENSEX", "BANKEX"}

# Popular NSE equity symbols (sample - not exhaustive)
NSE_EQUITY_SYMBOLS: set = {
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "HINDUNILVR",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "AXISBANK", "BAJFINANCE",
    "ASIANPAINT", "MARUTI", "SUNPHARMA", "TITAN", "ULTRACEMCO", "WIPRO",
    "HCLTECH", "NTPC", "POWERGRID", "TATASTEEL", "TATAMOTORS", "ADANIENT",
    "DMART", "PIIND", "DIVISLAB", "DRREDDY", "EICHERMOT", "GRASIM",
    "HEROMOTOCO", "HINDALCO", "INDUSINDBK", "JSWSTEEL", "M&M", "NESTLEIND",
    "ONGC", "SHREECEM", "TECHM", "UPL", "BPCL", "BRITANNIA", "CIPLA",
    "COALINDIA", "DABUR", "GAIL", "IOC", "IRCTC", "ITC", "JINDALSTEL",
    "LUPIN", "MM", "PEL", "RECLTD", "SRF", "TATACONSUM", "VEDL", "ZOMATO",
}


# =============================================================================
# Resolved Exchange
# =============================================================================

@dataclass(frozen=True)
class ResolvedExchange:
    """
    Result of exchange resolution.

    Attributes:
        exchange: The resolved Exchange enum value.
        segment: The Dhan ExchangeSegment.
        symbol_type: Type of symbol ("index", "equity", "commodity", "derivative", etc).
        step_size: Strike step size for option chains (None if not applicable).
    """
    exchange: Exchange
    segment: ExchangeSegment
    symbol_type: str = "equity"
    step_size: Optional[float] = None


# =============================================================================
# Exchange Resolver
# =============================================================================

class DhanExchangeResolver:
    """
    Auto-detect exchange segment from symbol name.

    This class provides logic to automatically determine the exchange
    and segment based on the symbol name, following common conventions.

    Features:
    - Index detection with NSE/BSE classification
    - MCX commodity detection with step sizes
    - Derivative detection from symbol patterns (CALL, PUT, CE, PE, FUT)
    - BSE F&O detection (SENSEX, BANKEX options)
    - Step size lookup for option strike selection

    Example:
        >>> result = DhanExchangeResolver.resolve("NIFTY")
        >>> result.exchange
        Exchange.NFO
        >>> result.symbol_type
        'index'
        >>> result.step_size
        50

        >>> result = DhanExchangeResolver.resolve("CRUDEOIL")
        >>> result.exchange
        Exchange.MCX
        >>> result.step_size
        50
    """

    @classmethod
    def resolve(cls, symbol: str, exchange: Optional[Exchange] = None) -> ResolvedExchange:
        """
        Resolve exchange from symbol name.

        Auto-detects exchange if not provided, using symbol characteristics:
        - Checks if symbol is index (NIFTY, BANKNIFTY, SENSEX, etc.)
        - Checks if symbol is commodity (GOLD, SILVER, CRUDEOIL, etc.)
        - Checks for derivative patterns (CALL/PUT/CE/PE/FUT in name)
        - Defaults to NSE equity

        Args:
            symbol: The symbol to resolve.
            exchange: Optional explicit exchange override.

        Returns:
            ResolvedExchange with exchange, segment, type info, and step size.
        """
        symbol_upper = symbol.upper().strip()

        # If exchange is explicitly provided, resolve with symbol-type awareness
        if exchange is not None:
            return cls._resolve_from_exchange(symbol_upper, exchange)

        # Auto-detect based on symbol
        return cls._auto_detect_exchange(symbol_upper)

    @classmethod
    def _auto_detect_exchange(cls, symbol: str) -> ResolvedExchange:
        """Auto-detect exchange from symbol characteristics."""
        from quant.contracts.instrument_registry import DEFAULT_REGISTRY

        spec = DEFAULT_REGISTRY.try_resolve(symbol)
        if spec is not None:
            seg_map = {
                "NSE_FNO": ExchangeSegment.NSE_FNO,
                "BSE_FNO": ExchangeSegment.BSE_FNO,
                "MCX_COMM": ExchangeSegment.MCX,
                "NSE": ExchangeSegment.NSE_EQ,
            }
            is_fut = cls._is_futures_symbol(symbol)
            is_opt = cls._is_option_symbol(symbol)
            if is_fut:
                stype = "future"
            elif spec.exchange == "MCX":
                stype = "commodity_option" if is_opt else "commodity"
            elif spec.exchange == "BSE":
                stype = "index_option" if is_opt else "index"
            else:
                stype = "index_option" if is_opt else "index"
            return ResolvedExchange(
                exchange=Exchange(spec.dhan_exchange),
                segment=seg_map.get(spec.segment, ExchangeSegment.NSE_FNO),
                symbol_type=stype,
                step_size=spec.strike_interval,
            )

        # Check for index symbols first
        if symbol in INDEX_EXCHANGE_MAP:
            base_exchange = INDEX_EXCHANGE_MAP[symbol]
            ex = Exchange.NFO if base_exchange == "NSE" else Exchange.BFO
            seg = ExchangeSegment.NSE_FNO if base_exchange == "NSE" else ExchangeSegment.BSE_FNO
            return ResolvedExchange(
                exchange=ex,
                segment=seg,
                symbol_type="index",
                step_size=INDEX_STEP_SIZES.get(symbol),
            )

        # Check for MCX commodity symbols
        if symbol in MCX_COMMODITY_SYMBOLS:
            return ResolvedExchange(
                exchange=Exchange.MCX,
                segment=ExchangeSegment.MCX,
                symbol_type="commodity",
                step_size=MCX_COMMODITY_STEP_SIZES.get(symbol),
            )

        # Check for derivative patterns in symbol name
        # e.g. "NIFTY 13 JAN 25750 CALL", "RELIANCE 25 JAN 2500 PUT", "NIFTY JAN FUT"
        if cls._is_option_symbol(symbol) or cls._is_futures_symbol(symbol):
            return cls._resolve_derivative_symbol(symbol)

        # Check for known equity symbols
        if symbol in NSE_EQUITY_SYMBOLS:
            return ResolvedExchange(
                exchange=Exchange.NSE,
                segment=ExchangeSegment.NSE_EQ,
                symbol_type="equity",
            )

        # Default to NSE equity
        return ResolvedExchange(
            exchange=Exchange.NSE,
            segment=ExchangeSegment.NSE_EQ,
            symbol_type="equity",
        )

    @classmethod
    def _resolve_from_exchange(cls, symbol: str, exchange: Exchange) -> ResolvedExchange:
        """
        Resolve segment from explicit exchange.

        Cash-market hints (NSE/BSE/INDEX) on a registered F&O root or a
        derivative contract are YAML session labels, not Dhan segments —
        auto-detect instead of routing NIFTY options to NSE_EQ.
        """
        from brokers.broker.types import Exchange as Ex
        from quant.contracts.instrument_registry import (
            DEFAULT_REGISTRY,
            is_futures_contract,
            is_option_contract,
        )

        cash_hint = exchange in (Ex.NSE, Ex.BSE, Ex.INDEX)
        if cash_hint and (
            is_option_contract(symbol)
            or is_futures_contract(symbol)
            or DEFAULT_REGISTRY.try_resolve(symbol) is not None
        ):
            return cls._auto_detect_exchange(symbol)

        # When explicit exchange is provided, respect it fully for segment mapping.
        # Still detect symbol type by name for the symbol_type + step_size fields.
        exchange_map = {
            Exchange.NSE: (ExchangeSegment.NSE_EQ, "equity"),
            Exchange.NFO: (ExchangeSegment.NSE_FNO, "derivative"),
            Exchange.BSE: (ExchangeSegment.BSE_EQ, "equity"),
            Exchange.BFO: (ExchangeSegment.BSE_FNO, "derivative"),
            Exchange.MCX: (ExchangeSegment.MCX, "commodity"),
            Exchange.INDEX: (ExchangeSegment.IDX_I, "index"),
        }
        segment, symbol_type = exchange_map.get(exchange, (ExchangeSegment.NSE_EQ, "equity"))
        step_size = cls.get_step_size(symbol)
        return ResolvedExchange(
            exchange=exchange, segment=segment, symbol_type=symbol_type, step_size=step_size,
        )

    @classmethod
    def _resolve_derivative_symbol(cls, symbol: str) -> ResolvedExchange:
        """Resolve exchange for a derivative using the canonical root, not substrings."""
        underlying = cls._extract_underlying(symbol)
        if underlying in BSE_INDEX_SYMBOLS:
            return ResolvedExchange(
                exchange=Exchange.BFO,
                segment=ExchangeSegment.BSE_FNO,
                symbol_type="derivative",
                step_size=cls.get_step_size(symbol),
            )
        if underlying in MCX_COMMODITY_SYMBOLS:
            return ResolvedExchange(
                exchange=Exchange.MCX,
                segment=ExchangeSegment.MCX,
                symbol_type="derivative",
                step_size=MCX_COMMODITY_STEP_SIZES.get(underlying),
            )
        return ResolvedExchange(
            exchange=Exchange.NFO,
            segment=ExchangeSegment.NSE_FNO,
            symbol_type="derivative",
            step_size=cls.get_step_size(symbol),
        )

    @classmethod
    def _is_option_symbol(cls, symbol: str) -> bool:
        from quant.contracts.instrument_registry import is_option_contract
        return is_option_contract(symbol)

    @classmethod
    def _is_futures_symbol(cls, symbol: str) -> bool:
        from quant.contracts.instrument_registry import is_futures_contract
        return is_futures_contract(symbol)

    @classmethod
    def _resolve_option_symbol(cls, symbol: str) -> ResolvedExchange:
        """Resolve exchange for compact option symbol."""
        underlying = cls._extract_underlying(symbol)

        # BSE index options
        if underlying in BSE_INDEX_SYMBOLS:
            return ResolvedExchange(
                exchange=Exchange.BFO,
                segment=ExchangeSegment.BSE_FNO,
                symbol_type="index_option",
                step_size=INDEX_STEP_SIZES.get(underlying),
            )

        # MCX commodity options
        if underlying in MCX_COMMODITY_SYMBOLS:
            return ResolvedExchange(
                exchange=Exchange.MCX,
                segment=ExchangeSegment.MCX,
                symbol_type="commodity_option",
                step_size=MCX_COMMODITY_STEP_SIZES.get(underlying),
            )

        # NSE index options
        if underlying in INDEX_EXCHANGE_MAP:
            return ResolvedExchange(
                exchange=Exchange.NFO,
                segment=ExchangeSegment.NSE_FNO,
                symbol_type="index_option",
                step_size=INDEX_STEP_SIZES.get(underlying),
            )

        # NSE stock options
        return ResolvedExchange(
            exchange=Exchange.NFO,
            segment=ExchangeSegment.NSE_FNO,
            symbol_type="stock_option",
        )

    @classmethod
    def _extract_underlying(cls, symbol: str) -> str:
        from quant.contracts.instrument_registry import root_token
        return root_token(symbol)

    @classmethod
    def get_step_size(cls, symbol: str) -> Optional[float]:
        """
        Get strike step size for a symbol.

        Useful for option chain strike selection. Returns the step size
        between consecutive strikes for the given underlying.

        Args:
            symbol: Symbol name (e.g., "NIFTY", "GOLD", "RELIANCE")

        Returns:
            Step size as float, or None if not found.
        """
        symbol = symbol.upper().strip()
        # Extract underlying if it's a derivative symbol
        if cls._is_option_symbol(symbol) or cls._is_futures_symbol(symbol):
            symbol = cls._extract_underlying(symbol)
        # Check for keywords in spaced derivative names
        for kw in (" CALL", " PUT", " CE", " PE", " FUT"):
            if kw in symbol:
                match = re.match(r"^([A-Z&]+)", symbol)
                if match:
                    symbol = match.group(1)
                break
        from quant.contracts.instrument_registry import DEFAULT_REGISTRY
        spec = DEFAULT_REGISTRY.try_resolve(symbol)
        if spec is not None:
            return spec.strike_interval
        return INDEX_STEP_SIZES.get(symbol) or MCX_COMMODITY_STEP_SIZES.get(symbol)

    @classmethod
    def is_index(cls, symbol: str) -> bool:
        """Check if symbol is an index."""
        return symbol.upper().strip() in INDEX_EXCHANGE_MAP

    @classmethod
    def is_commodity(cls, symbol: str) -> bool:
        """Check if symbol is a commodity."""
        return symbol.upper().strip() in MCX_COMMODITY_SYMBOLS

    @classmethod
    def get_exchange_for_index(cls, symbol: str) -> Optional[str]:
        """Get exchange for an index symbol (NSE or BSE)."""
        return INDEX_EXCHANGE_MAP.get(symbol.upper().strip())
