from app.application.range_bar_builder import RangeBarBuilder


def _open_first(builder, price):
    """Seed the very first (in-progress) bar."""
    builder.on_tick(ltp=price, timestamp="t0", buy_vol=0.0, sell_vol=0.0)


def _close(builder, price, buy_vol=0.0):
    """Drive the forming bar to `price` so the range bar closes.

    Volume is attributed to the closing tick, matching the existing
    test_range_bar_builder.py convention.
    """
    bar = builder.on_tick(ltp=price, timestamp="t", buy_vol=buy_vol, sell_vol=0.0)
    assert bar is not None, f"expected a closed bar at {price}"
    return bar


def _wide_quiet_bars(builder):
    """Six wide, low-volume bars that lift the average range / suppress avg volume.

    Prices walk 100 -> 118 in 3.0 steps; each bar closes at its high.
    """
    for i in range(6):
        _close(builder, 103.0 + 3.0 * i, buy_vol=50.0)
        builder.detect_triple_a()


def _absorption_accumulation(builder):
    """Absorption + two accumulation bars stacked on the same [118, 119] range."""
    _close(builder, 119.0, buy_vol=400.0)  # absorption (tight, high volume)
    assert builder.detect_triple_a().phase == "ABSORPTION"

    _close(builder, 118.0, buy_vol=300.0)  # accumulation bar 1 (retrace into POC)
    assert builder.detect_triple_a().phase == "ABSORPTION"
    assert builder._accumulation_count == 1

    _close(builder, 119.0, buy_vol=300.0)  # accumulation bar 2
    assert builder.detect_triple_a().phase == "ACCUMULATION"
    assert builder._accumulation_count == 2


def _build_breakout_builder():
    b = RangeBarBuilder(range_size=1.0, tick_size=0.1)
    _open_first(b, 100.0)
    _wide_quiet_bars(b)
    _absorption_accumulation(b)
    return b


def test_phase_transitions_waiting_to_aggression():
    b = _build_breakout_builder()

    # Aggression: wide, high-volume bar that closes beyond VWAP + 1 sigma (LONG).
    _close(b, 132.0, buy_vol=800.0)

    result = b.detect_triple_a()
    assert result.phase == "AGGRESSION"
    assert result.detected is True
    assert result.direction == "LONG"
    assert b._triple_a_phase == "AGGRESSION"
    assert b._aggression_bar_index == 9

    # The phases were observed in order: WAITING("") -> ABSORPTION -> ACCUMULATION
    # -> AGGRESSION (asserted inside the helpers above).


def test_no_aggression_without_two_accumulation_bars():
    b = RangeBarBuilder(range_size=1.0, tick_size=0.1)
    _open_first(b, 100.0)
    _wide_quiet_bars(b)
    _close(b, 119.0, buy_vol=400.0)
    assert b.detect_triple_a().phase == "ABSORPTION"
    _close(b, 118.0, buy_vol=300.0)  # only ONE accumulation bar so far
    assert b.detect_triple_a().phase == "ABSORPTION"
    assert b._accumulation_count == 1

    # Breakout immediately after a single accumulation bar must NOT fire.
    _close(b, 132.0, buy_vol=800.0)
    result = b.detect_triple_a()
    assert result.phase != "AGGRESSION"
    assert result.detected is False
    assert b._triple_a_phase == "ABSORPTION"
    assert b._accumulation_count == 0  # breakout bar is not consolidating


def test_resets_to_waiting_after_aggression():
    b = _build_breakout_builder()
    _close(b, 132.0, buy_vol=800.0)
    assert b.detect_triple_a().phase == "AGGRESSION"
    assert b._triple_a_phase == "AGGRESSION"

    # A fresh quiet bar after the signal resets the machine to WAITING.
    _close(b, 131.0, buy_vol=50.0)
    assert b.detect_triple_a().phase == ""
    assert b._triple_a_phase == ""
    assert b._accumulation_count == 0

    # A new absorption can then start a fresh cycle.
    _close(b, 132.0, buy_vol=400.0)
    assert b.detect_triple_a().phase == "ABSORPTION"
    assert b._triple_a_phase == "ABSORPTION"
