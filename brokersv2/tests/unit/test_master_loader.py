"""Tests for Master Data Loader - CSV import, API sync, caching."""
import pytest
import tempfile
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock
from brokersv2.domain.instrument.master_loader import (
    MasterDataLoader,
    InstrumentSource,
    LoadResult,
    MasterDataError,
    CSVLoadError,
    APISyncError,
    CacheError,
    InstrumentRecord,
)
from brokersv2.domain.instrument.registry import InstrumentRegistry
from brokersv2.domain.instrument.models import CanonicalInstrument
from brokersv2.core.types import Exchange, SecurityId


@pytest.fixture
def registry():
    """Create empty instrument registry."""
    return InstrumentRegistry()


@pytest.fixture
def sample_csv_content():
    """Sample DhanHQ CSV format."""
    return """SECURITY_ID,SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_INSTRUMENT_NAME,SM_SYMBOL_NAME,SEM_CUSTOM_SYMBOL,SEM_EXCH_INSTRUMENT_TYPE,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE,SEM_LOT_UNITS,SEM_TICK_SIZE,SEM_EXPIRY_FLAG
12345,NSE,EQ,EQUITY,RELIANCE,RELIANCE,EQ,,,,1,0.01,
12346,NSE,EQ,EQUITY,TCS,TCS,EQ,,,,1,0.01,
54321,NFO,FNO,FUTURES,NIFTY,NIFTY26JANFUT,FUT,2026-01-29,,,75,0.05,M
98765,NFO,FNO,OPTIONS,NIFTY,NIFTY26JAN24000CE,OPT,2026-01-29,24000.00,CE,75,0.05,W
98766,NFO,FNO,OPTIONS,NIFTY,NIFTY26JAN24000PE,OPT,2026-01-29,24000.00,PE,75,0.05,W
"""


