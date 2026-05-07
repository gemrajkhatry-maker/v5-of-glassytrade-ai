#!/usr/bin/env python
"""Manually run test_get_quotes_batch test."""
from brokersv2.broker.entities import Instrument, Quote, Exchange
from brokersv2.dhan import DhanBrokerV2

broker = DhanBrokerV2.create()
instruments = [
    Instrument(symbol="RELIANCE", exchange=Exchange.NSE),
    Instrument(symbol="TCS", exchange=Exchange.NSE),
]
quotes = broker.get_quotes_batch(instruments)

assert isinstance(quotes, dict), "quotes not dict"
assert len(quotes) == 2, f"expected 2 quotes, got {len(quotes)}"
for inst, quote in quotes.items():
    assert inst in instruments, f"{inst} not in instruments"
    assert isinstance(quote, Quote), f"quote not Quote: {type(quote)}"
    assert quote.ltp > 0, f"ltp not positive: {quote.ltp}"

print("TEST PASSED")
