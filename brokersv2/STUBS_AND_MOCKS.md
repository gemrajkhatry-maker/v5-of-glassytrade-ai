# Stubs, Mock Implementations, and Synthetic Parts in brokersv2

**Generated:** 2026-05-10  
**Scope:** `/Users/apple/Downloads/v5-of-glassytrade-ai/brokersv2` (excluding tests)

---

## Overview

This document catalogs all stubs, mock implementations, and synthetic parts found in the `brokersv2` codebase.

---

## 1. Explicit Stub / NotImplementedError

| File | Lines | Description |
|------|-------|-------------|
| ~~`analytics/options/__init__.py`~~ | ~~31-34~~ | ~~`detect_buildups()` raises `NotImplementedError`~~ ✅ **IMPLEMENTED** - Now detects OI buildup patterns with configurable thresholds |

---

## 2. Dry Run / Synthetic Mode (No Real Orders Sent)

Files that have `dry_run` mode which returns synthetic IDs instead of sending real orders to the broker.

| File | Lines | Description |
|------|-------|-------------|
| `infrastructure/dhan_adapter/adapter.py` | 49, 66, 129-131, 155-157, 281-283 | `DhanBrokerAdapter` has `dry_run` mode that returns synthetic IDs like `"DRY_RUN_{order_id}"` instead of sending real orders |
| `app/bootstrap.py` | 87, 95, 130-131, 240, 250, 265 | Factory functions support `dry_run` parameter for creating adapters without real connections |

---

## 3. TODO Stubs (Intentionally Incomplete)

These are placeholders for future implementation.

| File | Lines | Description |
|------|-------|-------------|
| `cache/intelligent_cache.py` | 171 | `# TODO: Implement key indexing for efficient invalidation` |
| `providers/opencart_provider.py` | 199 | `# TODO: Implement OpenChart symbol search` |
| `providers/dhan_provider.py` | 162-165 | `# TODO: Implement Dhan symbol search` - returns empty list |
| `replay/event_store.py` | 128 | `# TODO: Use proper hash (SHA256)` - uses simple checksum instead |
| `domain/instrument/master_loader.py` | 475-480 | `# TODO: Implement actual API call` - raises `APISyncError` |

---

## 4. Placeholder / Not Implemented Patterns

| File | Lines | Description |
|------|-------|-------------|
| `domain/instrument/models.py` | 294 | `__eq__` returns `NotImplemented` for non-CanonicalInstrument comparisons (standard Python pattern, not a stub) |
| `resilience/policies/rate_limit.py` | 328 | `_ScheduledRequest.__eq__` returns `NotImplemented` (standard Python pattern) |

---

## 5. Mock Data / Fake Data Patterns

| File | Lines | Description |
|------|-------|-------------|
| ~~`providers/health_monitor.py`~~ | ~~193, 196-200~~ | ~~Hardcoded `TEST_INSTRUMENT_SYMBOL = "RELIANCE"`~~ ✅ **FIXED** - Now configurable via `test_symbol` parameter or `HEALTH_CHECK_SYMBOL` env var |

---

## 6. Synthetic Return Values (Fake IDs/Responses)

Functions that return stub/fake data instead of real API responses.

| File | Lines | Description |
|------|-------|-------------|
| `infrastructure/dhan_adapter/adapter.py` | 131 | Returns `f"DRY_RUN_{order.order_id}"` only when `dry_run=True` (intentional safety feature) |
| ~~`infrastructure/dhan_adapter/factory.py` | 232-236~~ | ~~`get_quote()` returns minimal stub dict~~ ✅ **IMPLEMENTED** - Now calls real `client.get_quote()` |
| ~~`infrastructure/dhan_adapter/factory.py` | 307-311~~ | ~~`option_chain()` returns stub dict~~ ✅ **IMPLEMENTED** - Now calls real `client.get_option_chain()` |
| ~~`infrastructure/dhan_adapter/factory.py` | 313-316~~ | ~~`get_expiry_list()` returns empty list~~ ✅ **IMPLEMENTED** - Now calls `/optionchain/expirylist` endpoint |
| ~~`marketdata/pipeline.py` | 94-104~~ | ~~`get_quote()` returns hardcoded Quote(ltp=100.0, bid=99.9, ...)~~ ✅ **IMPLEMENTED** - Now calls real broker API via injected client |
| ~~`marketdata/pipeline.py` | 117-128~~ | ~~`get_historical()` returns single hardcoded candle~~ ✅ **IMPLEMENTED** - Now calls real broker API via injected client |
| ~~`gateway/server.py` | 117-147~~ | ~~`DryRunBroker.place_order_mock()` generates fake order IDs~~ ✅ **MOVED** - Now in `brokersv2/testing/mocks.py` as explicit test utility |
| ~~`gateway/server.py` | 164-189~~ | ~~`DryRunBroker.get_quote_mock()` returns mock prices~~ ✅ **MOVED** - Now in `brokersv2/testing/mocks.py` |
| ~~`gateway/server.py` | 191-220~~ | ~~`DryRunBroker.get_historical_mock()` generates mock candles~~ ✅ **MOVED** - Now in `brokersv2/testing/mocks.py` |

---

## 7. Configuration-Based Synthetic Mode

Gracefull degradation patterns when optional dependencies are not available.

| File | Lines | Description |
|------|-------|-------------|
| `app/bootstrap.py` | 44-45 | `pass  # python-dotenv not installed; rely on system environment.` |
| `infrastructure/dhan_adapter/factory.py` | 33 | `pass  # dotenv not installed, use system env only` |
| `replay/event_capture.py` | 106, 135 | `# Suppress flush errors on exit` and `# Already closed` pass statements |

---

## Summary Table

| Category | Count | Files Affected |
|----------|-------|----------------|
| NotImplementedError | 0 | ~~`analytics/options/__init__.py`~~ ✅ Implemented |
| Dry Run Mode | 2 | `infrastructure/dhan_adapter/adapter.py`, `app/bootstrap.py` |
| TODO Stubs | 5 | `cache/intelligent_cache.py`, `providers/opencart_provider.py`, `providers/dhan_provider.py`, `replay/event_store.py`, `domain/instrument/master_loader.py` |
| Standard Python NotImplemented | 2 | `domain/instrument/models.py`, `resilience/policies/rate_limit.py` |
| ~~Mock Data~~ ✅ Fixed | 0 | ~~`providers/health_monitor.py`~~ ✅ Configurable |
| ~~Synthetic Returns~~ ✅ Implemented | 1 | `infrastructure/dhan_adapter/adapter.py` (dry_run only - intentional safety) |
| Config Fallbacks | 3 | `app/bootstrap.py`, `infrastructure/dhan_adapter/factory.py`, `replay/event_capture.py` |

---

## New Test Coverage

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `tests/unit/test_marketdata_pipeline_real.py` | 9 | Pipeline with mocked client |
| `tests/unit/test_analytics_buildups.py` | 7 | detect_buildups function |
| `tests/unit/test_testing_mocks.py` | 6 | DryRunBroker in testing module |
| **Total** | **22** | All passing |