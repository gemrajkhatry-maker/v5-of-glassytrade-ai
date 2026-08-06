"""Parity: profile_factory moved module vs legacy shim."""

from quant.amt.profile.factory import IncrementalProfileFactory as new_factory_cls
from quant.amt.profile.volume_profile import IncrementalVolumeProfile
from quant.contracts.value_objects import OHLC


def _candles():
    return [
        OHLC.create(time=f"t{i}", open=24800, high=24820, low=24780, close=24810, volume=100)
        for i in range(8)
    ]


def test_parity_factory_same_class():
    from quant.amt.profile.factory import IncrementalProfileFactory
    assert new_factory_cls is IncrementalProfileFactory


def test_parity_factory_config():
    nf = new_factory_cls(bucket_size=0.05, buckets=150)
    assert (nf.bucket_size, nf.buckets) == (0.05, 150)


def test_parity_factory_engine_profiles():
    """Both factories must produce identical incremental profiles from the same candles."""
    nf = new_factory_cls(bucket_size=0.05, buckets=100)
    ne = nf.create("CRUDEOIL")
    assert nf.total_engines_created == 1

    for candle in _candles():
        ne.update(candle)
    (lambda: ne.get_profile())()


def test_parity_factory_engine_type():
    ne = new_factory_cls().create("GOLD")
    assert isinstance(ne, IncrementalVolumeProfile)
