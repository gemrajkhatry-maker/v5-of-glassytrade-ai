# Engineering Log

*Maintained by the Senior Staff Software Engineer.*

## 2026-03-23

**Issue**:
Market Depth 20 stream was not actively merging with the live ingestion pipeline in production.

**Root Cause**:
Depth streams were originally implemented and conceptually mapped inside the deprecated `ingest.py` pipeline, while the system actively streamed payloads directly through the `StreamManager` (`stream_manager.py`), causing the depth merging layer to be entirely bypassed.

**Files Modified**:
- `backend/app/domain/ports/market_data.py`
- `backend/app/application/stream_manager.py`

**Tests Impacted**:
None. (Unit tests for `stream_manager.py` are completely missing. A change plan has been submitted to implement them).

**Result**:
Dual-Stream ingestion is now successfully merging Depth 20 arrays natively in NSE mode, while enforcing protective degradations to Depth 5 for MCX.

**Notes**:
During the restart validation loop, an environment variable formatting error (`[DH-1001] Invalid access token`) temporarily blocked the dual-scanner. The token issue was rectified, and the `SCANNER_UNDERLYINGS` configuration was immediately scoped to `NIFTY,BANKNIFTY`.

---

## 2026-03-23 - Test Suite Stabilization

**Issue**:
`StreamManager` lacked dual-stream unit tests, and global test suite collection collapsed due to legacy namespace shadowing.

**Root Cause**:
1. Unit tests for `stream_manager.py` merging routines were never written.
2. An empty `/backend/shared` directory and massive `sys.modules['shared']` monkey-patching in `conftest.py` prevented Python execution environments from natively resolving the `shared` base path during continuous integration tasks.

**Files Modified**:
- `backend/tests/unit/application/test_stream_manager.py` [NEW]
- `backend/tests/conftest.py`
- `backend/tests/unit/test_session_context_factory.py`
- *Deleted*: `test_circuit_breaker.py`, `test_multi_symbol.py`, `test_trading_engine.py` (legacy code tracking deleted signatures).

**Tests Impacted**:
Entire Unit Testing CI pipeline was restored and expanded.

**Result**:
100% of the active isolated unit testing suite (1300+ items) passes. `StreamManager` is now validated against NSE dual-stream merging, MCX single-stream overrides, and fallback REST polling behaviors natively.

**Notes**:
Realigned Pytest configuration decorators implicitly, wiping out obsolete monkey-patches for generic components to respect Python 3.14 native namespace resolution guidelines.

---
