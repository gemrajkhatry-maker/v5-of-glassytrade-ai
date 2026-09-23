"""Test NPOC integration into the decision pipeline.

Re-audit finding: this file's original assertions only checked
``decision.signal is not None`` — true regardless of whether NPOC data was
consulted anywhere, so it proved nothing about NPOC wiring (false
confidence). Verified where NPOC fields actually flow: ``gates_edge.py``
never references ``npoc_above``/``npoc_below`` at all (confirmed by direct
search) — NPOC is not, and was never meant to be, an entry gate. The real
integration point is ``SignalBuilder._structural_tp``, which uses NPOC as
the highest-priority take-profit target (Fabio: target the nearest unfilled
naked POC). These tests now assert on that real behavior instead.
"""
from quant.decision.context import DecisionContext
from quant.decision.signal_builder import SignalBuilder


def _make_bar(time_str: str, o: float, h: float, lo: float, c: float, vol: float = 1000.0, delta: float = 200.0) -> object:
    from quant.bars import Bar
    return Bar(
        time=time_str,
        open=o,
        high=h,
        low=lo,
        close=c,
        volume=vol,
        buy_volume=vol * 0.6 if delta > 0 else vol * 0.4,
        sell_volume=vol * 0.4 if delta > 0 else vol * 0.6,
        delta=delta,
    )


def test_structural_tp_targets_npoc_above_for_long():
    """LONG: with a qualifying NPOC above entry, it must win as the TP —
    NPOC is the highest-priority structural target (ahead of prior POC and
    the opposite VA edge). Spec §11: shielded 2 ticks inside (toward entry)."""
    entry, sl = 24500.0, 24450.0  # risk = 50
    ctx = DecisionContext(
        npoc_above=24650.0,   # rr = 150/50 = 3.0 >= min_rr
        prior_poc=24700.0,    # farther than NPOC — must lose priority
        vah=24800.0,
    )
    tp = SignalBuilder._structural_tp(ctx, entry, sl, "LONG", fallback_tp=24575.0)
    # Shielded 2 ticks (0.10) inside NPOC toward entry: 24650.0 - 0.10 = 24649.9
    assert tp == 24649.9, "NPOC above must be selected over prior_poc/vah for LONG"


def test_structural_tp_targets_npoc_below_for_short():
    """SHORT: symmetric case — NPOC below entry wins as the TP.
    Spec §11: shielded 2 ticks inside (toward entry)."""
    entry, sl = 24500.0, 24550.0  # risk = 50
    ctx = DecisionContext(
        npoc_below=24350.0,   # rr = 150/50 = 3.0 >= min_rr
        prior_poc=24300.0,    # farther than NPOC — must lose priority
        val=24200.0,
    )
    tp = SignalBuilder._structural_tp(ctx, entry, sl, "SHORT", fallback_tp=24425.0)
    # Shielded 2 ticks (0.10) inside NPOC toward entry: 24350.0 + 0.10 = 24350.1
    assert tp == 24350.1, "NPOC below must be selected over prior_poc/val for SHORT"


def test_structural_tp_skips_npoc_that_fails_min_rr():
    """A too-close NPOC that can't meet min_rr must be skipped in favor of
    the next qualifying structural target (prior POC here) — NPOC is a
    priority preference, not an unconditional override."""
    entry, sl = 24500.0, 24450.0  # risk = 50, min_rr default 1.5 -> needs reward >= 75
    ctx = DecisionContext(
        npoc_above=24510.0,   # reward=10, rr=0.2 -> fails min_rr
        prior_poc=24700.0,    # reward=200, rr=4.0 -> qualifies
    )
    tp = SignalBuilder._structural_tp(ctx, entry, sl, "LONG", fallback_tp=24575.0)
    # Shielded 2 ticks (0.10) inside prior_poc toward entry: 24700.0 - 0.10 = 24699.9
    assert tp == 24699.9


def test_gates_edge_never_references_npoc():
    """NPOC is intentionally NOT an entry gate (Fabio's Triple-A edge is
    absorption -> accumulation -> aggression only). This pins that design
    decision so a future change can't silently start gating entries on
    NPOC proximity without a deliberate, reviewed change to gates_edge.py."""
    import inspect

    from quant.decision import gates_edge

    source = inspect.getsource(gates_edge)
    assert "npoc" not in source.lower()
