import sys
import time

def mark(label):
    print(f"[{time.time():.3f}] {label}")

mark("START")
try:
    mark("importing ports...")
    import brokersv2.broker.ports as ports
    mark("ports imported")
except Exception as e:
    mark(f"ports error: {e}")

try:
    mark("importing entities...")
    import brokersv2.broker.entities as entities
    mark("entities imported")
except Exception as e:
    mark(f"entities error: {e}")

try:
    mark("importing types...")
    import brokersv2.broker.types as types
    mark("types imported")
except Exception as e:
    mark(f"types error: {e}")

try:
    mark("importing dhan.broker...")
    from brokersv2.dhan import DhanBrokerV2
    mark("dhan.broker imported")
except Exception as e:
    mark(f"dhan.broker error: {e}")

mark("DONE")
