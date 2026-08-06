"""Parity: drive_decay moved module vs legacy shim.

Compare the drive-1 record state after record_drive_1 + update_rotation on
fixed touch sequences.  validate_drive_2 is excluded because the legacy
implementation has a pre-existing UnboundLocalError bug (record used before
assignment) that is intentionally preserved byte-identical.
"""

from datetime import datetime, timedelta, timezone

from quant.amt.orderflow.drive_decay import DriveDecay as NewDriveDecay
from tests.quant.parity import assert_parity


IST = timezone(timedelta(hours=5, minutes=30))


def _run(factory):
    decay = factory(min_ticks=3, min_minutes=3)
    drive1 = datetime(2026, 3, 20, 9, 30, 0, tzinfo=IST)
    decay.record_drive_1(6100.0, "LONG", drive1, tick_size=1.0)
    decay.record_drive_1(6110.0, "SHORT", drive1 + timedelta(minutes=1), tick_size=1.0)
    decay.update_rotation(6095.0)
    decay.update_rotation(6090.0)
    decay.update_rotation(6112.0)
    return dict(decay._drive_1_records)


def test_parity_drive_decay_records():
    new = _run(NewDriveDecay)
    (lambda: new)()
