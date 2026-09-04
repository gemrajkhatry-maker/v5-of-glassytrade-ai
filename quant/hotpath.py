"""Hot-path trace — opt-in observability for the live decision loop.

Records the five phases of the production hot path as they cross the REAL
code (not re-derived in a harness):

    tick         — a feed tick was consumed by the engine loop (runtime._run_inner)
    bar_closed   — a BarClosed event was emitted (aggregator boundary)
    decision     — a DecisionProduced event was emitted (gates 1-4 outcome)
    fill         — PositionOpened / PositionClosed / PositionReduced events
    snapshot     — a coordinator snapshot was composed for the WS transport

This is the "does the diagram match reality" instrument: if a phase is
missing or the ordering is wrong, the flow actually taken by the code differs
from the documented tick → bar → gate → fill → snapshot path.

Enable via environment (read once at import):

    GLASSYTRADE_HOTPATH_TRACE=1                keep an in-memory ring buffer
    GLASSYTRADE_HOTPATH_TRACE_FILE=/path.jsonl also append every record as JSONL

or programmatically (tests/harnesses):

    from quant.hotpath import get_hotpath_tracer
    t = get_hotpath_tracer()
    t.enable(clear=True)
    ... run the engine ...
    t.disable()
    for r in t.records("SYMBOL"):
        print(r)

When disabled, call sites short-circuit on a single boolean — no allocation
on the hot path. Stdlib only: no quant imports, so this module can never
participate in an import cycle.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

_ENV_FLAG = "GLASSYTRADE_HOTPATH_TRACE"
_ENV_FILE = "GLASSYTRADE_HOTPATH_TRACE_FILE"
_DEFAULT_RING = 8_192
# JSONL write buffering: tick records accumulate in memory and flush once the
# buffer reaches this size; non-tick phases flush immediately so a crash loses
# at most the pending tick burst.
_JSONL_FLUSH_BATCH = 128

# Phases in canonical order (matches the documented hot path).
PHASES: Tuple[str, ...] = ("tick", "bar_closed", "decision", "fill", "snapshot")


@dataclass(frozen=True)
class TraceRecord:
    """One hot-path phase crossing. ``seq`` is the process-wide order."""

    symbol: str
    phase: str
    seq: int
    epoch: float
    fields: Dict[str, Any] = field(default_factory=dict)


class HotPathTracer:
    """Thread-safe ring-buffer trace with optional JSONL append."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: Deque[TraceRecord] = deque(maxlen=_DEFAULT_RING)
        self._seq = 0
        self._dropped = 0  # records evicted by the ring cap (overflow visibility)
        self._enabled = self._env_enabled()
        self._file_path: Optional[str] = os.environ.get(_ENV_FILE) or None
        self._jsonl: Any = None
        self._pending_jsonl = 0
        if self._file_path and self._enabled:
            self._open_jsonl()
            atexit.register(self.close)

    @staticmethod
    def _env_enabled() -> bool:
        return os.environ.get(_ENV_FLAG, "").strip().lower() in ("1", "true", "yes", "on")

    def _open_jsonl(self) -> None:
        if self._file_path:
            self._jsonl = open(self._file_path, "a", encoding="utf-8")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self, *, clear: bool = False) -> None:
        with self._lock:
            self._enabled = True
            if clear:
                self._records.clear()
            if self._file_path and self._jsonl is None:
                self._open_jsonl()

    def disable(self) -> None:
        with self._lock:
            self._enabled = False

    def reset(self) -> None:
        with self._lock:
            self._records.clear()
            self._seq = 0
            self._dropped = 0

    def close(self) -> None:
        with self._lock:
            if self._jsonl is not None:
                try:
                    self._jsonl.flush()
                finally:
                    self._jsonl.close()
                    self._jsonl = None

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def emit(self, symbol: str, phase: str, **fields: Any) -> None:
        """Record one phase crossing. Never raises: a trace-internal failure
        (e.g. JSONL write error) must not stop trading."""
        if not self._enabled:
            return
        if phase not in PHASES:
            phase = f"phase:{phase}"  # keep unknown phases visible, never silent
        with self._lock:
            if len(self._records) == self._records.maxlen:
                self._dropped += 1  # ring cap reached — count the eviction
            self._seq += 1
            rec = TraceRecord(
                symbol=symbol, phase=phase, seq=self._seq,
                epoch=time.time(), fields=dict(fields),
            )
            self._records.append(rec)
            try:
                self._write_jsonl(rec)
            except Exception:
                logger.exception(
                    "hot-path trace: JSONL write failed for %s %s (seq=%d) — "
                    "trading continues", symbol, phase, self._seq,
                )

    def try_emit(self, symbol: str, phase: str, **fields: Any) -> None:
        """Call sites on non-bus paths (tick ingress, snapshot egress) use this:
        a trace bug must never propagate into the engine loop or WS push."""
        try:
            self.emit(symbol, phase, **fields)
        except Exception:
            logger.exception(
                "hot-path trace: emit failed for %s %s — trading continues",
                symbol, phase,
            )

    @property
    def dropped(self) -> int:
        """Records evicted by the ring cap — 0 until the buffer overflows."""
        with self._lock:
            return self._dropped

    def _write_jsonl(self, rec: TraceRecord) -> None:
        if self._jsonl is None:
            return
        line = (
            json.dumps({
                "symbol": rec.symbol, "phase": rec.phase, "seq": rec.seq,
                "epoch": rec.epoch, **rec.fields,
            }, default=str)
            + "\n"
        )
        self._jsonl.write(line)
        if rec.phase == "tick":
            self._pending_jsonl += 1
            if self._pending_jsonl >= _JSONL_FLUSH_BATCH:
                self._jsonl.flush()
                self._pending_jsonl = 0
        else:
            self._jsonl.flush()
            self._pending_jsonl = 0

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def records(
        self,
        symbol: Optional[str] = None,
        phases: Optional[Sequence[str]] = None,
    ) -> List[TraceRecord]:
        want_phases = set(phases) if phases is not None else None
        with self._lock:
            out = [
                r for r in self._records
                if (symbol is None or r.symbol == symbol)
                and (want_phases is None or r.phase in want_phases)
            ]
        return sorted(out, key=lambda r: r.seq)

    def counts(self, symbol: Optional[str] = None) -> Dict[str, int]:
        """Per-phase record counts (0 for phases never seen)."""
        c: Dict[str, int] = {p: 0 for p in PHASES}
        for r in self.records(symbol):
            if r.phase in c:
                c[r.phase] += 1
        return c

    def dump(self, path: str) -> int:
        """Write the current ring buffer to ``path`` as JSONL. Returns count."""
        with open(path, "w", encoding="utf-8") as f:
            for r in self.records():
                f.write(json.dumps({
                    "symbol": r.symbol, "phase": r.phase, "seq": r.seq,
                    "epoch": r.epoch, **r.fields,
                }, default=str) + "\n")
        return len(self._records)


