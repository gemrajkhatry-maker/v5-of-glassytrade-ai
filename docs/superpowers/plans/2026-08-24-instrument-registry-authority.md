# Instrument Registry Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** One `InstrumentRegistry` owns root → {exchange, dhan_exchange, tick, lot, strike, freeze, min_oi, session_profile}. Every MCX/NSE mode path reads it. Unknown roots fail loud.

**Architecture:** `quant/contracts/instrument_registry.py` is the table. `ExchangeConfig` becomes a façade that builds tick/lot/freeze/underlyings from that table (AMT thresholds stay exchange-level). YAML may enable roots but cannot disagree on lot/tick/strike/session clock. Scanner, selector, coordinator spawn, Dhan resolver, `market_info`, and the frontend MCX set all consume the registry (frontend locked by a Python grep test).

**Tech Stack:** Python 3.11, existing pytest, YAML config loader, TypeScript profile helper.

## Global Constraints

- No new dependencies. No fourth “source of truth” module.
- Do not commit unless the user asks.
- Unknown instrument root raises `UnknownInstrumentError` on scan/spawn/tick/lot — never `"MCX"` / `0.05` / `1.0`.
- Registry values for NICKEL tick and COTTONCANDY lot match the previously tested ExchangeConfig (1.0 / 25).
- SILVERM lot is 5 (not YAML 500). NSE `session_close` is 15:30.

---

### Task 1: Authority tests (RED)

**Files:**
- Create: `tests/quant/test_instrument_authority.py`

Cover: YAML SILVERM lot == registry 5; ExchangeConfig lots/ticks == registry; selector strike/lot == registry; scanner SENSEX `dhan_exchange` is BFO not MCX; unknown root does not scan as MCX; coordinator spawn `market` is the symbol’s `session_profile`; NSE YAML session_close is 15:30; frontend `MCX_UNDERLYINGS` set == `mcx_roots()`.

### Task 2: Registry + ExchangeConfig façade

**Files:**
- Modify: `quant/contracts/instrument_registry.py` (NICKEL tick 1.0, COTTONCANDY lot 25, `specs()`)
- Modify: `quant/contracts/exchange_config.py` (build underlyings/tick/lot/freeze/point from registry)
- Modify: `quant/contracts/timezones.py` (phase boundary times)

### Task 3: Hot-path consumers

**Files:**
- Modify: `quant/amt/session/scanner.py`
- Modify: `quant/amt/session/selector.py`
- Modify: `quant/multi_engine.py`
- Modify: `quant/amt/session/context.py`
- Modify: `brokers/broker/market_info.py`
- Modify: `brokers/broker/dhan/application/exchange_resolver.py`
- Modify: `brokers/broker/dhan/domain/constants.py` (index lots/strikes no longer duplicated)

### Task 4: YAML + boot validation

**Files:**
- Modify: `backend/config/strategies/mcx_options.yaml` (SILVERM lot 5)
- Modify: `backend/config/base.yaml` (NSE session_close 15:30)
- Modify: `backend/app/config_models/__init__.py` + `loader.py` (default 15:30)
- Modify: `backend/app/config_models/validator.py` (RULE-13: YAML lot/tick/strike/session must match registry)

### Task 5: Frontend + test updates

**Files:**
- Modify: `frontend/utils/profileInfo.ts` (MCX set = registry roots including GOLDPETAL)
- Modify: `backend/tests/unit/test_strategy_regressions.py` (read registry, not deleted dicts)

### Task 6: Verify

Run: `pytest tests/quant/test_instrument_authority.py tests/quant/amt/session/test_symbol_registry.py tests/quant/amt/session/test_selector.py tests/quant/amt/session/test_scanner.py backend/tests/unit/test_strategy_regressions.py backend/tests/unit/domain/test_lot_size_authority.py backend/tests/unit/domain/test_exchange_isolation.py backend/tests/unit/domain/test_config_architecture.py tests/quant/amt/session/test_context.py -q`
