"""
MCX Futures Resolution

Provides functionality to resolve commodity symbols to their nearest
futures contracts on MCX (Multi Commodity Exchange).

This is required because MCX commodities trade via futures contracts,
not spot prices. The API requires specific futures contract symbols
for LTP and historical data access.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any

import pandas as pd

from brokers.broker.logging import get_logger
from brokers.broker.types import Exchange

logger = get_logger("mcx_futures")


@dataclass
class FuturesContract:
    """
    Represents a futures contract for a commodity.

    Attributes:
        symbol: Trading symbol (e.g., 'GOLD26FEB25FUT')
        security_id: Dhan security ID
        underlying: Base commodity symbol (e.g., 'GOLD')
        exchange: Exchange segment
        expiry_date: Contract expiry date
        expiry_code: Expiry code
        lot_size: Contract lot size
    """

    symbol: str
    security_id: str
    underlying: str
    exchange: Exchange
    expiry_date: Optional[datetime] = None
    expiry_code: Optional[int] = None
    lot_size: Optional[int] = None

    @property
    def is_expired(self) -> bool:
        """Check if contract has expired."""
        if self.expiry_date is None:
            return False
        return datetime.now() > self.expiry_date

    @property
    def days_to_expiry(self) -> Optional[int]:
        """Get number of days until expiry."""
        if self.expiry_date is None:
            return None
        delta = self.expiry_date - datetime.now()
        return max(0, delta.days)


class MCXFuturesResolver:
    """
    Resolves MCX commodity symbols to their nearest futures contracts.

    MCX commodities (GOLD, SILVER, CRUDEOIL, etc.) trade via futures
    contracts. This class helps find the appropriate contract symbol
    for a given commodity.

    Examples:
        >>> resolver = MCXFuturesResolver()
        >>> contract = resolver.get_nearest_contract("GOLD")
        >>> print(contract.symbol)
        'GOLD26FEB25FUT'
    """

    # Common MCX commodities
    COMMON_COMMODITIES = {
        "GOLD",
        "SILVER",
        "CRUDEOIL",
        "NATURALGAS",
        "COPPER",
        "ZINC",
        "LEAD",
        "NICKEL",
        "ALUMINIUM",
        "CRUDEOILM",
        "NATURALGAS",
        "GOLDM",
        "SILVERM",
    }

    def __init__(self, symbol_mapper=None):
        """
        Initialize resolver.

        Args:
            symbol_mapper: Optional symbol mapper for looking up instruments
        """
        self._symbol_mapper = symbol_mapper
        self._cache: Dict[str, FuturesContract] = {}

    def get_nearest_contract(
        self, commodity: str, instrument_df: Optional[pd.DataFrame] = None
    ) -> Optional[FuturesContract]:
        """
        Get the nearest (earliest expiry) futures contract for a commodity.

        Args:
            commodity: Commodity symbol (e.g., 'GOLD', 'SILVER')
            instrument_df: Optional DataFrame with instrument data from Dhan

        Returns:
            FuturesContract for nearest expiry, or None if not found

        Example:
            >>> contract = resolver.get_nearest_contract("GOLD")
            >>> print(f"Trading {contract.symbol}, expires in {contract.days_to_expiry} days")
        """
        commodity = commodity.upper().strip()

        # Check cache first
        cache_key = f"{commodity}_MCX"
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            # Only return cached if not expired or expires within 2 days
            if cached.days_to_expiry is not None and cached.days_to_expiry > 2:
                logger.debug(f"Using cached futures contract for {commodity}")
                return cached

        # If instrument_df provided, use it to find contract
        if instrument_df is not None and not instrument_df.empty:
            return self._resolve_from_dataframe(commodity, instrument_df)

        # Try to use symbol mapper if available
        if self._symbol_mapper is not None:
            return self._resolve_from_mapper(commodity)

        logger.warning(f"Cannot resolve {commodity}: no data source available")
        return None

    def _resolve_from_dataframe(
        self, commodity: str, df: pd.DataFrame
    ) -> Optional[FuturesContract]:
        """
        Resolve futures contract from instrument DataFrame.

        Args:
            commodity: Commodity symbol
            df: Instrument DataFrame from Dhan master data

        Returns:
            FuturesContract or None
        """
        try:
            # Filter for MCX futures contracts
            # Column names based on Dhan instrument file format
            exchange_col = "SEM_EXM_EXCH_ID"
            instrument_col = "SEM_INSTRUMENT_NAME"
            symbol_col = "SM_SYMBOL_NAME"

            # Check required columns exist
            required_cols = [exchange_col, instrument_col, symbol_col]
            missing_cols = [c for c in required_cols if c not in df.columns]
            if missing_cols:
                logger.warning(f"Missing columns in instrument data: {missing_cols}")
                return None

            # Filter for FUTCOM contracts matching commodity
            mask = (
                (df[exchange_col] == "MCX")
                & (df[instrument_col] == "FUTCOM")
                & (df[symbol_col].astype(str).str.upper() == commodity)
            )

            matches = df[mask].copy()

            if matches.empty:
                logger.debug(f"No FUTCOM contracts found for {commodity}")
                return None

            # Sort by expiry date
            if "SEM_EXPIRY_DATE" in matches.columns:
                matches["SEM_EXPIRY_DATE"] = pd.to_datetime(
                    matches["SEM_EXPIRY_DATE"], errors="coerce"
                )
                matches = matches.sort_values("SEM_EXPIRY_DATE", ascending=True)

            # Get nearest contract
            row = matches.iloc[0]

            # Extract symbol (prefer custom symbol)
            symbol = str(
                row.get("SEM_CUSTOM_SYMBOL", row.get("SEM_TRADING_SYMBOL", ""))
            )
            security_id = str(row.get("SEM_SMST_SECURITY_ID", ""))

            # Parse expiry date
            expiry_date = None
            if "SEM_EXPIRY_DATE" in row and pd.notna(row["SEM_EXPIRY_DATE"]):
                try:
                    expiry_date = pd.to_datetime(row["SEM_EXPIRY_DATE"]).to_pydatetime()
                except (ValueError, TypeError, AttributeError):
                    pass

            # Get lot size
            lot_size = None
            if "SEM_LOT_SIZE" in row:
                try:
                    lot_size = int(row["SEM_LOT_SIZE"])
                except (ValueError, TypeError, AttributeError):
                    pass

            # Get expiry code
            expiry_code = None
            if "SEM_EXPIRY_CODE" in row:
                try:
                    expiry_code = int(row["SEM_EXPIRY_CODE"])
                except (ValueError, TypeError, AttributeError):
                    pass

            contract = FuturesContract(
                symbol=symbol,
                security_id=security_id,
                underlying=commodity,
                exchange=Exchange.MCX,
                expiry_date=expiry_date,
                expiry_code=expiry_code,
                lot_size=lot_size,
            )

            # Cache result
            self._cache[f"{commodity}_MCX"] = contract

            logger.info(
                f"Resolved {commodity} to futures contract: {symbol} "
                f"(expires: {expiry_date.date() if expiry_date else 'unknown'})"
            )

            return contract

        except Exception as e:
            logger.error(f"Error resolving {commodity} futures contract: {e}")
            return None

    def _resolve_from_mapper(self, commodity: str) -> Optional[FuturesContract]:
        """
        Resolve using symbol mapper if available.

        This is a fallback when direct DataFrame access isn't available.
        """
        # This would integrate with the symbol mapper
        # For now, return None to indicate mapper-based resolution not implemented
        logger.debug(f"Mapper-based resolution not available for {commodity}")
        return None

    def get_all_contracts(
        self, commodity: str, instrument_df: pd.DataFrame, limit: int = 5
    ) -> List[FuturesContract]:
        """
        Get all available futures contracts for a commodity, sorted by expiry.

        Args:
            commodity: Commodity symbol
            instrument_df: Instrument DataFrame
            limit: Maximum number of contracts to return

        Returns:
            List of FuturesContract objects
        """
        commodity = commodity.upper().strip()
        contracts = []

        try:
            # Filter for MCX futures contracts
            exchange_col = "SEM_EXM_EXCH_ID"
            instrument_col = "SEM_INSTRUMENT_NAME"
            symbol_col = "SM_SYMBOL_NAME"

            mask = (
                (instrument_df[exchange_col] == "MCX")
                & (instrument_df[instrument_col] == "FUTCOM")
                & (instrument_df[symbol_col].astype(str).str.upper() == commodity)
            )

            matches = instrument_df[mask].copy()

            if matches.empty:
                return contracts

            # Sort by expiry
            if "SEM_EXPIRY_DATE" in matches.columns:
                matches["SEM_EXPIRY_DATE"] = pd.to_datetime(
                    matches["SEM_EXPIRY_DATE"], errors="coerce"
                )
                matches = matches.sort_values("SEM_EXPIRY_DATE", ascending=True)

            # Create contract objects
            for _, row in matches.head(limit).iterrows():
                symbol = str(
                    row.get("SEM_CUSTOM_SYMBOL", row.get("SEM_TRADING_SYMBOL", ""))
                )
                security_id = str(row.get("SEM_SMST_SECURITY_ID", ""))

                expiry_date = None
                if "SEM_EXPIRY_DATE" in row and pd.notna(row["SEM_EXPIRY_DATE"]):
                    try:
                        expiry_date = pd.to_datetime(
                            row["SEM_EXPIRY_DATE"]
                        ).to_pydatetime()
                    except (ValueError, TypeError, AttributeError):
                        pass

                lot_size = None
                if "SEM_LOT_SIZE" in row:
                    try:
                        lot_size = int(row["SEM_LOT_SIZE"])
                    except (ValueError, TypeError, AttributeError):
                        pass

                contract = FuturesContract(
                    symbol=symbol,
                    security_id=security_id,
                    underlying=commodity,
                    exchange=Exchange.MCX,
                    expiry_date=expiry_date,
                    lot_size=lot_size,
                )
                contracts.append(contract)

            return contracts

        except Exception as e:
            logger.error(f"Error getting contracts for {commodity}: {e}")
            return contracts

    def clear_cache(self):
        """Clear the contract cache."""
        self._cache.clear()
        logger.debug("Futures contract cache cleared")

    def is_commodity(self, symbol: str) -> bool:
        """
        Check if a symbol is a known MCX commodity.

        Args:
            symbol: Symbol to check

        Returns:
            True if it's a known commodity
        """
        return symbol.upper().strip() in self.COMMON_COMMODITIES
