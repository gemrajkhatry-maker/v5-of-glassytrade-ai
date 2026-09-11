"""Small compatibility seam for market-feed ingestion."""


class MarketIngestionCoordinator:
    """Preserve QuantEngine's gateway protocol behind a focused facade."""

    def __init__(self, gateway, symbol: str, underlying_gateway=None, underlying_symbol: str | None = None) -> None:
        self._gateway = gateway
        self._symbol = symbol
        self._underlying_gateway = underlying_gateway
        self._underlying_symbol = underlying_symbol or symbol
        self._subscribed = False

    def subscribe(self) -> None:
        if not self._subscribed:
            self._gateway.subscribe(self._symbol)
            if self._underlying_gateway is not None:
                self._underlying_gateway.subscribe(self._underlying_symbol)
            self._subscribed = True

    def next_tick(self):
        return self._gateway.next_tick()

    def try_next_tick(self):
        if self._underlying_gateway is None:
            return None
        reader = getattr(self._underlying_gateway, "try_next_tick", None)
        return reader() if reader is not None else self._underlying_gateway.next_tick()

    def drain_underlying(self):
        if self._underlying_gateway is None:
            return
        while True:
            tick = self.try_next_tick()
            if tick is None:
                return
            yield tick
