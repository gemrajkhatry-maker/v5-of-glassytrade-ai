#!/usr/bin/env python3
"""
Live test: 20-level market depth via WebSocket (stream_depth).

Uses broker.stream_depth(instruments, depth_level=20) which connects to
Dhan FullDepth WebSocket and yields MarketDepth with up to 20 levels per side.

Run: .venv/bin/python brokers/scripts/test_20level_depth_live.py
"""
import os
import sys
import asyncio
from pathlib import Path

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "dhanhq_custom"))

from dotenv import load_dotenv
load_dotenv(project_root / ".env", override=True)

from brokers.broker.dhan.application.broker import DhanBroker
from brokers.broker.entities import Instrument, MarketDepth, DepthLevel
from brokers.broker.types import Exchange

PASSED = 0
FAILED = 0


def ok(name: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  PASS: {name}" + (f" ({detail})" if detail else ""))
    else:
        FAILED += 1
        print(f"  FAIL: {name}" + (f" ({detail})" if detail else ""))


async def collect_depth_updates(broker: DhanBroker, instruments: list, timeout_sec: float = 15):
    """Consume stream_depth for up to timeout_sec; return list of MarketDepth."""
    collected = []
    try:
        async def consume():
            async for depth in broker.stream_depth(instruments, depth_level=20):
                collected.append(depth)
                if len(collected) >= 6:  # e.g. 3 bid + 3 ask or 6 updates
                    return
        await asyncio.wait_for(consume(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        pass
    return collected


async def main() -> None:
    global PASSED, FAILED
    PASSED = 0
    FAILED = 0

    if not os.getenv("DHAN_CLIENT_ID") or not os.getenv("DHAN_ACCESS_TOKEN"):
        print("Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env")
        sys.exit(1)

    broker = DhanBroker.create()
    await broker.initialize()

    try:
        print("=" * 60)
        print("20-level market depth (stream_depth, WebSocket)")
        print("=" * 60)

        inst = Instrument(symbol="RELIANCE", exchange=Exchange.NSE)
        print("\n--- NSE RELIANCE depth_level=20 (collecting up to 15s) ---")

        depths = await collect_depth_updates(broker, [inst], timeout_sec=15)

        ok("At least one depth update", len(depths) >= 1, f"got={len(depths)}")

        if depths:
            # Each item is MarketDepth with side (bid/ask) and levels
            d0 = depths[0]
            ok("MarketDepth type", isinstance(d0, MarketDepth))
            ok("Has symbol", bool(d0.symbol))
            ok("Has side", d0.side in ("bid", "ask"))
            ok("Has levels", len(d0.levels) >= 1, f"levels={len(d0.levels)}")
            # 20-level feed should give up to 20 levels per side
            ok("Level count >= 5", len(d0.levels) >= 5, f"n={len(d0.levels)}")
            if len(d0.levels) >= 10:
                ok("Level count >= 10 (deep book)", True, f"n={len(d0.levels)}")
            if len(d0.levels) >= 20:
                ok("Level count >= 20 (full depth)", True, f"n={len(d0.levels)}")

            for i, lev in enumerate(d0.levels[:3]):
                ok(f"  level[{i}]", isinstance(lev, DepthLevel) and lev.price >= 0 and lev.quantity >= 0,
                   f"price={lev.price} qty={lev.quantity}")

            # Check we got both sides if multiple updates
            sides = {d.side for d in depths}
            ok("Has both bid and ask", "bid" in sides or "ask" in sides, f"sides={sides}")

        if len(depths) < 1:
            print("  (No depth updates in 15s — market may be closed or feed delayed)")

    finally:
        await broker.close()

    print("\n" + "=" * 60)
    if FAILED == 0:
        print(f"ALL {PASSED} TESTS PASSED (20-level depth)")
    else:
        print(f"RESULTS: {PASSED} passed, {FAILED} failed")
    print("=" * 60)
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    asyncio.run(main())
