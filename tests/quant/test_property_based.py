"""
Property-based tests using hypothesis for quant mathematical invariants.
"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'backend'))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from hypothesis import given, settings, HealthCheck
    from hypothesis import strategies as st
    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False

pytestmark = pytest.mark.skipif(not HAS_HYPOTHESIS, reason='hypothesis not installed')

if HAS_HYPOTHESIS:
    from quant.amt.profile.volume_profile import create_profile, build_snapshot
    from quant.bars import Bar

    def _make_bar(price: float, volume: int, i: int) -> Bar:
        return Bar(
            time=f'2026-08-14T{i % 24:02d}:{i % 60:02d}:00',
            open=price, high=price * 1.001, low=price * 0.999,
            close=price, volume=volume
        )

    @given(
        prices=st.lists(
            st.floats(min_value=10.0, max_value=99000.0, allow_nan=False, allow_infinity=False),
            min_size=2, max_size=30
        ),
        volumes=st.lists(st.integers(min_value=1, max_value=100_000), min_size=2, max_size=30)
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_vah_always_geq_val(prices, volumes):
        """Invariant: VAH >= VAL always."""
        n = min(len(prices), len(volumes))
        bars = [_make_bar(prices[i], volumes[i], i) for i in range(n)]
        prof = create_profile(bars)
        vp = build_snapshot(prof)
        if vp.vah and vp.val:
            assert vp.vah >= vp.val, f'VAH {vp.vah} < VAL {vp.val}'

    @given(
        prices=st.lists(
            st.floats(min_value=10.0, max_value=99000.0, allow_nan=False, allow_infinity=False),
            min_size=2, max_size=30
        ),
        volumes=st.lists(st.integers(min_value=1, max_value=100_000), min_size=2, max_size=30)
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_poc_within_price_range(prices, volumes):
        """Invariant: POC must be within the min/max price range."""
        n = min(len(prices), len(volumes))
        bars = [_make_bar(prices[i], volumes[i], i) for i in range(n)]
        prof = create_profile(bars)
        vp = build_snapshot(prof)
        if vp.poc and vp.total_volume > 0:
            min_p = min(b.low for b in bars)
            max_p = max(b.high for b in bars)
            span = max_p - min_p
            assert (min_p - span * 0.02 - 1e-4) <= vp.poc <= (max_p + span * 0.02 + 1e-4), (
                f'POC {vp.poc} outside range [{min_p}, {max_p}]'
            )
