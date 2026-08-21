"""OFFLINE WS fixture builder — replays the REAL serialization code path.

Feeds a synthetic engine state through quant.state.StateProjector and maps the
result with quant.ws_adapter.view_state_to_ws — the exact mapper the gameloop
WS handler emits downstream. No handwritten JSON: every frame comes from
view_state_to_ws output.

Output: runtime_audit/fixtures/ws_payloads.json (flat list of snapshot frames,
>=10 frames across multiple symbols incl. NIFTY and BANKNIFTY contracts, with
non-zero ltp/volume flowing through). Written atomically (tmp + os.replace).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

from quant.events import AmtUpdated, DepthUpdated, RiskUpdated
from quant.execution.risk import RiskState
from quant.state import StateProjector
from quant.ws_adapter import view_state_to_ws

SYMBOLS = [
    "NIFTY 27 AUG 25000 CALL",
    "BANKNIFTY 27 AUG 55000 CALL",
]
FRAMES_PER_SYMBOL = 6  # 2 symbols x 6 = 12 frames (>= 10 required)

OUT_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "ws_payloads.json"


def _build_symbol_frames(projector: StateProjector, symbol: str, n: int,
                         now_epoch: int, base_ltp: float) -> list[dict]:
    risk = RiskState(
        daily_pnl=0.0,
        consecutive_losses=0,
        halted=False,
        halt_reason="",
        risk_per_trade_pct=0.005,
        trades_today=0,
        equity=1_000_000.0,
    )
    projector.on_event(RiskUpdated(symbol=symbol, time=str(now_epoch), risk=risk))

    frames: list[dict] = []
    for i in range(n):
        ltp = base_ltp + i * 0.55 + (0.25 if i % 3 == 0 else -0.15)
        volume = 1200 + i * 137

        bar = SimpleNamespace(
            time=str(now_epoch - (n - i)),  # live epoch string, like the gateway
            open=ltp - 1.2,
            high=ltp + 0.9,
            low=ltp - 1.6,
            close=ltp,
            volume=float(volume),
            buy_volume=float(volume * 0.54),
            sell_volume=float(volume * 0.46),
            delta=float(volume * 0.08),
            oi=41_500.0 + i * 25,
            vwap=ltp - 0.35,
        )
        tick = SimpleNamespace(
            price=ltp,
            oi=41_500.0 + i * 25,
            depth={
                "bids": [[ltp - 0.05, 250], [ltp - 0.10, 480]],
                "asks": [[ltp + 0.05, 310], [ltp + 0.10, 190]],
            },
        )
        # Real per-tick path: live LTP/OI/depth + forming candle refresh.
        projector.on_quote(symbol, tick, current_bar=bar)

        amt = {
            "poc": ltp - 0.4,
            "vah": ltp + 1.8,
            "val": ltp - 2.1,
            "ibHigh": ltp + 1.1,
            "ibLow": ltp - 1.4,
            "cvd": float(volume * 0.08),
            "deltaSeries": [float(volume * 0.02 * k) for k in range(1, 4)],
        }
        projector.on_event(AmtUpdated(symbol=symbol, time=str(now_epoch + i), amt=amt))

        depth = {
            "bids": [[ltp - 0.05, 250 + i], [ltp - 0.10, 480 - i]],
            "asks": [[ltp + 0.05, 310 + i], [ltp + 0.10, 190 - i]],
        }
        projector.on_event(DepthUpdated(symbol=symbol, time=str(now_epoch + i), depth=depth))

        # The exact mapper QuantCoordinator/gameloop uses downstream.
        frames.append(view_state_to_ws(projector.snapshot(symbol)))
    return frames


def build_frames() -> list[dict]:
    projector = StateProjector()
    now_epoch = int(time.time())
    frames: list[dict] = []
    for idx, symbol in enumerate(SYMBOLS):
        frames.extend(
            _build_symbol_frames(
                projector, symbol, FRAMES_PER_SYMBOL, now_epoch,
                base_ltp=182.35 if symbol.startswith("NIFTY") else 512.80,
            )
        )
    return frames


def main() -> None:
    frames = build_frames()

    # Sanity: real-path guarantees before writing.
    assert len(frames) >= 10, f"expected >=10 frames, got {len(frames)}"
    symbols_in_frames = {f["_symbol"] for f in frames}
    assert any(s.startswith("NIFTY ") for s in symbols_in_frames), symbols_in_frames
    assert any(s.startswith("BANKNIFTY ") for s in symbols_in_frames), symbols_in_frames
    assert all(f["ltp"] and f["ltp"] > 0 for f in frames), "non-positive ltp leaked"
    assert all(f["tick"] and f["tick"]["volume"] > 0 for f in frames), "zero volume leaked"

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(frames, indent=2, allow_nan=False)
    tmp = OUT_PATH.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, OUT_PATH)  # atomic overwrite
    print(f"wrote {len(frames)} frames ({sorted(symbols_in_frames)}) -> {OUT_PATH}")
    print(f"sample keys: {sorted(frames[0])}")


if __name__ == "__main__":
    main()
