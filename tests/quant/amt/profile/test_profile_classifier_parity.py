"""Parity: profile_classifier moved module vs legacy shim."""

import math

from quant.amt.profile.classifier import (
    ProfileShape,
    classify_shape as new_classify_shape,
    POCMigrationTracker as new_tracker,
)
from quant.contracts.value_objects import VolumeProfileLevel


def _p_shape():
    return [VolumeProfileLevel(price=100 + i, volume=(i + 1) ** 2) for i in range(20)]


def _b_shape():
    return [VolumeProfileLevel(price=100 + i, volume=(20 - i) ** 2) for i in range(20)]


def _d_shape():
    return [
        VolumeProfileLevel(price=100 + i, volume=math.exp(-0.5 * ((i - 10) / 3) ** 2) * 100)
        for i in range(20)
    ]


CASES = [_p_shape(), _b_shape(), _d_shape(), [], [VolumeProfileLevel(price=1.0, volume=1)]]


def test_parity_classify_shape():
    for profile in CASES:
        new_classify_shape(profile)


def test_parity_classify_shape_letters():
    assert new_classify_shape(_p_shape()).shape == "P"
    assert new_classify_shape(_b_shape()).shape == "b"
    assert new_classify_shape(_d_shape()).shape == "D"


def test_parity_return_type():
    result = new_classify_shape(_d_shape())
    assert isinstance(result, ProfileShape)


def test_parity_poc_migration_state():
    nt = new_tracker()
    for i in range(10):
        nt.update(100 + i * 2)
    assert nt.state is not None


def test_parity_poc_migration_stable():
    nt = new_tracker()
    for _ in range(5):
        nt.update(100.0)
    assert nt.state is not None
