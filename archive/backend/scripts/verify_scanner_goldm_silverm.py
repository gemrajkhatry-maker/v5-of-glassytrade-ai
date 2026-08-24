#!/usr/bin/env python3
"""Verify scanner + dual-feed mapping + history for MCX GOLDM / SILVERM.

Uses Dhan credentials from repo .env. Sync broker init, then a dedicated
event loop only for async fetch_history (avoids nested-loop init failures).

Usage:
  cd backend && ./venv/bin/python -m scripts.verify_scanner_goldm_silverm
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
_REPO = _ROOT.parent
try:
    from dotenv import load_dotenv

    load_dotenv(_REPO / ".env", override=False)
except ImportError:
    pass

from quant.amt.session.scanner import OptionScannerService
from quant.amt.session.futures_provider import UnderlyingFuturesProvider
from app.infrastructure.adapters.dhan_adapter import DhanMarketDataAdapter


def main() -> int:
    cid = os.getenv("DHAN_CLIENT_ID", "")
    tok = os.getenv("DHAN_ACCESS_TOKEN", "")
    if not cid or not tok:
        print("SKIP: DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN not set")
        return 0

    adapter = DhanMarketDataAdapter(
        exchange="MCX",
        client_id=cid,
        access_token=tok,
    )
    adapter.ensure_initialized_sync()

    provider = UnderlyingFuturesProvider()
    scanner = OptionScannerService(adapter)
    ok = True

    loop = asyncio.new_event_loop()
    try:
        for root in ("GOLDM", "SILVERM"):
            print(f"\n=== {root} ===")
            try:
                chain = adapter.get_option_chain(root, exchange="MCX", expiry_index=0)
            except Exception as e:
                print(f"  chain ERROR: {e}")
                ok = False
                continue
            if chain is None:
                print("  chain: None")
                ok = False
                continue
            print(
                f"  chain: spot={chain.spot_price:.2f} atm={chain.atm_strike} "
                f"calls={len(chain.calls)} puts={len(chain.puts)}"
            )

            results = scanner.scan_top_n(
                n=4,
                underlyings=[root],
                exchange="MCX",
                expiry_index=0,
                strikes_around_atm=2,
                top_per_underlying=4,
            )
            print(f"  scanner picks: {len(results)}")
            for r in results[:4]:
                print(f"    - {r.symbol} score={r.score:.0f} ltp={r.ltp:.2f} oi={r.oi}")
                m = provider.get_mapping(r.symbol)
                if m:
                    print(f"      dual-feed fut: {m.underlying_symbol}")
                else:
                    print("      dual-feed fut: MISSING (instruments.json)")
                    ok = False
                try:
                    hist = loop.run_until_complete(
                        adapter.fetch_history(r.symbol, "5m", 30)
                    )
                    print(f"      history 5m: {len(hist)} candles")
                    if not hist:
                        ok = False
                except Exception as e:
                    print(f"      history ERROR: {e}")
                    ok = False
                if m:
                    try:
                        fh = loop.run_until_complete(
                            adapter.fetch_history(m.underlying_symbol, "5m", 30)
                        )
                        print(
                            f"      futures history: {len(fh)} ({m.underlying_symbol})"
                        )
                        if not fh:
                            print(
                                "      (if empty: roll underlying_symbol in "
                                "config/instruments.json)"
                            )
                    except Exception as e:
                        print(f"      futures history ERROR: {e}")
    finally:
        loop.close()

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
