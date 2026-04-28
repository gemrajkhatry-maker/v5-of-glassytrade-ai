"""
Dhan Symbol Mapper - Implementation of ISymbolMapper protocol.

This module provides the symbol mapper implementation for mapping between
trading symbols and Dhan security IDs.

Features:
    - Local caching of instrument data via CSV download
    - Symbol-to-security-id resolution
    - Option instrument lookup
    - Fuzzy search support

Example:
    >>> from brokers.broker.dhan.infrastructure import DhanSymbolMapper
    >>> from brokers.broker.dhan.domain import ExchangeSegment
    >>>
    >>> mapper = DhanSymbolMapper()
    >>> await mapper.refresh_cache()
    >>>
    >>> # Get security ID
    >>> security_id = await mapper.get_security_id(
    ...     "NIFTY23FEB18000CE",
    ...     ExchangeSegment.NSE_FNO
    ... )
"""

import asyncio
import io
from datetime import date, datetime
from pathlib import Path
from typing import Optional, List, Dict

import pandas as pd

from brokers.broker.dhan.ports import (
    ISymbolMapper,
)
from brokers.broker.dhan.domain import (
    ExchangeSegment,
    DhanInstrument,
    InstrumentTypeEnum,
    OptionType,
    DhanSymbolNotFoundError,
    DhanNetworkError,
    INSTRUMENT_CACHE_TTL_SECONDS,
)
from brokers.broker.logging import get_logger
from brokers.broker.utils.symbol import (
    canonicalize_symbol,
    fuzzy_match_score,
)


# =============================================================================
# Logger
# =============================================================================

logger = get_logger("dhan.symbol_mapper")


# =============================================================================
# Dhan Symbol Mapper Implementation
# =============================================================================


