"""Phase 5 tests — StoragePort ISP split."""
from app.domain.ports.storage import (
    StoragePort, TickStoragePort, TradeStoragePort, DecisionStoragePort,
    OpenPositionStoragePort,
)
from app.infrastructure.storage.database import SQLiteStorageAdapter


class TestStoragePortSplit:
    def test_sub_ports_exist(self):
        assert issubclass(StoragePort, TickStoragePort)
        assert issubclass(StoragePort, TradeStoragePort)
        assert issubclass(StoragePort, DecisionStoragePort)
        assert issubclass(StoragePort, OpenPositionStoragePort)

    def test_sqlite_implements_all(self):
        adapter = SQLiteStorageAdapter(db_path=":memory:")
        assert isinstance(adapter, TickStoragePort)
        assert isinstance(adapter, TradeStoragePort)
        assert isinstance(adapter, DecisionStoragePort)
        assert isinstance(adapter, OpenPositionStoragePort)
        assert isinstance(adapter, StoragePort)

    def test_sub_port_has_correct_methods(self):
        assert hasattr(TickStoragePort, 'save_tick')
        assert hasattr(TickStoragePort, 'query_ticks')
        assert hasattr(TradeStoragePort, 'save_trade')
        assert hasattr(TradeStoragePort, 'query_trades')
        assert hasattr(DecisionStoragePort, 'save_llm_decision')
        assert hasattr(DecisionStoragePort, 'query_llm_decisions')
        assert hasattr(OpenPositionStoragePort, 'save_open_position')
        assert hasattr(OpenPositionStoragePort, 'delete_open_position')
        assert hasattr(OpenPositionStoragePort, 'load_open_positions')
