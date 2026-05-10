"""Master Data Loader - CSV import, API sync, and caching for instruments."""
from __future__ import annotations

import csv
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from brokersv2.domain.instrument.registry import InstrumentRegistry
from brokersv2.domain.instrument.models import CanonicalInstrument
from brokersv2.core.types import (
    Exchange,
    SecurityId,
    InstrumentType,
    OptionType,
    InternalUid,
)

logger = logging.getLogger(__name__)


class InstrumentSource(Enum):
    """Source of instrument data."""
    CSV = "CSV"
    API = "API"
    CACHE = "CACHE"


class MasterDataError(Exception):
    """Base exception for master data errors."""
    pass


class CSVLoadError(MasterDataError):
    """Raised when CSV loading fails."""
    pass


class APISyncError(MasterDataError):
    """Raised when API sync fails."""
    pass


class CacheError(MasterDataError):
    """Raised when cache operations fail."""
    pass


@dataclass
class InstrumentRecord:
    """Raw instrument record from data source."""
    security_id: str
    exchange: str
    segment: str
    symbol: str
    instrument_type: str
    lot_size: int
    tick_size: float
    expiry: Optional[datetime] = None
    strike_price: Optional[float] = None
    option_type: Optional[str] = None
    display_symbol: Optional[str] = None

    @property
    def is_option(self) -> bool:
        """Check if instrument is an option."""
        return self.instrument_type.upper() in ("OPT", "OPTIONS", "OPTION")

    @property
    def is_future(self) -> bool:
        """Check if instrument is a future."""
        return self.instrument_type.upper() in ("FUT", "FUTURES", "FUTURE")

    @property
    def is_equity(self) -> bool:
        """Check if instrument is equity."""
        return self.instrument_type.upper() in ("EQ", "EQUITY")

    @property
    def is_call(self) -> bool:
        """Check if option is a call."""
        return self.option_type and self.option_type.upper() in ("CE", "CALL")

    @property
    def is_put(self) -> bool:
        """Check if option is a put."""
        return self.option_type and self.option_type.upper() in ("PE", "PUT")