class DhanSymbolMapper(ISymbolMapper):
    """
    Symbol mapper implementation for the Dhan API.

    Implements the ISymbolMapper protocol for mapping between human-readable
    trading symbols and Dhan's internal security IDs. Uses local caching
    via CSV download for performance.

    Attributes:
        cache_ttl: Cache time-to-live in seconds.
        cache_dir: Directory for caching instrument CSV files.

    Example:
        >>> mapper = DhanSymbolMapper()
        >>> await mapper.refresh_cache()
        >>>
        >>> # Get security ID for a symbol
        >>> security_id = await mapper.get_security_id(
        ...     "NIFTY23FEB18000CE",
        ...     ExchangeSegment.NSE_FNO
        ... )
        >>> print(security_id)  # "12345"
        >>>
        >>> # Search for instruments
        >>> instruments = await mapper.search_instruments("NIFTY")
        >>> for inst in instruments:
        ...     print(inst.trading_symbol)
    """

    INSTRUMENT_CSV_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"

    def __init__(
        self,
        cache_ttl: int = INSTRUMENT_CACHE_TTL_SECONDS,
        cache_dir: Optional[Path] = None,
    ) -> None:
        """
        Initialize the symbol mapper.

        Args:
            cache_ttl: Cache time-to-live in seconds.
            cache_dir: Custom cache directory for instrument files.
        """
        self._cache_ttl = cache_ttl
        if cache_dir:
            self._cache_dir = Path(cache_dir)
        else:
            self._cache_dir = Path.home() / ".cache" / "dhan_broker" / "instruments"

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._instrument_df: Optional[pd.DataFrame] = None

        # Caches
        self._by_security_id: Dict[str, DhanInstrument] = {}
        self._by_symbol: Dict[str, DhanInstrument] = {}  # key: "symbol:exchange_code"
        self._by_trading_symbol: Dict[str, DhanInstrument] = {}
        self._by_trading_symbol_exchange: Dict[str, DhanInstrument] = {}  # key: "trading_symbol:exchange_code"
        # Case-insensitive indexes for O(1) lookup (avoids linear scans)
        self._by_trading_symbol_lower: Dict[str, DhanInstrument] = {}  # key: "lower(trading_symbol):exchange_code"
        self._by_symbol_lower: Dict[str, DhanInstrument] = {}  # key: "lower(symbol):exchange_code"

        # Cache metadata
        self._last_refresh: Optional[datetime] = None
        # Lock created lazily in the running loop to avoid event-loop binding issues
        self._refresh_lock: Optional[asyncio.Lock] = None

        logger.debug(f"DhanSymbolMapper initialized with cache_ttl={cache_ttl}s")

    @property
    def cache_size(self) -> int:
        """Get the number of instruments in cache."""
        return len(self._by_security_id)

    @property
    def instruments(self) -> Dict[str, DhanInstrument]:
        return self._by_security_id

    @property
    def last_refresh(self) -> Optional[datetime]:
        """Get the last cache refresh time."""
        return self._last_refresh

    @property
    def is_cache_stale(self) -> bool:
        """Check if the cache needs refresh."""
        if self._last_refresh is None:
            return True
        age = (datetime.now() - self._last_refresh).total_seconds()
        return age > self._cache_ttl

    async def get_security_id(
        self, symbol: str, exchange: ExchangeSegment
    ) -> Optional[str]:
        """
        Get Dhan security ID for a trading symbol.

        Resolution order (all steps filter by exchange segment):
          1. Exact trading_symbol:exchange composite key
          2. Exact symbol:exchange key (SM_SYMBOL_NAME based)
          3. Case-insensitive match on trading_symbol within same exchange
          4. Case-insensitive match on symbol name within same exchange
          5. Canonical match (handles spaces/dashes) within same exchange
          6. Fuzzy match within same exchange

        This matches the resolution approach used in dhanhq_custom's SymbolMapper.

        Args:
            symbol: Trading symbol (e.g., "RELIANCE", "NIFTY23FEB18000CE").
            exchange: Exchange segment (NSE_EQ, NSE_FNO, MCX, etc.).

        Returns:
            Security ID if found, None otherwise.
        """
        if self.is_cache_stale:
            await self.refresh_cache()

        exchange_code = exchange.code if exchange else None

        def _matches_exchange(inst: DhanInstrument) -> bool:
            """Check if instrument belongs to the requested exchange segment."""
            if not exchange_code or not inst.exchange_segment:
                return False
            return inst.exchange_segment.code == exchange_code

        # 1. Exact trading_symbol:exchange composite key
        if exchange_code:
            composite = f"{symbol}:{exchange_code}"
            instrument = self._by_trading_symbol_exchange.get(composite)
            if instrument:
                return instrument.security_id

        # 2. Exact symbol:exchange key (SM_SYMBOL_NAME based)
        if exchange_code:
            key = f"{symbol}:{exchange_code}"
            instrument = self._by_symbol.get(key)
            if instrument:
                return instrument.security_id

        # 3. Case-insensitive exact match on trading_symbol (O(1) via index)
        symbol_lower = symbol.lower()
        if exchange_code:
            ts_lower_key = f"{symbol_lower}:{exchange_code}"
            inst = self._by_trading_symbol_lower.get(ts_lower_key)
            if inst:
                return inst.security_id
            # 4. Case-insensitive exact match on symbol name (O(1) via index)
            sym_lower_key = f"{symbol_lower}:{exchange_code}"
            inst = self._by_symbol_lower.get(sym_lower_key)
            if inst:
                return inst.security_id
        else:
            # No exchange specified — scan all exchange codes
            for inst in self._by_trading_symbol_lower.values():
                if inst.trading_symbol.lower() == symbol_lower:
                    return inst.security_id
            for inst in self._by_symbol_lower.values():
                if inst.symbol and inst.symbol.lower() == symbol_lower:
                    return inst.security_id

        # 5. Canonical matching (handle spaces/dashes/underscores)
        canonical_input = canonicalize_symbol(symbol)
        if canonical_input:
            for inst in self._by_security_id.values():
                if not _matches_exchange(inst):
                    continue
                if canonicalize_symbol(inst.trading_symbol) == canonical_input:
                    logger.debug(f"Canonical match: {symbol} → {inst.trading_symbol}")
                    return inst.security_id
            for inst in self._by_security_id.values():
                if not _matches_exchange(inst):
                    continue
                if canonicalize_symbol(inst.symbol) == canonical_input:
                    logger.debug(f"Canonical match: {symbol} → {inst.symbol}")
                    return inst.security_id

        # 6. Fuzzy matching within same exchange
        best_match = None
        best_score = 0.0
        min_fuzzy_score = 0.8

        for inst in self._by_security_id.values():
            if not _matches_exchange(inst):
                continue
            score = fuzzy_match_score(symbol, inst.trading_symbol)
            if score > best_score and score >= min_fuzzy_score:
                best_score = score
                best_match = inst

        if best_match:
            logger.debug(
                f"Fuzzy match: {symbol} → {best_match.trading_symbol} (score: {best_score:.2f})"
            )
            return best_match.security_id

        logger.debug(
            f"Security ID not found for symbol={symbol}, exchange={getattr(exchange, 'name', exchange)}"
        )
        return None

    async def get_instrument(self, security_id: str) -> Optional[DhanInstrument]:
        """
        Get full instrument details by security ID.

        Args:
            security_id: Dhan security ID.

        Returns:
            DhanInstrument if found, None otherwise.
        """
        # Ensure cache is populated
        if self.is_cache_stale:
            await self.refresh_cache()

        return self._by_security_id.get(security_id)

    async def search_instruments(
        self,
        query: str,
        exchange: Optional[ExchangeSegment] = None,
        fuzzy: bool = False,
    ) -> List[DhanInstrument]:
        """
        Search for instruments matching a query.

        Supports partial matching on trading symbol and symbol name.
        Can also use fuzzy matching for approximate matches.

        Args:
            query: Search query (e.g., "NIFTY", "BANK").
            exchange: Optional exchange filter.
            fuzzy: Whether to use fuzzy matching (default: False for exact/partial matching only).

        Returns:
            List of matching instruments.
        """
        # Ensure cache is populated
        if self.is_cache_stale:
            await self.refresh_cache()

        query_lower = query.lower()
        query_canonical = canonicalize_symbol(query)
        results: List[DhanInstrument] = []
        scored_results: List[tuple] = []  # (instrument, score)

        for instrument in self._by_security_id.values():
            # Check exchange filter (guard None exchange_segment)
            if not instrument.exchange_segment:
                continue
            if exchange and instrument.exchange_segment.code != exchange.code:
                continue

            score = 0.0

            # Check exact match on trading symbol
            if instrument.trading_symbol.lower() == query_lower:
                score = 1.0
            # Check exact match on symbol name
            elif instrument.symbol.lower() == query_lower:
                score = 0.95
            # Check partial match in trading symbol
            elif query_lower in instrument.trading_symbol.lower():
                score = 0.8 + (0.1 * len(query_lower) / len(instrument.trading_symbol))
            # Check partial match in symbol name
            elif query_lower in instrument.symbol.lower():
                score = 0.7 + (0.1 * len(query_lower) / len(instrument.symbol))
            # Check canonical match (handles format variations like spaces, dashes)
            elif query_canonical and query_canonical == canonicalize_symbol(
                instrument.trading_symbol
            ):
                score = 0.9
            # Check canonical match on symbol name
            elif query_canonical and query_canonical == canonicalize_symbol(
                instrument.symbol
            ):
                score = 0.85
            # Fuzzy matching (if enabled)
            elif fuzzy:
                fuzzy_score = fuzzy_match_score(query, instrument.trading_symbol)
                if fuzzy_score > 0.6:
                    score = fuzzy_score * 0.7  # Scale down fuzzy matches

            if score > 0:
                scored_results.append((instrument, score))

        # Sort by score descending
        scored_results.sort(key=lambda x: x[1], reverse=True)

        # Return just the instruments
        results = [inst for inst, _ in scored_results]

        logger.debug(f"Search for '{query}' found {len(results)} instruments")
        return results

    async def get_option_instruments(
        self, underlying: str, expiry: date
    ) -> List[DhanInstrument]:
        """
        Get all option instruments for an underlying on a specific expiry.

        Args:
            underlying: Underlying symbol (e.g., "NIFTY", "BANKNIFTY").
            expiry: Expiry date.

        Returns:
            List of option instruments (both CE and PE).
        """
        # Ensure cache is populated
        if self.is_cache_stale:
            await self.refresh_cache()

        underlying_upper = underlying.upper()
        results: List[DhanInstrument] = []

        for instrument in self._by_security_id.values():
            # Check if it's an option
            if not instrument.is_option:
                continue

            # Check underlying match
            if instrument.symbol.upper() != underlying_upper:
                continue

            # Check expiry match
            if instrument.expiry_date and instrument.expiry_date == expiry:
                results.append(instrument)

        logger.debug(f"Found {len(results)} options for {underlying} expiry {expiry}")
        return results

    async def get_nearest_futures_contract(
        self, symbol: str, exchange: ExchangeSegment = ExchangeSegment.MCX
    ) -> Optional[DhanInstrument]:
        """
        Get nearest (earliest expiry) futures contract for a commodity symbol.

        This method is required for resolving MCX commodity symbols (e.g., GOLD, SILVER)
        to their futures contracts, since spot prices are not available via API.

        Args:
            symbol: Commodity symbol (e.g., 'GOLD', 'SILVER', 'CRUDEOIL')
            exchange: Exchange segment (default: MCX)

        Returns:
            DhanInstrument for nearest futures contract, or None if not found

        Raises:
            DhanInvalidExchangeError: If exchange is not MCX
        """
        from brokers.broker.dhan.domain import DhanInvalidExchangeError

        symbol = symbol.upper().strip()

        # Validate exchange
        if exchange != ExchangeSegment.MCX:
            raise DhanInvalidExchangeError(
                f"get_nearest_futures_contract() only supports MCX exchange, got: {exchange.code}"
            )

        # Ensure cache is populated
        if self.is_cache_stale:
            await self.refresh_cache()

        try:
            # Filter MCX FUTCOM contracts matching the symbol
            futures_instruments = []

            for instrument in self._by_security_id.values():
                # Check exchange
                if instrument.exchange_segment != ExchangeSegment.MCX:
                    continue

                # Check instrument type is futures (FUTCOM)
                if instrument.instrument_type != InstrumentTypeEnum.COMMODITY_FUTURE:
                    continue

                # Check symbol match
                if instrument.symbol.upper() != symbol:
                    continue

                futures_instruments.append(instrument)

            if not futures_instruments:
                logger.debug(f"No FUTCOM contracts found for {symbol} on MCX")
                return None

            # Sort by expiry date (ascending) to get nearest expiry
            futures_instruments.sort(key=lambda x: x.expiry_date or date.max)

            # Filter out expired contracts
            today = date.today()
            active = [f for f in futures_instruments if f.expiry_date and f.expiry_date >= today]
            if not active:
                logger.debug(f"All FUTCOM contracts for {symbol} are expired, using nearest")
                active = futures_instruments

            # Return the first (nearest expiry) active futures contract
            nearest = active[0]
            logger.debug(
                f"Resolved {symbol} to nearest futures: {nearest.trading_symbol} "
                f"(expiry: {nearest.expiry_date})"
            )
            return nearest

        except Exception as e:
            logger.debug(f"Failed to resolve {symbol} to nearest futures contract: {e}")
            return None

    async def refresh_cache(self) -> None:
        """
        Refresh the instrument cache.

        Downloads instrument CSV from Dhan's public URL and caches locally.

        Raises:
            DhanNetworkError: If refresh fails.
        """
        if self._refresh_lock is None:
            self._refresh_lock = asyncio.Lock()
        async with self._refresh_lock:
            # Double-check after acquiring lock
            if not self.is_cache_stale and self._by_security_id:
                return

            logger.info("Refreshing instrument cache...")

            try:
                current_date = datetime.now().date()
                cache_file = self._cache_dir / f"api-scrip-master_{current_date}.csv"

                if cache_file.exists():
                    try:
                        df = pd.read_csv(cache_file, low_memory=False)
                        if not df.empty:
                            self._process_instrument_df(df)
                            self._last_refresh = datetime.now()
                            logger.info(
                                f"Instrument cache loaded from cache: {len(self._by_security_id)} instruments"
                            )
                            return
                    except Exception:
                        pass

                import aiohttp

                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        self.INSTRUMENT_CSV_URL, timeout=aiohttp.ClientTimeout(total=60)
                    ) as response:
                        if response.status != 200:
                            raise DhanNetworkError(
                                message=f"Failed to download instruments: HTTP {response.status}",
                            )

                        content = await response.text()
                        df = pd.read_csv(io.StringIO(content), low_memory=False)

                if "SEM_CUSTOM_SYMBOL" in df.columns:
                    df["SEM_CUSTOM_SYMBOL"] = (
                        df["SEM_CUSTOM_SYMBOL"]
                        .astype(str)
                        .str.strip()
                        .str.replace(r"\s+", " ", regex=True)
                    )

                df.to_csv(cache_file, index=False)
                self._cleanup_old_cache_files(current_date)

                self._process_instrument_df(df)

                self._last_refresh = datetime.now()

                logger.info(
                    f"Instrument cache refreshed: {len(self._by_security_id)} instruments"
                )

            except DhanNetworkError:
                raise

            except Exception as e:
                logger.error(f"Failed to refresh instrument cache: {e}")
                raise DhanNetworkError(
                    message=f"Failed to refresh instrument cache: {e}",
                    details={"error": str(e)},
                )

    def _cleanup_old_cache_files(self, current_date: date) -> None:
        """Remove old cache files."""
        current_file = self._cache_dir / f"api-scrip-master_{current_date}.csv"
        for file_path in self._cache_dir.glob("api-scrip-master_*.csv"):
            if file_path != current_file:
                try:
                    file_path.unlink()
                except Exception:
                    pass

    def _get_instrument_type(
        self, exchange_segment: "ExchangeSegment", symbol: str
    ) -> "InstrumentTypeEnum":
        """
        Get instrument type based on exchange segment and symbol.

        Args:
            exchange_segment: The exchange segment.
            symbol: The trading symbol.

        Returns:
            The instrument type.
        """
        from brokers.broker.dhan.domain import InstrumentTypeEnum

        segment_name = exchange_segment.name.lower() if exchange_segment else ""

        if "index" in segment_name:
            return InstrumentTypeEnum.INDEX
        elif "fno" in segment_name or "derivative" in segment_name:
            if symbol.upper() in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"):
                return InstrumentTypeEnum.INDEX_OPTION
            return InstrumentTypeEnum.STOCK_OPTION
        elif "mcx" in segment_name or "commodity" in segment_name:
            return InstrumentTypeEnum.COMMODITY_FUTURE
        else:
            return InstrumentTypeEnum.EQUITY

    def _process_instrument_df(self, df: pd.DataFrame) -> None:
        """
        Process instrument DataFrame and populate caches.

        Args:
            df: DataFrame with instrument data from CSV.
        """
        self._by_security_id.clear()
        self._by_symbol.clear()
        self._by_trading_symbol.clear()
        self._by_trading_symbol_exchange.clear()
        self._by_trading_symbol_lower.clear()
        self._by_symbol_lower.clear()
        
        # Optimization: Filter for relevant segments before processing
        # This drastically reduces records from ~100k to ~15k
        if "SEM_EXM_EXCH_ID" in df.columns:
            valid_exchanges = ["NSE", "NFO", "MCX", "BSE"]
            df = df[df["SEM_EXM_EXCH_ID"].fillna("").str.upper().isin(valid_exchanges)]
            
        self._instrument_df = df

        # Convert to dict records for O(N) performance — significantly faster than iterrows()
        records = df.to_dict('records')
        
        # Cache method lookups
        _parse_instrument_row = self._parse_instrument_row
        _add_to_cache = self._add_to_cache
        
        for row in records:
            instrument = _parse_instrument_row(row)
            if instrument:
                raw_ts = str(row.get("SEM_TRADING_SYMBOL", ""))
                _add_to_cache(instrument, raw_trading_symbol=raw_ts)

    def _add_to_cache(
        self, instrument: DhanInstrument, raw_trading_symbol: str = ""
    ) -> None:
        """
        Add an instrument to all cache indexes.

        Also indexes by raw SEM_TRADING_SYMBOL when it differs from the
        custom symbol (e.g., raw="NIFTY" vs custom="Nifty 50") so both
        lookup forms resolve to the same instrument.

        Args:
            instrument: The instrument to cache.
            raw_trading_symbol: The raw SEM_TRADING_SYMBOL from CSV.
        """
        # By security ID
        self._by_security_id[instrument.security_id] = instrument

        # By trading symbol (may overwrite across exchanges, used only as fallback)
        self._by_trading_symbol[instrument.trading_symbol] = instrument

        # Exchange-aware indexes (skip if exchange_segment missing)
        if instrument.exchange_segment:
            code = instrument.exchange_segment.code
            # By symbol:exchange (SM_SYMBOL_NAME based)
            if instrument.symbol:
                key = f"{instrument.symbol}:{code}"
                self._by_symbol[key] = instrument
                # Case-insensitive symbol index
                self._by_symbol_lower[f"{instrument.symbol.lower()}:{code}"] = instrument
            # By trading_symbol:exchange (composite, no collisions across exchanges)
            ts_key = f"{instrument.trading_symbol}:{code}"
            self._by_trading_symbol_exchange[ts_key] = instrument
            # Case-insensitive trading_symbol index
            self._by_trading_symbol_lower[f"{instrument.trading_symbol.lower()}:{code}"] = instrument
            # Also index by raw SEM_TRADING_SYMBOL if it differs from custom
            if raw_trading_symbol and raw_trading_symbol != instrument.trading_symbol:
                raw_key = f"{raw_trading_symbol}:{code}"
                self._by_trading_symbol_exchange[raw_key] = instrument

    def _get_exchange_segment(
        self, exchange_code: str, instrument_type: str
    ) -> ExchangeSegment:
        """
        Get exchange segment from exchange code and instrument type.

        Args:
            exchange_code: The exchange code from CSV (e.g., "NSE", "BSE", "MCX")
            instrument_type: The instrument type from CSV (e.g., "EQ", "OPTSTK", "FUTSTK")

        Returns:
            The appropriate ExchangeSegment.
        """
        exchange_code = str(exchange_code).upper()
        instrument_type = str(instrument_type).upper()

        # Map based on exchange and instrument type
        # INDEX instruments always go to IDX_I regardless of exchange (matches dhanhq_custom)
        if instrument_type == "INDEX":
            return ExchangeSegment.IDX_I

        if exchange_code == "NSE":
            if instrument_type in ("EQ", "EQUITY"):
                return ExchangeSegment.NSE_EQ
            elif instrument_type in ("OPTSTK", "OPTIDX", "FUTSTK", "FUTIDX"):
                return ExchangeSegment.NSE_FNO
            elif instrument_type in ("FUTCUR", "OPTCUR"):
                return ExchangeSegment.NSE_CURRENCY
            else:
                return ExchangeSegment.NSE_EQ
        elif exchange_code == "BSE":
            if instrument_type in ("EQ", "EQUITY"):
                return ExchangeSegment.BSE_EQ
            elif instrument_type in ("OPTSTK", "OPTIDX", "FUTSTK", "FUTIDX"):
                return ExchangeSegment.BSE_FNO
            else:
                return ExchangeSegment.BSE_EQ
        elif exchange_code == "MCX":
            return ExchangeSegment.MCX

        return ExchangeSegment.NSE_FNO  # Default

    def _parse_instrument_row(self, row: pd.Series) -> Optional[DhanInstrument]:
        """
        Parse instrument data from CSV row.

        Args:
            row: pandas Series with instrument data from CSV.

        Returns:
            Parsed DhanInstrument or None if parsing fails.
        """
        try:
            security_id = str(row.get("SEM_SMST_SECURITY_ID", ""))
            trading_symbol = str(row.get("SEM_TRADING_SYMBOL", ""))
            custom_symbol = str(row.get("SEM_CUSTOM_SYMBOL", trading_symbol))
            # Prefer SEM_SMST_SYMBOL_NAME, fall back to SM_SYMBOL_NAME (MCX uses this)
            sym_val = row.get("SEM_SMST_SYMBOL_NAME")
            if not pd.notna(sym_val) or str(sym_val).strip() in ("", "nan"):
                sym_val = row.get("SM_SYMBOL_NAME", "")
            symbol = str(sym_val) if pd.notna(sym_val) else ""

            if not security_id or not trading_symbol or security_id == "nan":
                return None

            exchange_code = row.get("SEM_EXM_EXCH_ID", "NSE")
            instrument_type_str = str(row.get("SEM_INSTRUMENT_NAME", "EQ"))
            exchange_segment = self._get_exchange_segment(
                exchange_code, instrument_type_str
            )
            instrument_type = self._parse_instrument_type(instrument_type_str)

            expiry_date = None
            expiry_val = row.get("SEM_EXPIRY_DATE")
            if pd.notna(expiry_val) and str(expiry_val) != "nan":
                expiry_date = self._parse_date(str(expiry_val))

            strike = None
            strike_val = row.get("SEM_STRIKE_PRICE")
            if pd.notna(strike_val) and str(strike_val) != "nan":
                try:
                    strike = float(strike_val)
                except (ValueError, TypeError):
                    pass

            option_type_str = str(row.get("SEM_OPTION_TYPE", ""))
            option_type = (
                self._parse_option_type(option_type_str)
                if option_type_str and option_type_str != "nan"
                else None
            )

            lot_size = 1
            lot_val = row.get("SEM_LOT_UNITS")
            if pd.notna(lot_val) and str(lot_val) != "nan":
                try:
                    lot_size = int(float(lot_val))
                except (ValueError, TypeError):
                    pass

            tick_size = 0.05
            tick_val = row.get("SEM_TICK_SIZE")
            if pd.notna(tick_val) and str(tick_val) != "nan":
                try:
                    tick_size = float(tick_val)
                except (ValueError, TypeError):
                    pass

            isin = None
            isin_val = row.get("SEM_SMST_ISIN")
            if pd.notna(isin_val) and str(isin_val) != "nan":
                isin = str(isin_val)

            segment_name = None
            segment_val = row.get("SEM_SEGMENT_NAME")
            if pd.notna(segment_val) and str(segment_val) != "nan":
                segment_name = str(segment_val)

            return DhanInstrument(
                security_id=security_id,
                trading_symbol=custom_symbol
                if custom_symbol != "nan"
                else trading_symbol,
                symbol=symbol if symbol != "nan" else trading_symbol,
                exchange_segment=exchange_segment,
                instrument_type=instrument_type,
                expiry_date=expiry_date,
                strike=strike,
                option_type=option_type,
                lot_size=lot_size,
                tick_size=tick_size,
                isin=isin,
                segment_name=segment_name,
            )

        except Exception as e:
            logger.warning(f"Failed to parse instrument: {e}")
            return None

    def _parse_instrument_type(self, type_str: str) -> InstrumentTypeEnum:
        """
        Parse instrument type from string.

        Args:
            type_str: Instrument type string.

        Returns:
            InstrumentTypeEnum value.
        """
        type_map = {
            "EQ": InstrumentTypeEnum.EQUITY,
            "INDEX": InstrumentTypeEnum.INDEX,
            "FUTIDX": InstrumentTypeEnum.INDEX_FUTURE,
            "FUTSTK": InstrumentTypeEnum.STOCK_FUTURE,
            "OPTIDX": InstrumentTypeEnum.INDEX_OPTION,
            "OPTSTK": InstrumentTypeEnum.STOCK_OPTION,
            "FUTCOM": InstrumentTypeEnum.COMMODITY_FUTURE,
            "OPTFUT": InstrumentTypeEnum.COMMODITY_OPTION,
            "FUTCUR": InstrumentTypeEnum.CURRENCY_FUTURE,
            "OPTCUR": InstrumentTypeEnum.CURRENCY_OPTION,
        }
        return type_map.get(type_str.upper(), InstrumentTypeEnum.EQUITY)

    def _parse_option_type(self, type_str: str) -> Optional[OptionType]:
        """
        Parse option type from string.

        Args:
            type_str: Option type string (CE/PE).

        Returns:
            OptionType or None.
        """
        type_upper = type_str.upper()
        if type_upper == "CE":
            return OptionType.CALL
        elif type_upper == "PE":
            return OptionType.PUT
        return None

    def _parse_date(self, date_str: str) -> Optional[date]:
        """
        Parse date from string with fast-path optimizations for common formats.

        Args:
            date_str: Date string in various formats.

        Returns:
            Parsed date or None.
        """
        if not date_str:
            return None

        date_str = str(date_str).strip()
        if not date_str or date_str == "nan":
            return None

        if " " in date_str and ":" in date_str:
            date_str = date_str.split()[0]

        # Fast-path for YYYY-MM-DD
        if len(date_str) == 10 and date_str[4] == "-" and date_str[7] == "-":
            try:
                return date(int(date_str[0:4]), int(date_str[5:7]), int(date_str[8:10]))
            except ValueError:
                pass
        
        # Fast-path for DD-MM-YYYY
        if len(date_str) == 10 and date_str[2] == "-" and date_str[5] == "-":
            try:
                return date(int(date_str[6:10]), int(date_str[3:5]), int(date_str[0:2]))
            except ValueError:
                pass

        # Fast-path for YYYYMMDD
        if len(date_str) == 8 and date_str.isdigit():
            try:
                return date(int(date_str[0:4]), int(date_str[4:6]), int(date_str[6:8]))
            except ValueError:
                pass

        formats = [
            "%Y-%m-%d",
            "%d-%m-%Y",
            "%Y%m%d",
            "%d%b%Y",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue

        logger.warning(f"Failed to parse date: {date_str}")
        return None

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"DhanSymbolMapper(cache_size={len(self._by_security_id)}, "
            f"last_refresh={self._last_refresh})"
        )
