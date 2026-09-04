from quantv2.guards import run_guards, GuardInputs, classify_market


class _FakeBook:
    def __init__(self, obi: float) -> None:
        self._obi = obi

    def obi(self) -> float:
        return self._obi


def _ok(**over):
    base = dict(cvd_slope=0.5, obi=0.1, vwap_extreme=False, drive_count=1,
                market_state="TRENDING", book_stale=False)
    base.update(over)
    return GuardInputs(**base)


def test_vetoes():
    ok = _ok()
    assert run_guards("LONG", ok) is None
    assert run_guards("LONG", _ok(cvd_slope=-0.31)) == "CVD_CONFLICT"
    assert run_guards("LONG", _ok(vwap_extreme=True)) == "ANTI_CLIMAX"
    assert run_guards("LONG", _ok(drive_count=3)) == "DRIVE_EXHAUSTION"
    assert run_guards("LONG", _ok(market_state="DEAD")) == "DEAD_MARKET"
    assert run_guards("LONG", _ok(book_stale=True)) == "STALE_BOOK"


def test_cvd_band_boundaries_nse():
    # fabio L105-106: strict band — exactly ±0.3 passes, beyond vetoes
    assert run_guards("LONG", _ok(cvd_slope=-0.3)) is None
    assert run_guards("SHORT", _ok(cvd_slope=0.3)) is None
    assert run_guards("SHORT", _ok(cvd_slope=0.31)) == "CVD_CONFLICT"
    # SHORT conflict is opposite-sign: a falling CVD does not block a SHORT
    assert run_guards("SHORT", _ok(cvd_slope=-0.9)) is None


def test_drive_exhaustion_boundary():
    assert run_guards("LONG", _ok(drive_count=2)) is None
    assert run_guards("SHORT", _ok(drive_count=3)) == "DRIVE_EXHAUSTION"


def test_stale_book_wins_over_other_vetoes():
    # feed-integrity veto outranks condition vetoes: stale inputs are unreliable
    assert run_guards("LONG", _ok(book_stale=True, market_state="DEAD")) == "STALE_BOOK"
    assert run_guards("LONG", _ok(book_stale=True, vwap_extreme=True, drive_count=5)) == "STALE_BOOK"


def test_no_direction():
    assert run_guards("FLAT", _ok()) == "NO_DIRECTION"


def test_classify_market():
    dead_closes = [100.0, 100.01, 100.005, 100.0]      # 0.01 range on ~100 = 0.01%
    trend_closes = [100.0, 100.5, 101.0, 101.5]        # 1.5 range on ~101 ≈ 1.5%
    assert classify_market(dead_closes, _FakeBook(0.0)) == "DEAD"
    assert classify_market(trend_closes, _FakeBook(0.6)) == "TRENDING"
    # range expansion alone is not a trend without 5-level OBI pressure
    assert classify_market(trend_closes, _FakeBook(0.05)) == "BALANCED"
    # stacked book under a compressed range is balance, not death
    assert classify_market(dead_closes, _FakeBook(0.5)) == "BALANCED"
    assert classify_market([], _FakeBook(0.0)) == "DEAD"
    assert classify_market([100.0], _FakeBook(0.9)) == "DEAD"
