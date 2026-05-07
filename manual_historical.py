#!/usr/bin/env python
"""Manual test for get_historical."""
from datetime import datetime
import pandas as pd

from brokersv2.broker.entities import Instrument, Exchange
from brokersv2.dhan import DhanBrokerV2

broker = DhanBrokerV2.create()
inst = Instrument(symbol="RELIANCE", exchange=Exchange.NSE)
df = broker.get_historical(inst, datetime(2024,1,1), datetime(2024,1,31))
print("DF shape:", df.shape)
print(df.head())
assert isinstance(df, pd.DataFrame)
assert not df.empty
for col in ["open","high","low","close","volume"]:
    assert col in df.columns, f"Missing {col}"
print("test_get_historical PASSED")
