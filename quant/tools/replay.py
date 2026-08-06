"""Golden-file replay harness for the AuctionState analysis layer.

Pure and deterministic: captures a session's (bar -> AuctionState) series to a
JSONL golden file, replays it through a fresh ``AuctionCoordinator``, and
asserts the two series agree field-for-field (floats within 1e-9; enums and
strings exact). Catches drift in any of the six detectors (volume profile,
VWAP, order flow, absorption, location, Triple-A).

No backend imports, no network, no time — same bars in, same states out.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, Sequence, Union

from quant.absorption import Absorption
from quant.auction_state import AuctionState
from quant.bars import Bar
from quant.coordinator import AuctionCoordinator
from quant.location import LocationState
from quant.order_flow import OrderFlowState
from quant.volume_profile import VolumeProfile, VolumeProfileLevel
from quant.vwap import VWAPState

FLOAT_ATOL = 1e-9

PathLike = Union[str, Path]
BarSource = Union[PathLike, Sequence[Bar]]

__all__ = [
    "FLOAT_ATOL",
    "ReplayMismatch",
    "capture",
    "replay",
    "assert_replay_equal",
    "write_golden",
    "read_golden",
    "states_to_jsonl_bytes",
]


class ReplayMismatch(AssertionError):
    """Raised when a replayed AuctionState series diverges from the golden file."""


# ---------------------------------------------------------------------------
# Serialization (stable JSONL, one (bar, state) record per line)
# ---------------------------------------------------------------------------


def _bar_to_dict(bar: Bar) -> dict:
    return asdict(bar)


def _bar_from_dict(data: dict) -> Bar:
    return Bar(**data)


def _state_to_dict(state: AuctionState) -> dict:
    vp = state.volume_profile
    vw = state.vwap
    of = state.order_flow
    loc = state.location
    ab = state.absorption
    return {
        "time": state.time,
        "close": state.close,
        "volume_profile": {
            "levels": [
                {
                    "price": lvl.price,
                    "volume": lvl.volume,
                    "buy_volume": lvl.buy_volume,
                    "sell_volume": lvl.sell_volume,
                }
                for lvl in vp.levels
            ],
            "poc": vp.poc,
            "vah": vp.vah,
            "val": vp.val,
            "step": vp.step,
            "total_volume": vp.total_volume,
        },
        "vwap": asdict(vw),
        "order_flow": {
            "delta": of.delta,
            "cvd": of.cvd,
            "cvd_slope": of.cvd_slope,
            "cvd_divergence": of.cvd_divergence,
            "aggressive_prints": [[p[0], p[1], p[2]] for p in of.aggressive_prints],
        },
        "absorption": (
            {
                "bar_index": ab.bar_index,
                "price": ab.price,
                "volume": ab.volume,
                "side": ab.side,
                "strength": ab.strength,
                "bar_age": ab.bar_age,
            }
            if ab is not None
            else None
        ),
        "location": asdict(loc),
        "triple_a_phase": state.triple_a_phase,
        "triple_a_signal": state.triple_a_signal,
    }


def _state_from_dict(data: dict) -> AuctionState:
    vp = data["volume_profile"]
    of = data["order_flow"]
    ab = data["absorption"]
    return AuctionState(
        time=data["time"],
        close=data["close"],
        volume_profile=VolumeProfile(
            levels=tuple(VolumeProfileLevel(**lvl) for lvl in vp["levels"]),
            poc=vp["poc"],
            vah=vp["vah"],
            val=vp["val"],
            step=vp["step"],
            total_volume=vp["total_volume"],
        ),
        vwap=VWAPState(**data["vwap"]),
        order_flow=OrderFlowState(
            delta=of["delta"],
            cvd=of["cvd"],
            cvd_slope=of["cvd_slope"],
            cvd_divergence=of["cvd_divergence"],
            aggressive_prints=tuple((p[0], p[1], p[2]) for p in of["aggressive_prints"]),
        ),
        absorption=(
            Absorption(
                bar_index=ab["bar_index"],
                price=ab["price"],
                volume=ab["volume"],
                side=ab["side"],
                strength=ab["strength"],
                bar_age=ab["bar_age"],
            )
            if ab is not None
            else None
        ),
        location=LocationState(**data["location"]),
        triple_a_phase=data["triple_a_phase"],
        triple_a_signal=data["triple_a_signal"],
    )


def states_to_jsonl_bytes(bars: Sequence[Bar], states: Sequence[AuctionState]) -> bytes:
    """Serialize a (bars, states) pair to stable JSONL bytes (one line each)."""
    lines = [
        json.dumps(
            {"bar": _bar_to_dict(b), "state": _state_to_dict(s)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        for b, s in zip(bars, states)
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_golden(path: PathLike, bars: Sequence[Bar], states: Sequence[AuctionState]) -> None:
    """Persist a (bar -> AuctionState) golden file. Creates parent dirs."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(states_to_jsonl_bytes(bars, states))


