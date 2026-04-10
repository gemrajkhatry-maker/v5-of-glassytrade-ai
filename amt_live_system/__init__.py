"""AMT Live Trading System — Production-Grade Implementation.

This module implements the Fabio Valentini Auction Market Theory (AMT) strategy
for Indian options trading (NIFTY / BANKNIFTY / CRUDE OIL contracts).

System Architecture:
===================

┌─────────────────────────────────────────────────────────────────────────┐
│                          LIVE TRADING SYSTEM                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────────┐     ┌──────────────────┐     ┌────────────────┐  │
│  │   DATA LAYER     │────▶│  FEATURE ENGINE  │────▶│   STRATEGY     │  │
│  │                  │     │                  │     │    ENGINE      │  │
│  │ • Tick Ingest    │     │ • AMT Features   │     │                │  │
│  │ • Candle Build   │     │ • Order Flow     │     │ • State Machine│  │
│  │ • Volume Profile │     │ • Options Metrics│     │ • Signal Gen   │  │
│  │ • VWAP/POC       │     │ • Greeks         │     │ • Entry/Exit   │  │
│  └──────────────────┘     └──────────────────┘     └───────┬────────┘  │
│                                                            │           │
│  ┌──────────────────┐     ┌──────────────────┐     ┌───────▼────────┐  │
│  │   RISK ENGINE    │◀───▶│ EXECUTION ENGINE │◀────│  GATE ENGINE   │  │
│  │                  │     │                  │     │                │  │
│  │ • Position Size  │     │ • Dhan Broker    │     │ • 12-Gate Pipe │  │
│  │ • Stop Loss      │     │ • Order Types    │     │ • Validation   │  │
│  │ • Daily Limits   │     │ • Slippage Mgmt  │     │ • Quorum Logic │  │
│  │ • Circuit Break  │     │ • Retry Logic    │     │ • Rejection    │  │
│  └──────────────────┘     └──────────────────┘     └────────────────┘  │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    STATE MANAGEMENT                               │  │
│  │  • Per-symbol state    • Crash recovery    • Trade lifecycle     │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘

"""

from __future__ import annotations

# Package version
__version__ = "1.0.0"
