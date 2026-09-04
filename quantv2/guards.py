"""Guard veto layer — pre-setup vetoes per fabio decision pipeline.

Doc anchor: docs/amt/fabio_decision_pipeline.md L93-107 (Phase A: Guards).
Translated from quant/amt/market/state_engine.py + vars_detector.py veto
semantics (v1 frozen, never imported).

Veto reasons (evaluated in this fixed priority order):
  NO_DIRECTION     — direction not in {LONG, SHORT} (doc L100).
  STALE_BOOK       — depth feed not refreshed; every order-flow input
                     (cvd_slope, obi) is unreliable, so the integrity veto
                     outranks all condition vetoes.
  DEAD_MARKET      — market_state == "DEAD" (doc L101).
  ANTI_CLIMAX      — vwap_extreme: price beyond the 2-sigma VWAP band
                     (above vwap_upper_2 for LONG, below vwap_lower_2 for
                     SHORT; the caller collapses both into one bool) (doc
                     L102-103).
  DRIVE_EXHAUSTION — drive_count >= 3 (doc L104 pins drive_number >= 3;
                     v1 additionally required drive_entry_valid == False,
                     v2 assumes the caller only counts drives without a
                     valid entry).
  CVD_CONFLICT     — CVD slope against the trade direction beyond the NSE
                     band: LONG vetoed when cvd_slope < -0.3, SHORT vetoed
                     when cvd_slope > 0.3 (doc L105-106; strict
                     inequalities — exactly ±0.3 passes). MCX uses ±0.5;
                     v2 callers on MCX must pass a pre-halved slope or
                     extend this module.

5-LEVEL CONSTRAINT: any OBI threshold in this module (|obi| >= 0.3 for
classify_market's trend gate) is defined against the 5-level depth Dhan
marketfeed actually exposes for NSE F&O (quantv2/orderflow/book.py,
DepthBook max_levels=5). OBI = (bid_qty - ask_qty) / (bid_qty + ask_qty)
over at most 5 levels per side — never a full-book OBI.
"""
from __future__ import annotations

from dataclasses import dataclass

CVD_VETO_BAND_NSE = 0.3
DRIVE_EXHAUSTION_COUNT = 3
OBI_TREND_MIN = 0.3          # 5-level-book OBI (see module docstring)
RANGE_DEAD_FRACTION = 0.0005  # window range <= 0.05% of mean price
RANGE_TREND_FRACTION = 0.002  # window range >= 0.2% of mean price


@dataclass(frozen=True)
class GuardInputs:
    """Per-evaluation guard context (fabio L93-107)."""

    cvd_slope: float = 0.0
    obi: float = 0.0
    vwap_extreme: bool = False
    drive_count: int = 0
    market_state: str = ""
    book_stale: bool = False


def run_guards(direction: str, inputs: GuardInputs) -> str | None:
    """Return the veto reason, or None when all guards pass."""
    d = str(direction).upper()
    if d not in ("LONG", "SHORT"):
        return "NO_DIRECTION"
    if inputs.book_stale:
        return "STALE_BOOK"
    if str(inputs.market_state).upper() == "DEAD":
        return "DEAD_MARKET"
    if inputs.vwap_extreme:
        return "ANTI_CLIMAX"
    if inputs.drive_count >= DRIVE_EXHAUSTION_COUNT:
        return "DRIVE_EXHAUSTION"
    if d == "LONG" and inputs.cvd_slope < -CVD_VETO_BAND_NSE:
        return "CVD_CONFLICT"
    if d == "SHORT" and inputs.cvd_slope > CVD_VETO_BAND_NSE:
        return "CVD_CONFLICT"
    return None


def classify_market(closes, book=None) -> str:
    """Classify "TRENDING" / "BALANCED" / "DEAD" via range + volume compression.

    Range compression: (max(closes) - min(closes)) / mean(|close|) over the
    supplied window. Volume compression: |obi| of `book`, which must be the
    5-level depth book (DepthBook.obi(), see 5-LEVEL CONSTRAINT above) —
    the only volume-pressure signal the NSE F&O feed provides.

      DEAD      — range compressed (<= 0.05%) AND book pressure flat
                  (|obi| < 0.3); both axes compressed.
      TRENDING  — range expanded (>= 0.2%) AND directional pressure
                  (|obi| >= 0.3).
      BALANCED  — anything else (expanded range with a flat book, or a
                  compressed range with a stacked book).
    """
    prices = [float(c) for c in closes]
    if len(prices) < 2:
        return "DEAD"
    ref = sum(abs(p) for p in prices) / len(prices)
    if ref <= 0.0:
        return "DEAD"
    rng = (max(prices) - min(prices)) / ref
    obi = 0.0
    if book is not None:
        obi_fn = getattr(book, "obi", None)
        obi = float(obi_fn()) if callable(obi_fn) else float(book)
    if rng <= RANGE_DEAD_FRACTION and abs(obi) < OBI_TREND_MIN:
        return "DEAD"
    if rng >= RANGE_TREND_FRACTION and abs(obi) >= OBI_TREND_MIN:
        return "TRENDING"
    return "BALANCED"
