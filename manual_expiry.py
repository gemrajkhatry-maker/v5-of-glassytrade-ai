#!/usr/bin/env python
from datetime import datetime
from brokersv2.broker.entities import Exchange
from brokersv2.dhan import DhanBrokerV2

b = DhanBrokerV2.create()
exp = b.get_expiry_list("NIFTY", Exchange.NFO)
print("expiries:", exp)
assert isinstance(exp, list) and len(exp) > 0
print("PASS")
