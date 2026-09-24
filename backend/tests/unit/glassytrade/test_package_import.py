def test_target_package_imports_without_legacy_host_modules():
    from glassytrade.domain.common.ids import ContractId
    from glassytrade.domain.execution.types import OrderIntent
    from glassytrade.domain.ledger.events import LedgerEvent
    from glassytrade.domain.market_data.events import MarketDataEvent

    assert ContractId.__module__.startswith("glassytrade.")
    assert OrderIntent.__module__.startswith("glassytrade.")
    assert LedgerEvent.__module__.startswith("glassytrade.")
    assert MarketDataEvent.__module__.startswith("glassytrade.")