# ----------------------------------------------------------------------
# Module singleton + render helpers
# ----------------------------------------------------------------------

_TRACER: Optional[HotPathTracer] = None


def get_hotpath_tracer() -> HotPathTracer:
    global _TRACER
    if _TRACER is None:
        _TRACER = HotPathTracer()
    return _TRACER


def _detail(rec: TraceRecord, width: int = 88) -> str:
    parts = []
    for k, v in rec.fields.items():
        if k == "gates" and isinstance(v, list):
            bits = []
            for g in v:
                mark = "PASS" if g.get("passed") else "BLOCK"
                bits.append(f"{g.get('gate')}:{g.get('name')}={mark}")
            parts.append("gates=[" + " ".join(bits) + "]")
        elif k == "signal" and isinstance(v, dict) and v:
            parts.append(
                "signal=" + " ".join(f"{sk}={sv}" for sk, sv in v.items())
            )
        else:
            parts.append(f"{k}={v}")
    line = " ".join(parts)
    return line if len(line) <= width else line[: width - 1] + "…"


def render_records(
    records: Sequence[TraceRecord],
    *,
    include_ticks: bool = False,
    tick_burst: int = 3,
    max_rows: int = 120,
) -> str:
    """Render records as a compact terminal table (first tick of each burst)."""
    t0 = records[0].epoch if records else time.time()
    rows = []
    burst = 0
    for r in records:
        if r.phase == "tick" and not include_ticks:
            burst += 1
            if burst > tick_burst:
                continue
        rel = r.epoch - t0
        rows.append(
            f"{r.seq:>6} {rel:>9.3f}s  {r.phase:<12} {r.symbol:<20} {_detail(r)}"
        )
        if len(rows) >= max_rows:
            rows.append("… (truncated)")
            break
    if not rows:
        return "(no hot-path records)"
    return "\n".join(rows)


