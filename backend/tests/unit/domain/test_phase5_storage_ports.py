"""Phase 5 tests — StoragePort ISP split."""
from app.domain.ports.storage import (
    IStorage, ITickStorage, ITradeStorage, IDecisionStorage,
    IOpenPositionStorage, IPositionEventStorage,
)
from app.infrastructure.storage.database import SQLiteStorageAdapter


class TestStoragePortSplit:
    def test_sub_ports_exist(self):
        assert issubclass(IStorage, ITickStorage)
        assert issubclass(IStorage, ITradeStorage)
        assert issubclass(IStorage, IDecisionStorage)
        assert issubclass(IStorage, IOpenPositionStorage)
        assert issubclass(IStorage, IPositionEventStorage)

    def test_sqlite_implements_all(self):
        adapter = SQLiteStorageAdapter(db_path=":memory:")
        assert isinstance(adapter, ITickStorage)
        assert isinstance(adapter, ITradeStorage)
        assert isinstance(adapter, IDecisionStorage)
        assert isinstance(adapter, IOpenPositionStorage)
        assert isinstance(adapter, IPositionEventStorage)
        assert isinstance(adapter, IStorage)

    def test_sub_port_has_correct_methods(self):
        assert hasattr(ITickStorage, 'save_tick')
        assert hasattr(ITickStorage, 'query_ticks')
        assert hasattr(ITradeStorage, 'save_trade')
        assert hasattr(ITradeStorage, 'query_trades')
        assert hasattr(IDecisionStorage, 'save_llm_decision')
        assert hasattr(IDecisionStorage, 'query_llm_decisions')
        assert hasattr(IOpenPositionStorage, 'save_open_position')
        assert hasattr(IOpenPositionStorage, 'delete_open_position')
        assert hasattr(IOpenPositionStorage, 'load_open_positions')
        assert hasattr(IPositionEventStorage, 'save_position_event')
        assert hasattr(IPositionEventStorage, 'query_position_events')
