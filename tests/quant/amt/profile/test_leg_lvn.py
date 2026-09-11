from quant.amt.profile.leg_lvn import resolve_leg_lvn


def test_resolve_leg_lvn_prefers_nearest_positive_plural_level():
    result = resolve_leg_lvn({"legLvns": [-1.0, 99.0, 101.5]}, 101.0)
    assert result.available is True
    assert result.level == 101.5
    assert result.source == "legLvns"


def test_resolve_leg_lvn_uses_legacy_fallback():
    result = resolve_leg_lvn({"legLvn": 99.5}, 100.0)
    assert result.available is True
    assert result.level == 99.5
    assert result.source == "legLvn"


def test_resolve_leg_lvn_reports_unavailable_without_a_level():
    result = resolve_leg_lvn({}, 100.0)
    assert result.available is False
    assert result.level == 0.0
    assert result.reason == "NO_LVN"