@pytest.fixture
def sample_csv_file(sample_csv_content):
    """Create temporary CSV file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write(sample_csv_content)
        return f.name


class TestInstrumentRecord:
    """Test InstrumentRecord value object."""

    def test_create_equity_record(self):
        """Test creating equity instrument record."""
        record = InstrumentRecord(
            security_id="12345",
            exchange="NSE",
            segment="EQ",
            symbol="RELIANCE",
            instrument_type="EQ",
            lot_size=1,
            tick_size=0.01,
        )

        assert record.security_id == "12345"
        assert record.exchange == "NSE"
        assert record.is_option is False
        assert record.is_future is False
        assert record.is_equity is True

    def test_create_option_record(self):
        """Test creating option instrument record."""
        record = InstrumentRecord(
            security_id="98765",
            exchange="NFO",
            segment="FNO",
            symbol="NIFTY26JAN24000CE",
            instrument_type="OPT",
            expiry=date(2026, 1, 29),
            strike_price=24000.00,
            option_type="CE",
            lot_size=75,
            tick_size=0.05,
        )

        assert record.is_option is True
        assert record.is_call is True
        assert record.is_put is False
        assert record.strike_price == 24000.00
        assert record.option_type == "CE"

    def test_create_future_record(self):
        """Test creating future instrument record."""
        record = InstrumentRecord(
            security_id="54321",
            exchange="NFO",
            segment="FNO",
            symbol="NIFTY26JANFUT",
            instrument_type="FUT",
            expiry=date(2026, 1, 29),
            lot_size=75,
            tick_size=0.05,
        )

        assert record.is_future is True
        assert record.is_option is False

    def test_display_symbol(self):
        """Test display symbol generation."""
        record = InstrumentRecord(
            security_id="12345",
            exchange="NSE",
            segment="EQ",
            symbol="RELIANCE",
            instrument_type="EQ",
            lot_size=1,
            tick_size=0.01,
            display_symbol="RELIANCE",
        )

        assert record.display_symbol == "RELIANCE"


class TestMasterDataLoader:
    """Test master data loading from various sources."""

    def test_load_from_csv_basic(self, registry, sample_csv_file):
        """Test basic CSV loading."""
        loader = MasterDataLoader(registry)
        result = loader.load_from_csv(sample_csv_file)

        assert result is not None
        assert result.total_records >= 2  # At least 2 valid records
        assert result.successful >= 2
        assert result.failed == 0
        assert result.source == InstrumentSource.CSV

    def test_load_from_csv_file_not_found(self, registry):
        """Test CSV loading with non-existent file."""
        loader = MasterDataLoader(registry)

        with pytest.raises(CSVLoadError, match="not found"):
            loader.load_from_csv("/nonexistent/file.csv")

    def test_load_from_csv_invalid_format(self, registry):
        """Test CSV loading with invalid format."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("invalid,data\nno,headers")
            csv_file = f.name

        loader = MasterDataLoader(registry)

        with pytest.raises(CSVLoadError, match="invalid|missing"):
            loader.load_from_csv(csv_file)

        os.unlink(csv_file)

    def test_load_csv_equity_instruments(self, registry, sample_csv_file):
        """Test loading equity instruments from CSV."""
        loader = MasterDataLoader(registry)
        result = loader.load_from_csv(sample_csv_file)

        assert registry.instrument_count >= 2  # RELIANCE, TCS

        # Verify equity lookup works
        instrument = registry.lookup_by_symbol("RELIANCE", Exchange.NSE)
        assert instrument is not None
        assert instrument.symbol == "RELIANCE"
        assert instrument.exchange == Exchange.NSE
        assert instrument.exchange == Exchange.NSE

    def test_load_csv_option_instruments(self, registry, sample_csv_file):
        """Test loading option instruments from CSV."""
        loader = MasterDataLoader(registry)
        result = loader.load_from_csv(sample_csv_file)

        # Verify options are loaded
        options = registry.get_options_chain("NIFTY", Exchange.NFO, date(2026, 1, 29))
        assert len(options) >= 2  # CE and PE

    def test_load_csv_future_instruments(self, registry, sample_csv_file):
        """Test loading future instruments from CSV."""
        loader = MasterDataLoader(registry)
        result = loader.load_from_csv(sample_csv_file)

        # Verify futures are loaded
        futures = registry.get_instruments_by_type("FUTURE")
        assert len(futures) >= 1

    def test_load_from_api_segment(self, registry):
        """Test loading instruments from DhanHQ API."""
        loader = MasterDataLoader(registry)

        # Mock API response
        mock_response = [
            {
                "securityId": "11111",
                "exchangeSegment": "NSE_EQ",
                "symbol": "INFY",
                "displayName": "INFY",
                "instrumentType": "EQUITY",
                "lotSize": 1,
                "tickSize": 0.01,
            }
        ]

        with patch.object(loader, '_fetch_from_api', return_value=mock_response):
            result = loader.load_from_api("NSE_EQ")

            assert result is not None
            assert result.total_records == 1
            assert result.successful == 1
            assert result.source == InstrumentSource.API

    def test_load_from_api_error(self, registry):
        """Test API loading with error."""
        loader = MasterDataLoader(registry)

        with patch.object(loader, '_fetch_from_api', side_effect=Exception("API error")):
            with pytest.raises(APISyncError):
                loader.load_from_api("NSE_EQ")

    def test_load_all_segments(self, registry):
        """Test loading all segments sequentially."""
        loader = MasterDataLoader(registry)

        with patch.object(loader, 'load_from_api') as mock_load:
            mock_load.return_value = LoadResult(
                total_records=10,
                successful=10,
                failed=0,
                source=InstrumentSource.API,
            )

            results = loader.load_all_segments()

            # Should load all major segments
            assert len(results) >= 4  # NSE_EQ, NSE_FNO, MCX, BSE_EQ
            assert all(r.successful > 0 for r in results)

    def test_incremental_update(self, registry, sample_csv_file):
        """Test incremental update (only new/changed instruments)."""
        loader = MasterDataLoader(registry)

        # Initial load
        result1 = loader.load_from_csv(sample_csv_file)
        assert result1.successful == 5

        # Incremental update (should detect no changes)
        result2 = loader.load_from_csv(sample_csv_file, incremental=True)
        assert result2 is not None
        # Same instruments, no duplicates

    def test_load_with_validation_errors(self, registry):
        """Test CSV loading with some validation errors."""
        csv_content = """SECURITY_ID,SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_INSTRUMENT_NAME,SM_SYMBOL_NAME,SEM_CUSTOM_SYMBOL,SEM_EXCH_INSTRUMENT_TYPE,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE,SEM_LOT_UNITS,SEM_TICK_SIZE,SEM_EXPIRY_FLAG
12345,NSE,EQ,EQUITY,RELIANCE,RELIANCE,EQ,,,,50,0.01,
12346,INVALID_EXCHANGE,EQ,EQUITY,BAD,BAD,EQ,,,,50,0.01,
12347,NSE,EQ,EQUITY,TCS,TCS,EQ,,,,50,0.01,
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            csv_file = f.name

        loader = MasterDataLoader(registry)
        result = loader.load_from_csv(csv_file)

        # Should have some failures
        assert result.failed >= 1
        assert result.successful >= 2

        os.unlink(csv_file)

    def test_load_performance_benchmark(self, registry):
        """Test loading performance with large dataset."""
        import time
        
        # Generate 1000 instruments
        csv_lines = ["SECURITY_ID,SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_INSTRUMENT_NAME,SM_SYMBOL_NAME,SEM_CUSTOM_SYMBOL,SEM_EXCH_INSTRUMENT_TYPE,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE,SEM_LOT_UNITS,SEM_TICK_SIZE,SEM_EXPIRY_FLAG"]
        for i in range(1000):
            csv_lines.append(f"{10000+i},NSE,EQ,EQUITY,STOCK{i},STOCK{i},EQ,,,,50,0.01,")
        
        csv_content = "\n".join(csv_lines)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write(csv_content)
            csv_file = f.name

        loader = MasterDataLoader(registry)
        
        start = time.time()
        result = loader.load_from_csv(csv_file)
        elapsed = time.time() - start

        assert result.successful == 1000
        assert elapsed < 2.0  # Should load 1000 instruments in <2 seconds

        os.unlink(csv_file)


class TestMasterDataLoaderCaching:
    """Test caching functionality."""

    def test_save_cache(self, registry, sample_csv_file):
        """Test saving loaded instruments to cache."""
        loader = MasterDataLoader(registry, cache_enabled=True)
        loader.load_from_csv(sample_csv_file)

        cache_file = loader.get_cache_file()
        assert cache_file is not None
        assert os.path.exists(cache_file)

    def test_load_from_cache(self, registry, sample_csv_file):
        """Test loading instruments from cache."""
        # First load from CSV
        loader1 = MasterDataLoader(registry, cache_enabled=True)
        loader1.load_from_csv(sample_csv_file)

        # Create new registry and load from cache
        registry2 = InstrumentRegistry()
        loader2 = MasterDataLoader(registry2, cache_enabled=True)
        
        result = loader2.load_from_cache()

        assert result is not None
        assert result.successful > 0
        assert result.source == InstrumentSource.CACHE

    def test_cache_versioning(self, registry, sample_csv_file):
        """Test cache version tracking."""
        loader = MasterDataLoader(registry, cache_enabled=True)
        loader.load_from_csv(sample_csv_file)

        metadata = loader.get_cache_metadata()
        assert metadata is not None
        assert "version" in metadata
        assert "timestamp" in metadata
        assert "count" in metadata

    def test_cache_invalidation(self, registry, sample_csv_file):
        """Test cache invalidation on source update."""
        loader = MasterDataLoader(registry, cache_enabled=True)
        
        # Load from CSV (creates cache)
        loader.load_from_csv(sample_csv_file)
        
        # Load again with force_refresh
        result = loader.load_from_csv(sample_csv_file, force_refresh=True)
        
        assert result is not None
        # Should reload from source, not cache

    def test_cache_performance(self, registry, sample_csv_file):
        """Test cache load is faster than CSV."""
        import time
        
        # Load from CSV
        loader1 = MasterDataLoader(registry, cache_enabled=True)
        start = time.time()
        loader1.load_from_csv(sample_csv_file)
        csv_time = time.time() - start

        # Load from cache
        registry2 = InstrumentRegistry()
        loader2 = MasterDataLoader(registry2, cache_enabled=True)
        start = time.time()
        loader2.load_from_cache()
        cache_time = time.time() - start

        # Cache should be faster
        assert cache_time < csv_time


class TestInstrumentSource:
    """Test instrument source enum."""

    def test_source_values(self):
        """Test source enum values."""
        assert InstrumentSource.CSV.value == "CSV"
        assert InstrumentSource.API.value == "API"
        assert InstrumentSource.CACHE.value == "CACHE"


class TestLoadResult:
    """Test LoadResult value object."""

    def test_successful_load(self):
        """Test successful load result."""
        result = LoadResult(
            total_records=100,
            successful=95,
            failed=5,
            source=InstrumentSource.CSV,
        )

        assert result.success_rate == pytest.approx(0.95)
        assert result.has_failures is True
        assert result.is_complete is True

    def test_perfect_load(self):
        """Test load with no failures."""
        result = LoadResult(
            total_records=100,
            successful=100,
            failed=0,
            source=InstrumentSource.API,
        )

        assert result.success_rate == 1.0
        assert result.has_failures is False

    def test_empty_load(self):
        """Test empty load result."""
        result = LoadResult(
            total_records=0,
            successful=0,
            failed=0,
            source=InstrumentSource.CACHE,
        )

        assert result.success_rate == 0.0
        assert result.is_complete is False