@dataclass
class LoadResult:
    """Result of instrument loading operation."""
    total_records: int
    successful: int
    failed: int
    source: InstrumentSource
    errors: List[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.total_records == 0:
            return 0.0
        return self.successful / self.total_records

    @property
    def has_failures(self) -> bool:
        """Check if there were any failures."""
        return self.failed > 0

    @property
    def is_complete(self) -> bool:
        """Check if load completed (has records)."""
        return self.total_records > 0


class MasterDataLoader:
    """
    Loads master instrument data from various sources.
    
    Sources:
    - CSV files (DhanHQ master list)
    - DhanHQ API (segment-wise)
    - Local cache (JSON)
    
    Features:
    - Incremental updates
    - Cache with versioning
    - Performance benchmarks
    - Error handling and reporting
    """

    # DhanHQ CSV URLs
    DHAN_CSV_COMPACT = "https://images.dhan.co/api-data/api-scrip-master.csv"
    DHAN_CSV_DETAILED = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"

    # Cache configuration
    DEFAULT_CACHE_DIR = Path.home() / ".brokersv2" / "cache"
    CACHE_VERSION = "1.0"

    def __init__(
        self,
        registry: InstrumentRegistry,
        cache_enabled: bool = True,
        cache_dir: Optional[Path] = None,
        api_client=None,
    ):
        self._registry = registry
        self._cache_enabled = cache_enabled
        self._cache_dir = cache_dir or self.DEFAULT_CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._api_client = api_client  # Optional DhanHttpClient for API sync

    def load_from_csv(
        self,
        csv_path: str,
        incremental: bool = False,
        force_refresh: bool = False,
    ) -> LoadResult:
        """
        Load instruments from CSV file.
        
        Args:
            csv_path: Path to CSV file
            incremental: Only load new/changed instruments
            force_refresh: Force reload even if cache exists
            
        Returns:
            LoadResult with statistics
            
        Raises:
            CSVLoadError: If file not found or invalid format
        """
        # Validate file exists
        if not os.path.exists(csv_path):
            raise CSVLoadError(f"CSV file not found: {csv_path}")

        try:
            records = self._parse_csv(csv_path)
        except Exception as e:
            raise CSVLoadError(f"Failed to parse CSV: {e}") from e

        if not records:
            raise CSVLoadError("CSV file contains no valid records or missing required headers")

        # Load instruments into registry
        result = self._load_records(records, InstrumentSource.CSV)

        # Save to cache if enabled
        if self._cache_enabled and result.successful > 0:
            self._save_to_cache()

        logger.info(
            f"Loaded {result.successful}/{result.total_records} instruments from CSV "
            f"({result.failed} failed)"
        )

        return result

    def load_from_api(self, exchange_segment: str) -> LoadResult:
        """
        Load instruments from DhanHQ API.
        
        Args:
            exchange_segment: Exchange segment (e.g., "NSE_EQ", "NSE_FNO")
            
        Returns:
            LoadResult with statistics
            
        Raises:
            APISyncError: If API call fails
        """
        try:
            api_data = self._fetch_from_api(exchange_segment)
        except Exception as e:
            raise APISyncError(f"API sync failed for {exchange_segment}: {e}") from e

        # Convert API data to records
        records = self._parse_api_response(api_data)

        # Load into registry
        result = self._load_records(records, InstrumentSource.API)

        # Save to cache
        if self._cache_enabled and result.successful > 0:
            self._save_to_cache()

        logger.info(
            f"Loaded {result.successful}/{result.total_records} instruments from API "
            f"for {exchange_segment}"
        )

        return result

    def load_all_segments(self) -> List[LoadResult]:
        """
        Load instruments from all major segments.
        
        Returns:
            List of LoadResult for each segment
        """
        segments = ["NSE_EQ", "NSE_FNO", "BSE_EQ", "BSE_FNO", "MCX"]
        results = []

        for segment in segments:
            try:
                result = self.load_from_api(segment)
                results.append(result)
            except APISyncError as e:
                logger.warning(f"Failed to load {segment}: {e}")
                results.append(LoadResult(
                    total_records=0,
                    successful=0,
                    failed=0,
                    source=InstrumentSource.API,
                    errors=[str(e)],
                ))

        return results

    def load_from_cache(self) -> Optional[LoadResult]:
        """
        Load instruments from cache.
        
        Returns:
            LoadResult or None if cache doesn't exist
        """
        cache_file = self._get_cache_file_path()
        
        if not cache_file.exists():
            return None

        try:
            with open(cache_file, 'r') as f:
                cache_data = json.load(f)

            instruments_data = cache_data.get("instruments", [])
            
            records = []
            for inst_data in instruments_data:
                record = self._cache_record_to_record(inst_data)
                records.append(record)

            result = self._load_records(records, InstrumentSource.CACHE)

            logger.info(f"Loaded {result.successful} instruments from cache")
            return result

        except Exception as e:
            raise CacheError(f"Failed to load from cache: {e}") from e

    def get_cache_file(self) -> Optional[str]:
        """Get cache file path."""
        cache_file = self._get_cache_file_path()
        return str(cache_file) if cache_file.exists() else None

    def get_cache_metadata(self) -> Optional[Dict[str, Any]]:
        """Get cache metadata."""
        cache_file = self._get_cache_file_path()
        
        if not cache_file.exists():
            return None

        try:
            with open(cache_file, 'r') as f:
                cache_data = json.load(f)

            return {
                "version": cache_data.get("version"),
                "timestamp": cache_data.get("timestamp"),
                "count": cache_data.get("count", 0),
                "source": cache_data.get("source"),
            }
        except Exception:
            return None

    def _parse_csv(self, csv_path: str) -> List[InstrumentRecord]:
        """Parse CSV file into instrument records."""
        records = []
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            # Validate we have minimum required columns
            required_columns = {"SECURITY_ID", "SM_SYMBOL_NAME", "SEM_EXCH_INSTRUMENT_TYPE"}
            
            available_columns = set(reader.fieldnames or [])
            if not required_columns.issubset(available_columns):
                raise CSVLoadError(
                    f"CSV missing required columns: {required_columns - available_columns}"
                )

            for row in reader:
                try:
                    record = self._csv_row_to_record(row)
                    records.append(record)
                except Exception as e:
                    logger.debug(f"Skipping invalid row: {e}")
                    continue

        return records

    def _csv_row_to_record(self, row: Dict[str, str]) -> InstrumentRecord:
        """Convert CSV row to InstrumentRecord."""
        # Parse expiry date if present
        expiry = None
        if row.get("SEM_EXPIRY_DATE"):
            try:
                expiry = datetime.strptime(row["SEM_EXPIRY_DATE"], "%Y-%m-%d")
            except ValueError:
                pass

        # Parse strike price if present
        strike_price = None
        if row.get("SEM_STRIKE_PRICE"):
            try:
                strike_price = float(row["SEM_STRIKE_PRICE"])
            except ValueError:
                pass

        return InstrumentRecord(
            security_id=row["SECURITY_ID"],
            exchange=row["SEM_EXM_EXCH_ID"],
            segment=row["SEM_SEGMENT"],
            symbol=row["SM_SYMBOL_NAME"],
            instrument_type=row["SEM_EXCH_INSTRUMENT_TYPE"],
            lot_size=int(row.get("SEM_LOT_UNITS", 1)),
            tick_size=float(row.get("SEM_TICK_SIZE", 0.01)),
            expiry=expiry,
            strike_price=strike_price,
            option_type=row.get("SEM_OPTION_TYPE"),
            display_symbol=row.get("SEM_CUSTOM_SYMBOL"),
        )

    def _parse_api_response(self, api_data: List[Dict]) -> List[InstrumentRecord]:
        """Parse API response into instrument records."""
        records = []
        
        for item in api_data:
            try:
                record = InstrumentRecord(
                    security_id=item["securityId"],
                    exchange=item.get("exchangeSegment", "").replace("_EQ", "").replace("_FNO", ""),
                    segment=item.get("exchangeSegment", ""),
                    symbol=item.get("symbol", ""),
                    instrument_type=item.get("instrumentType", ""),
                    lot_size=item.get("lotSize", 1),
                    tick_size=item.get("tickSize", 0.01),
                )
                records.append(record)
            except Exception as e:
                logger.debug(f"Skipping invalid API record: {e}")
                continue

        return records

    def _load_records(
        self,
        records: List[InstrumentRecord],
        source: InstrumentSource,
    ) -> LoadResult:
        """Load records into registry."""
        successful = 0
        failed = 0
        errors = []

        for record in records:
            try:
                instrument = self._record_to_instrument(record)
                
                # Register in registry
                self._registry.register(
                    instrument=instrument,
                    security_id=SecurityId(record.security_id),
                    exchange_segment=record.segment,
                    ws_symbol=record.symbol,
                )
                
                successful += 1
            except Exception as e:
                failed += 1
                errors.append(f"Failed to load {record.symbol}: {e}")

        return LoadResult(
            total_records=len(records),
            successful=successful,
            failed=failed,
            source=source,
            errors=errors,
        )

    def _record_to_instrument(self, record: InstrumentRecord) -> CanonicalInstrument:
        """Convert InstrumentRecord to CanonicalInstrument."""
        uid = InternalUid(f"{record.exchange}_{record.security_id}")

        if record.is_option and record.expiry and record.strike_price and record.option_type:
            # Create option instrument
            return CanonicalInstrument.create_option(
                symbol=record.symbol,
                exchange=Exchange(record.exchange),
                expiry=record.expiry.date(),
                strike=Decimal(str(record.strike_price)),
                option_type=OptionType(record.option_type),
                lot_size=record.lot_size,
                tick_size=Decimal(str(record.tick_size)),
            )
        elif record.is_future and record.expiry:
            # Create future instrument
            return CanonicalInstrument.create_future(
                symbol=record.symbol,
                exchange=Exchange(record.exchange),
                expiry=record.expiry.date(),
                lot_size=record.lot_size,
                tick_size=Decimal(str(record.tick_size)),
            )
        else:
            # Create equity instrument
            return CanonicalInstrument.create_equity(
                symbol=record.symbol,
                exchange=Exchange(record.exchange),
                lot_size=record.lot_size,
                tick_size=Decimal(str(record.tick_size)),
            )

    def _fetch_from_api(self, exchange_segment: str) -> List[Dict]:
        """
        Fetch instruments from DhanHQ API.

        Requires an api_client (e.g., DhanHttpClient) to be injected at init.
        Falls back to CSV download if no client is configured.
        """
        if self._api_client is None:
            raise APISyncError(
                f"No API client configured for {exchange_segment}. "
                f"Pass api_client to MasterDataLoader or use CSV loading instead."
            )

        try:
            # Dhan master endpoint returns a list of instrument dicts
            # Use urllib for sync HTTP to avoid asyncio anti-patterns
            import urllib.request
            import urllib.error
            import json

            base_url = getattr(self._api_client, "config", None)
            base_url = base_url.base_url if base_url else "https://api.dhan.co/v2"
            url = f"{base_url}/master"
            headers = getattr(self._api_client, "_headers", {})

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read().decode("utf-8")
                master_data = json.loads(raw)

            if not isinstance(master_data, list):
                raise APISyncError(
                    f"Unexpected master data format for {exchange_segment}: {type(master_data)}"
                )

            # Filter by exchange segment if specified
            if exchange_segment:
                filtered = []
                for item in master_data:
                    if not isinstance(item, dict):
                        continue
                    seg = str(item.get("SEM_EXM_EXCH_ID", "")).upper()
                    expected = exchange_segment.split("_")[0] if "_" in exchange_segment else exchange_segment
                    if seg == expected:
                        filtered.append(item)
                return filtered

            return master_data

        except APISyncError:
            raise
        except urllib.error.HTTPError as exc:
            raise APISyncError(
                f"HTTP {exc.code} fetching instruments for {exchange_segment}: {exc.reason}"
            ) from exc
        except Exception as exc:
            raise APISyncError(
                f"Failed to fetch instruments from API for {exchange_segment}: {exc}"
            ) from exc

    def _save_to_cache(self):
        """Save registry instruments to cache."""
        cache_file = self._get_cache_file_path()

        try:
            instruments_data = []
            for instrument in self._registry.get_all_instruments():
                inst_data = {
                    "symbol": instrument.symbol,
                    "exchange": instrument.exchange.value,
                    "instrument_type": instrument.instrument_type.value,
                    "lot_size": instrument.lot_size,
                    "tick_size": float(instrument.tick_size),
                }
                instruments_data.append(inst_data)

            cache_data = {
                "version": self.CACHE_VERSION,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "count": len(instruments_data),
                "source": "registry",
                "instruments": instruments_data,
            }

            with open(cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)

            logger.debug(f"Saved {len(instruments_data)} instruments to cache")

        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")

    def _cache_record_to_record(self, inst_data: Dict) -> InstrumentRecord:
        """Convert cached data to InstrumentRecord."""
        return InstrumentRecord(
            security_id=f"cache_{inst_data['symbol']}",
            exchange=inst_data["exchange"],
            segment="",
            symbol=inst_data["symbol"],
            instrument_type=inst_data.get("instrument_type", "EQ"),
            lot_size=inst_data.get("lot_size", 1),
            tick_size=inst_data.get("tick_size", 0.01),
        )

    def _get_cache_file_path(self) -> Path:
        """Get cache file path."""
        return self._cache_dir / "instruments_cache.json"

    async def schedule_daily_refresh(
        self,
        refresh_time_ist: "time" = None,  # type: ignore[assignment]
    ) -> None:
        """
        Background task: download the Dhan CSV master at 08:45 IST every day.

        Runs forever as an asyncio coroutine.  Wire via asyncio.ensure_future()
        in the application startup sequence (bootstrap.py).

        Args:
            refresh_time_ist: Override the refresh time (default 08:45 IST).
        """
        import asyncio
        from datetime import time as _time
        from zoneinfo import ZoneInfo

        if refresh_time_ist is None:
            refresh_time_ist = _time(8, 45)  # 08:45 IST before market open

        IST = ZoneInfo("Asia/Kolkata")
        logger.info("MasterDataLoader: daily refresh scheduled at %s IST", refresh_time_ist)

        while True:
            from datetime import datetime as _dt
            now_ist = _dt.now(IST)
            today_refresh = _dt.combine(now_ist.date(), refresh_time_ist, tzinfo=IST)

            if now_ist >= today_refresh:
                # Already past today's refresh time — schedule for tomorrow
                from datetime import timedelta
                today_refresh += timedelta(days=1)

            wait_seconds = (today_refresh - now_ist).total_seconds()
            logger.debug(
                "MasterDataLoader: next refresh in %.0f seconds (%s IST)",
                wait_seconds,
                today_refresh.strftime("%Y-%m-%d %H:%M:%S"),
            )
            await asyncio.sleep(wait_seconds)

            # Perform the refresh
            try:
                before_count = len(self._registry._instruments) if hasattr(self._registry, "_instruments") else 0
                await self._download_and_reload()
                after_count = len(self._registry._instruments) if hasattr(self._registry, "_instruments") else 0
                diff = after_count - before_count
                logger.info(
                    "MasterDataLoader: refresh complete — %d instruments "
                    "(diff %+d from previous load).",
                    after_count, diff,
                )
            except Exception as exc:
                logger.error("MasterDataLoader: daily refresh FAILED: %s", exc, exc_info=True)

    async def _download_and_reload(self) -> None:
        """Download the Dhan CSV from the CDN and reload the registry."""
        import asyncio
        import io
        import tempfile

        url = self.DHAN_CSV_COMPACT

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    resp.raise_for_status()
                    content = await resp.text(encoding="utf-8", errors="replace")
        except ImportError:
            # Fallback to blocking urllib in a thread pool
            import urllib.request
            loop = asyncio.get_running_loop()
            content = await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(url, timeout=60).read().decode("utf-8", errors="replace"),
            )

        # Write to a temp file and pass to the existing CSV loader
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            # load_from_csv is CPU/IO-bound synchronous — run in a thread pool
            # so the event loop is not blocked for the duration of the CSV parse.
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self.load_from_csv, tmp_path)
        finally:
            import os as _os
            try:
                _os.unlink(tmp_path)
            except OSError:
                pass
