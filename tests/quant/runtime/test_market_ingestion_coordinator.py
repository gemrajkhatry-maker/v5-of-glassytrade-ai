from dataclasses import dataclass

from quant.market_ingestion import MarketIngestionCoordinator


@dataclass
class Tick:
    price: float


class Gateway:
    def __init__(self):
        self.subscriptions = []
        self.ticks = iter([Tick(101.0), None])

    def subscribe(self, symbol):
        self.subscriptions.append(symbol)

    def next_tick(self):
        return next(self.ticks)


def test_coordinator_preserves_subscription_and_tick_order():
    gateway = Gateway()
    coordinator = MarketIngestionCoordinator(gateway, "NIFTY")

    coordinator.subscribe()

    assert gateway.subscriptions == ["NIFTY"]
    assert coordinator.next_tick().price == 101.0
    assert coordinator.next_tick() is None


def test_coordinator_drains_optional_underlying_feed_without_reordering():
    primary = Gateway()
    underlying = Gateway()
    underlying.ticks = iter([Tick(200.0), Tick(201.0), None])
    coordinator = MarketIngestionCoordinator(primary, "NIFTY", underlying)

    coordinator.subscribe()
    assert underlying.subscriptions == ["NIFTY"]
    assert [tick.price for tick in coordinator.drain_underlying()] == [200.0, 201.0]
