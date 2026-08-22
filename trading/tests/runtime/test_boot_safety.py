"""Tests for boot() safety gates — mode validation, live gates, wiring."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from tradex_domain import BrokerId
from tradex_domain.capabilities import dhan_capabilities

from tradex_trading.config.schema import AppConfig
from tradex_trading.runtime.startup import boot


class TestBootModeValidation:
    """boot() validates the mode against an allowlist."""

    def test_paper_mode_boots(self) -> None:
        cfg = AppConfig(mode="paper")
        session = boot(cfg)
        assert session.state.value == "READY"
        session.stop()

    def test_backtest_mode_boots(self) -> None:
        cfg = AppConfig(mode="backtest")
        session = boot(cfg)
        assert session.state.value == "READY"
        session.stop()

    def test_unknown_mode_raises(self) -> None:
        cfg = AppConfig(mode="unknown_mode")
        with pytest.raises(ValueError, match="unknown mode"):
            boot(cfg)

    def test_empty_mode_raises(self) -> None:
        cfg = AppConfig(mode="")
        with pytest.raises(ValueError, match="unknown mode"):
            boot(cfg)


class TestBootConfigValidation:
    """AppConfig.from_dict fails closed on broken values."""

    def test_from_dict_unknown_broker_id_raises(self) -> None:
        """A typo'd/unknown broker_id must raise — never silently become PAPER
        (which would turn a broken live config into a paper session)."""
        with pytest.raises(ValueError, match="unknown broker_id"):
            AppConfig.from_dict({"broker_id": "dhaan", "mode": "live"})

    def test_from_dict_known_broker_id_parses(self) -> None:
        cfg = AppConfig.from_dict({"broker_id": "DHAN", "mode": "live"})
        assert cfg.broker_id == BrokerId.DHAN


def _fake_broker(backend: MagicMock | None = None) -> MagicMock:
    """MagicMock live broker: capabilities + an order-stream backend."""
    broker = MagicMock()
    broker.capabilities = dhan_capabilities()
    broker.stream_backend.return_value = backend or MagicMock()
    return broker


def _live_cfg(tmp_path) -> AppConfig:
    from tradex_trading.config.schema import PersistenceConfig

    return AppConfig(
        mode="live",
        broker_id=BrokerId.DHAN,
        live_enabled=True,
        persistence=PersistenceConfig(path=str(tmp_path / "orders.db")),
    )


def _request() -> object:
    from decimal import Decimal

    from tradex_domain.enums import OrderSide, OrderType, TimeInForce
    from tradex_domain.execution import OrderRequest
    from tradex_domain.instruments import Equity
    from tradex_domain.value_objects import Price, Quantity

    return OrderRequest(
        instrument=Equity.of("NSE", "RELIANCE"),
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Quantity(value=Decimal("10")),
        price=Price(value=Decimal("100")),
        time_in_force=TimeInForce.DAY,
    )


class TestBootLiveGates:
    """boot() enforces live-mode safety gates."""

    def test_live_with_paper_broker_raises(self) -> None:
        cfg = AppConfig(mode="live", broker_id=BrokerId.PAPER, live_enabled=True)
        with pytest.raises(ValueError, match="live mode requires a non-paper broker"):
            boot(cfg)

    def test_live_without_live_enabled_raises(self) -> None:
        cfg = AppConfig(mode="live", broker_id=BrokerId.DHAN, live_enabled=False)
        with pytest.raises(ValueError, match="live mode requires live_enabled"):
            boot(cfg)

    def test_live_boot_broker_name_mismatch_raises(
        self, monkeypatch, tmp_path
    ) -> None:
        """An explicitly contradictory broker.name (upstox vs broker_id=DHAN)
        aborts boot instead of silently trading through the wrong adapter."""
        from tradex_trading.config.schema import BrokerConfig
        from tradex_trading.runtime import live as live_mod

        cfg = AppConfig(
            mode="live",
            broker_id=BrokerId.DHAN,
            live_enabled=True,
            broker=BrokerConfig(name="upstox"),
            persistence=_live_cfg(tmp_path).persistence,
        )
        monkeypatch.setattr(
            live_mod, "build_broker_from_env", lambda _p, **_kw: _fake_broker()
        )
        with pytest.raises(ValueError, match="broker mismatch"):
            boot(cfg)

    def test_live_boot_orders_gated_by_default(
        self, monkeypatch, tmp_path
    ) -> None:
        """Fail-closed: live boot with the schema default (live_orders_enabled
        unset → False) must NOT place orders — the config flag is honored, not
        silently overridden to True."""
        from tradex_domain.errors import OrderRejectedError
        from tradex_trading.runtime import live as live_mod

        broker = _fake_broker()
        broker.submit_order.return_value = "upstox-order-1"
        monkeypatch.setattr(live_mod, "build_broker_from_env", lambda _p, **_kw: broker)

        session = boot(_live_cfg(tmp_path))
        try:
            assert session._live_orders_enabled is False
            assert session.engine._risk.live_orders_enabled is False
            with pytest.raises(OrderRejectedError):
                session.trade.submit(_request())
        finally:
            session.stop()

    def test_live_boot_orders_enabled_when_explicit(
        self, monkeypatch, tmp_path
    ) -> None:
        """Explicit opt-in (live_orders_enabled=True) opens the order gate."""
        from tradex_domain.enums import OrderStatus
        from tradex_trading.runtime import live as live_mod

        broker = _fake_broker()
        broker.submit_order.return_value = "upstox-order-1"
        monkeypatch.setattr(live_mod, "build_broker_from_env", lambda _p, **_kw: broker)

        cfg = _live_cfg(tmp_path)
        cfg = AppConfig(
            mode="live",
            broker_id=BrokerId.DHAN,
            live_enabled=True,
            live_orders_enabled=True,
            persistence=cfg.persistence,
        )
        session = boot(cfg)
        try:
            assert session._live_orders_enabled is True
            assert session.engine._risk.live_orders_enabled is True
            receipt = session.trade.submit(_request())
            assert receipt.status in (OrderStatus.ACK, OrderStatus.SUBMITTED)
        finally:
            session.stop()


    def test_paper_boot_with_journal_path_records_events(self, tmp_path) -> None:
        """P0-2: boot with journal_path durably records bus events and closes
        the journal on session.stop()."""
        from decimal import Decimal

        from tradex_domain.enums import OrderSide, OrderType, TimeInForce
        from tradex_domain.execution import OrderRequest
        from tradex_domain.instruments import Equity
        from tradex_domain.value_objects import CorrelationId, Price, Quantity

        journal_file = tmp_path / "session.jsonl"
        cfg = AppConfig(mode="paper", journal_path=str(journal_file))
        session = boot(cfg)
        try:
            session.engine.submit(OrderRequest(
                instrument=Equity.of("NSE", "RELIANCE"),
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Quantity(value=Decimal("10")),
                price=Price(value=Decimal("2500")),
                time_in_force=TimeInForce.DAY,
                correlation_id=CorrelationId(value="journal-boot"),
            ))
            lines = [ln for ln in journal_file.read_text().splitlines() if ln.strip()]
            assert any("OrderPlaced" in ln for ln in lines)
            assert any("OrderFilled" in ln for ln in lines)
        finally:
            session.stop()
        # The journal is closed and replayable after stop.
        from tradex_trading.replay.event_journal import iter_journal_events
        assert len(list(iter_journal_events(journal_file))) > 0

    def test_boot_without_journal_path_records_nothing(self, tmp_path) -> None:
        cfg = AppConfig(mode="paper")
        session = boot(cfg)
        try:
            assert session._journal is None  # noqa: SLF001
        finally:
            session.stop()

    def test_paper_boot_with_depth_tape_records_snapshots(self, tmp_path) -> None:
        """P1a: boot with depth_tape_path durably records Depth snapshots and
        closes the tape on session.stop()."""
        from decimal import Decimal

        from tradex_domain.instruments import Equity
        from tradex_domain.market import Depth
        from tradex_domain.value_objects import Price, Quantity

        tape_file = tmp_path / "depth.jsonl"
        cfg = AppConfig(mode="paper", depth_tape_path=str(tape_file))
        session = boot(cfg)
        try:
            session.bus.publish(Depth(
                instrument=Equity.of("NSE", "RELIANCE"),
                bids=((Price(value=Decimal("99")), Quantity(value=Decimal("5"))),),
                asks=((Price(value=Decimal("101")), Quantity(value=Decimal("5"))),),
            ))
            lines = [ln for ln in tape_file.read_text().splitlines() if ln.strip()]
            assert any("Depth" in ln for ln in lines)
        finally:
            session.stop()
        # The tape is closed and loadable after stop.
        from tradex_trading.replay.depth_tape import load_depth_tape
        assert len(load_depth_tape(tape_file)) == 1

    def test_boot_without_depth_tape_records_nothing(self, tmp_path) -> None:
        cfg = AppConfig(mode="paper")
        session = boot(cfg)
        try:
            assert session._depth_tape is None  # noqa: SLF001
        finally:
            session.stop()


class TestBootSessionMode:
    """boot() stores mode on the session."""

    def test_session_has_mode(self) -> None:
        cfg = AppConfig(mode="paper")
        session = boot(cfg)
        assert session.mode == "paper"
        session.stop()

    def test_backtest_session_mode(self) -> None:
        cfg = AppConfig(mode="backtest")
        session = boot(cfg)
        assert session.mode == "backtest"
        session.stop()


class TestBootStreamBackendWiring:
    """boot() wires the broker order/portfolio stream backend into the session."""

    def test_live_boot_wires_stream_backend(self, monkeypatch, tmp_path) -> None:
        from tradex_trading.runtime import live as live_mod

        backend = MagicMock()
        broker = _fake_broker(backend)
        monkeypatch.setattr(live_mod, "build_broker_from_env", lambda _p, **_kw: broker)

        session = boot(_live_cfg(tmp_path))
        try:
            assert session._stream_backend is backend
            assert session.stream._backend is backend
        finally:
            session.stop()

    def test_live_boot_raises_when_backend_fails(self, monkeypatch, tmp_path) -> None:
        """Fail-closed: a live broker whose order-stream backend can't build
        aborts boot instead of silently running with no fill path."""
        from tradex_trading.runtime import live as live_mod

        broker = _fake_broker()
        broker.stream_backend.side_effect = RuntimeError("no ws transport")
        monkeypatch.setattr(live_mod, "build_broker_from_env", lambda _p, **_kw: broker)

        with pytest.raises(ValueError, match="failed to build"):
            boot(_live_cfg(tmp_path))

    def test_paper_boot_has_no_stream_backend(self) -> None:
        cfg = AppConfig(mode="paper")
        session = boot(cfg)
        try:
            assert session._stream_backend is None
        finally:
            session.stop()


class TestBootPersistenceWiring:
    """boot() wires the durable idempotency guard when persistence is set."""

    def test_persistence_path_wires_sqlite_guard(self, tmp_path) -> None:
        from tradex_trading.config.schema import PersistenceConfig
        from tradex_trading.execution.sqlite_store import SQLiteIdempotencyGuard

        cfg = AppConfig(
            mode="paper",
            persistence=PersistenceConfig(path=str(tmp_path / "orders.db")),
        )
        session = boot(cfg)
        try:
            guard = session.engine._guard  # noqa: SLF001 – wiring probe
            assert isinstance(guard, SQLiteIdempotencyGuard)
        finally:
            session.stop()

    def test_no_persistence_keeps_no_guard(self) -> None:
        """Default boot stays unchanged: idempotency is opt-in."""
        session = boot(AppConfig(mode="paper"))
        try:
            assert session.engine._guard is None  # noqa: SLF001 – wiring probe
        finally:
            session.stop()
