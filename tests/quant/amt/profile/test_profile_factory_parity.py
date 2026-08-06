"""Parity: profile_factory moved module vs legacy shim."""

from quant.amt.profile.factory import IncrementalProfileFactory as new_factory_cls
from app.domain.fabio_ai.services.profile_factory import IncrementalProfileFactory as legacy_factory_cls
from quant.amt.profile.volume_profile import IncrementalVolumeProfile
from quant.contracts.value_objects import OHLC
from tests.quant.parity import assert_parity


def _candles():
    return [
        OHLC.create(time=f"t{i}", open=24800, high=24820, low=24780, close=24810, volume=100)
        for i in range(8)
    ]


def test_parity_factory_same_class():
    assert new_factory_cls is legacy_factory_cls


def test_parity_factory_config():
    lf = legacy_factory_cls(bucket_size=0.05, buckets=150)
    nf = new_factory_cls(bucket_size=0.05, buckets=150)
    assert (lf.bucket_size, lf.buckets) == (nf.bucket_size, nf.buckets) == (0.05, 150)


def test_parity_factory_engine_profiles():
    """Both factories must produce identical incremental profiles from the same candles."""
    lf = legacy_factory_cls(bucket_size=0.05, buckets=100)
    nf = new_factory_cls(bucket_size=0.05, buckets=100)
    le = lf.create("CRUDEOIL")
    ne = nf.create("CRUDEOIL")
    assert lf.total_engines_created == nf.total_engines_created == 1

    for candle in _candles():
        le.update(candle)
        ne.update(candle)
    assert_parity(lambda: le.get_profile(), lambda: ne.get_profile())


def test_parity_factory_engine_type():
    le = legacy_factory_cls().create("GOLD")
    ne = new_factory_cls().create("GOLD")
    assert isinstance(le, IncrementalVolumeProfile)
    assert isinstance(ne, IncrementalVolumeProfile)