def read_golden(path: PathLike) -> tuple[list[Bar], list[AuctionState]]:
    """Load a golden file back into Bars and AuctionState objects."""
    bars: list[Bar] = []
    states: list[AuctionState] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            bars.append(_bar_from_dict(record["bar"]))
            states.append(_state_from_dict(record["state"]))
    return bars, states


def _read_records(path: PathLike) -> list[dict]:
    """Raw (bar, state) record dicts — used for the strict field-level compare."""
    records: list[dict] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def capture(
    bars: Sequence[Bar],
    analyzer: Any | None = None,
    golden_path: PathLike | None = None,
) -> list[AuctionState]:
    """Feed ``bars`` through ``analyzer`` and return the AuctionState series.

    When ``golden_path`` is given, a JSONL golden file of (bar -> AuctionState)
    is written there. A fresh ``AuctionCoordinator`` is used when ``analyzer``
    is None, so the capture is deterministic.
    """
    if analyzer is None:
        analyzer = AuctionCoordinator()
    states = [analyzer.on_bar_close(b) for b in bars]
    if golden_path is not None:
        write_golden(golden_path, bars, states)
    return states


def replay(source: BarSource, analyzer: Any | None = None) -> list[AuctionState]:
    """Replay a session and return the resulting AuctionState series.

    ``source`` is a golden JSONL path or a sequence of Bars. A fresh
    ``AuctionCoordinator`` is used unless ``analyzer`` is supplied, so two
    replays of the same source are byte-identical.
    """
    if analyzer is None:
        analyzer = AuctionCoordinator()
    bars = _bars_from(source)
    return [analyzer.on_bar_close(b) for b in bars]


def assert_replay_equal(golden_path: PathLike, analyzer: Any | None = None, *, bars: Sequence[Bar] | None = None) -> None:
    """Replay a golden session and assert the states match field-for-field.

    Raises ``ReplayMismatch`` on ANY divergence (floats within 1e-9; enums and
    strings exact). This is the §5.2 drift gate: a fresh analyzer re-feeds the
    recorded bars and the output must reproduce the golden states byte-for-byte.

    ``bars`` overrides the bar stream fed to the analyzer — pass a mutated
    session to prove the drift detector fires when input diverges from golden.
    """
    if analyzer is None:
        analyzer = AuctionCoordinator()
    expected = [rec["state"] for rec in _read_records(golden_path)]
    if bars is not None:
        actual = [_state_to_dict(s) for s in [analyzer.on_bar_close(b) for b in bars]]
    else:
        actual = [_state_to_dict(s) for s in replay(golden_path, analyzer)]
    _compare_records(expected, actual)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _bars_from(source: BarSource) -> list[Bar]:
    if isinstance(source, (str, Path)):
        return read_golden(source)[0]
    return list(source)


def _compare_records(expected: list[dict], actual: list[dict]) -> None:
    if len(expected) != len(actual):
        raise ReplayMismatch(
            f"bar count differs: golden={len(expected)} replay={len(actual)}"
        )
    for i, (exp, act) in enumerate(zip(expected, actual)):
        _compare(exp, act, f"record[{i}]")


def _compare(exp: Any, act: Any, path: str) -> None:
    if isinstance(exp, dict):
        if not isinstance(act, dict):
            raise ReplayMismatch(f"{path}: replay has {type(act).__name__}, golden has dict")
        for key in exp:
            if key not in act:
                raise ReplayMismatch(f"{path}.{key}: missing in replay")
            _compare(exp[key], act[key], f"{path}.{key}")
        return
    if isinstance(exp, (list, tuple)):
        if not isinstance(act, (list, tuple)) or len(act) != len(exp):
            raise ReplayMismatch(f"{path}: sequence length differs (golden={len(exp)} replay={len(act)})")
        for i, (e, a) in enumerate(zip(exp, act)):
            _compare(e, a, f"{path}[{i}]")
        return
    if isinstance(exp, float) and isinstance(act, (int, float)):
        if not math.isclose(exp, act, rel_tol=0.0, abs_tol=FLOAT_ATOL):
            raise ReplayMismatch(
                f"{path}: {exp!r} != {act!r} (|Δ|={abs(exp - act):.3e})"
            )
        return
    if isinstance(exp, bool) != isinstance(act, bool):
        raise ReplayMismatch(f"{path}: bool type mismatch {exp!r} != {act!r}")
    if exp != act:
        raise ReplayMismatch(f"{path}: {exp!r} != {act!r}")