# ----------------------------------------------------------------------
# Passive EventBus subscriber (B7) — quant/hotpath.py stays free of
# module-level ``quant`` imports so importing this module can never form a
# cycle; the event types are imported lazily inside ``subscribe``.
#
# The engine publishes typed events and knows nothing about the tracer:
# bar/decision/fill phases are derived HERE from the events it emits. The
# subscriber runs at priority +200 — before the journal (-100) — so a trace
# failure is isolated by the bus and never poisons later handlers.
# ----------------------------------------------------------------------


class HotPathSubscriber:
    """Maps domain events onto hot-path trace phases, passively."""

    def __init__(self, tracer: "HotPathTracer | None" = None) -> None:
        self._tracer = tracer if tracer is not None else get_hotpath_tracer()

    @classmethod
    def subscribe(cls, bus, tracer: "HotPathTracer | None" = None) -> "HotPathSubscriber":
        """Subscribe to every event type that defines a hot-path phase."""
        from quant.events import (
            BarClosed,
            DecisionProduced,
            PositionClosed,
            PositionOpened,
            PositionReduced,
        )

        subscriber = cls(tracer)
        for evt_type in (
            BarClosed,
            DecisionProduced,
            PositionOpened,
            PositionClosed,
            PositionReduced,
        ):
            bus.subscribe(evt_type, subscriber.on_event, priority=+200)
        return subscriber

    def on_event(self, event) -> None:
        """Record the phase crossing carried by ``event`` (no-op when off)."""
        if not self._tracer.enabled:
            return
        from quant.events import (
            BarClosed,
            DecisionProduced,
            PositionClosed,
            PositionOpened,
            PositionReduced,
        )

        corr = getattr(event, "correlation_id", "") or ""
        if isinstance(event, BarClosed):
            b = event.bar
            self._tracer.try_emit(
                event.symbol, "bar_closed",
                time=event.time,
                correlation_id=corr,
                open=getattr(b, "open", None),
                high=getattr(b, "high", None),
                low=getattr(b, "low", None),
                close=getattr(b, "close", None),
                volume=getattr(b, "volume", None),
            )
            return
        if isinstance(event, DecisionProduced):
            d = event.decision
            signal = None
            s = getattr(d, "signal", None)
            if s is not None:
                signal = {
                    "type": s.type,
                    "entry": getattr(s, "entry", None),
                    "sl": getattr(s, "sl", None),
                    "tp": getattr(s, "tp", None),
                    "rr": getattr(s, "rr", None),
                }
            self._tracer.try_emit(
                event.symbol, "decision",
                time=event.time,
                correlation_id=corr,
                approved=bool(getattr(d, "approved", False)),
                reason=getattr(d, "reason", ""),
                model_label=getattr(d, "model_label", ""),
                gates=[
                    {"gate": g.gate, "name": g.name, "passed": g.passed,
                     "reason": g.reason}
                    for g in (getattr(d, "gate_results", None) or ())
                ],
                signal=signal,
            )
            return
        if isinstance(event, PositionOpened):
            p = event.position
            o = getattr(p, "order", None)
            sig = getattr(o, "signal", None)
            size = float(getattr(p, "size", 0.0) or 0.0)
            self._tracer.try_emit(
                event.symbol, "fill",
                time=event.time,
                correlation_id=corr,
                kind="open",
                side="LONG" if size > 0 else "SHORT",
                qty=getattr(o, "quantity", None) or abs(size),
                entry=getattr(p, "open_price", None),
                sl=getattr(sig, "sl", None) if sig is not None else None,
                tp=getattr(sig, "tp", None) if sig is not None else None,
                model_label=getattr(sig, "model_label", "") if sig is not None else "",
                pyramid=bool(getattr(p, "is_pyramid", False)),
            )
            return
        if isinstance(event, PositionClosed):
            f = event.fill
            p = getattr(f, "position", None)
            self._tracer.try_emit(
                event.symbol, "fill",
                time=event.time,
                correlation_id=corr,
                kind="close",
                side="LONG" if float(getattr(p, "size", 0.0) or 0.0) > 0 else "SHORT",
                qty=abs(float(getattr(p, "size", 0.0) or 0.0)),
                price=getattr(f, "close_price", None),
                reason=getattr(f, "reason", ""),
                pnl=getattr(f, "pnl", None),
            )
            return
        if isinstance(event, PositionReduced):
            f = event.fill
            rem = event.remaining
            self._tracer.try_emit(
                event.symbol, "fill",
                time=event.time,
                correlation_id=corr,
                kind="partial",
                price=getattr(f, "close_price", None),
                reason=getattr(f, "reason", ""),
                remaining_size=float(getattr(rem, "size", 0.0) or 0.0),
            )
