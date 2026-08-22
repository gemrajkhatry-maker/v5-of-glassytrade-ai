"""Runtime boot — composition root for the v4 trading platform.

This is the ONLY place that wires all components together.
Fail-closed: any error during boot prevents session creation.

``boot`` also wires the extensions auto-discovery contract: every strategy
discovered in ``strategy/extensions`` is registered into a
``ReactiveStrategyEngine``, and every discovered scanner definition is bound
into the session's ``ScannerService`` (via ``scanner_definitions``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

from tradex_brokers import BrokerFactory, DhanBroker, PaperBroker, UpstoxBroker
from tradex_domain import BrokerId
from tradex_domain.market import Depth
from tradex_domain.protocols import BrokerAdapter

from tradex_trading.config.schema import AppConfig
from tradex_trading.execution.engine import ExecutionEngine, RiskManager
from tradex_trading.execution.fees import FeeCalculator
from tradex_trading.execution.book_fill_source import BookFillSource
from tradex_trading.execution.fill_sources import (
    BrokerFillSource,
    PaperFillSource,
    SimulatedFillSource,
)
from tradex_trading.execution.slippage import PercentageSlippageModel
from tradex_trading.reactive.bus import ReactiveBus
from tradex_trading.runtime.compose import compose
from tradex_trading.reactive.thread_safe_bus import ThreadSafeReactiveBus
from tradex_trading.runtime.metrics import MetricsRegistry
from tradex_trading.sdk.session import TradingSession
from tradex_trading.strategy.core.engine import ReactiveStrategyEngine
from tradex_trading.strategy.core.scanner import ScannerEngine
from tradex_trading.strategy.extensions import all_scanners, all_strategies

log = logging.getLogger(__name__)


def _broker_matches_config(config: AppConfig, broker: Any) -> bool:
    """Validate that the injected broker matches the configured broker identity.

    Built-in adapters are checked by class. A custom injected adapter may expose
    ``provider`` or ``broker_id`` for an explicit identity check; otherwise its
    injection is treated as an intentional factory override and still must
    satisfy the runtime adapter contract at session start.

    The config's ``broker.name`` defaults to ``"paper"`` and is a vestigial
    duplicate of ``broker_id``; an unset (default) name is treated as
    "unspecified" and compared against ``broker_id`` instead — so a live config
    that only sets ``broker_id`` (the documented flow) is not a mismatch, while
    an explicitly contradictory name (e.g. ``broker_id=DHAN`` with
    ``broker.name="upstox"``) is.
    """
    name = config.broker.name.strip().lower()
    if not name or name == "paper":
        name = config.broker_id.value.lower()
    if name == "paper":
        return isinstance(broker, PaperBroker)
    if isinstance(broker, DhanBroker):
        return name == "dhan"
    if isinstance(broker, UpstoxBroker):
        return name == "upstox"
    # Custom adapter — check provider/broker_id attribute.
    identity = getattr(broker, "provider", getattr(broker, "broker_id", None))
    if identity is None:
        return False
    value = getattr(identity, "value", identity)
    return str(value).strip().lower() == name


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    """Bundled runtime components returned by ``boot_context``.

    Holds the config, session, engine, strategy engine, bus, and broker so
    callers can manage the full lifecycle (including ``close()``).
    """

    config: AppConfig
    session: TradingSession
    engine: ExecutionEngine
    strategy_engine: object | None
    bus: ReactiveBus | ThreadSafeReactiveBus
    broker: Any

    def close(self) -> None:
        """Stop the session and release runtime resources."""
        self.session.stop()
        if hasattr(self, "engine") and self.engine is not None:
            try:
                self.engine.shutdown()
            except Exception as exc:  # pragma: no cover
                log.error("Error shutting down engine: %s", exc)
        if self.strategy_engine is not None:
            try:
                self.strategy_engine.dispose_all()  # type: ignore[attr-defined]
            except Exception as exc:  # pragma: no cover
                log.error("Error disposing strategy engine: %s", exc)
        close_fn = getattr(self.broker, "close", None)
        if close_fn is not None:
            close_fn()


def boot(config: AppConfig | None = None) -> TradingSession:
    """Fail-closed boot: compose all components into a ready TradingSession.

    This is the composition root — the ONLY place that wires everything together.
    Extension strategies are registered into a ``ReactiveStrategyEngine`` and
    discovered scanner definitions are bound into the session's ScannerService.

    Parameters
    ----------
    config : AppConfig | None
        Application configuration. If None, uses defaults (paper mode).

    Returns
    -------
    TradingSession
        A fully initialized session in READY state.

    Raises
    ------
    Exception
        Any error during boot prevents session creation (fail-closed).
    """
    cfg = config or AppConfig()
    log.info("Booting runtime context...")

    # 0. Safety gates
    valid_modes = {"paper", "backtest", "replay", "live"}
    if cfg.mode not in valid_modes:
        raise ValueError(
            f"unknown mode: {cfg.mode!r}, must be one of {sorted(valid_modes)}"
        )
    if cfg.mode == "live" and cfg.broker_id == BrokerId.PAPER:
        raise ValueError("live mode requires a non-paper broker")
    if cfg.mode == "live" and not cfg.live_enabled:
        raise ValueError("live mode requires live_enabled=true in config")

    # 1. Create broker. Live brokers bind a real transport via the standard
    # interface (build_broker_from_env) — BrokerFactory.create builds a
    # transport-less adapter whose REST calls raise "broker not connected".
    # Paper/backtest/replay keep the factory (paper is transport-less by design).
    # The concrete adapters (DhanBroker/UpstoxBroker) implement the
    # BrokerAdapter protocol at runtime but mypy can't prove structural
    # conformance through the BaseBroker facade, so pin the type here.
    broker: BrokerAdapter
    if cfg.mode == "live":
        from tradex_trading.runtime.live import build_broker_from_env
        broker = cast(BrokerAdapter, build_broker_from_env(cfg.broker_id.value))
        # Fail-closed identity check: an EXPLICITLY configured broker name that
        # contradicts the broker_id is a broken live config, not a guessable
        # one — abort boot instead of silently trading through the wrong
        # adapter. The default ``broker.name="paper"`` counts as unset (it
        # resolves against broker_id), so the documented broker_id-only flow
        # still boots.
        configured_name = cfg.broker.name.strip().lower()
        if configured_name not in ("", "paper") and not _broker_matches_config(
            cfg, broker
        ):
            raise ValueError(
                f"live mode broker mismatch: config broker.name "
                f"{cfg.broker.name!r} does not match {cfg.broker_id.value} "
                f"({type(broker).__name__})"
            )
    else:
        broker = cast(BrokerAdapter, BrokerFactory.create(cfg.broker_id))

    # 2. Create metrics registry
    metrics = MetricsRegistry()

    # 3. Create reactive bus. Live mode serializes publishes (RLock): the
    # broker feed thread, engine worker threads, and API callers all publish
    # concurrently, and a plain RxPY Subject must never be driven from two
    # threads at once. The feed thread's own quote → pipeline chain is
    # reentrant on the same thread, so the lock never delays it.
    bus: ReactiveBus | ThreadSafeReactiveBus = ReactiveBus(metrics=metrics)
    if cfg.mode == "live":
        # bus is still the plain ReactiveBus just created above.
        bus = ThreadSafeReactiveBus(cast(ReactiveBus, bus))

    # 3b. Execution costs — the SAME slippage + fee models used by
    # BacktestEngine when callers configure them (HIGH-6b parity: backtest and
    # reactive paper/live net P&L must agree). Off by default (zero-cost model).
    slippage_model: Any = None
    if cfg.execution.slippage_bps is not None:
        slippage_model = PercentageSlippageModel(
            pct=cfg.execution.slippage_bps / Decimal("10000"),
        )
    fee_calculator: FeeCalculator | None = (
        FeeCalculator() if cfg.execution.fees_enabled else None
    )

    # 4. Create fill source based on mode
    fill_source: Any
    if cfg.mode == "paper":
        # Paper matches against the live L2 book when depth is subscribed
        # (Depth events flow onto the session bus via the market feed);
        # without depth it degrades to LTP-at-price exactly as before.
        book_source = BookFillSource()
        bus.of_type(Depth).subscribe(
            lambda depth: book_source.update_depth(depth)
        )
        fill_source = PaperFillSource(
            slippage_model=slippage_model, book_source=book_source,
        )
    elif cfg.mode == "backtest":
        fill_source = SimulatedFillSource(slippage_model=slippage_model)
    elif cfg.mode == "live":
        fill_source = BrokerFillSource(broker)
    elif cfg.mode == "replay":
        fill_source = SimulatedFillSource(slippage_model=slippage_model)
    else:
        raise ValueError(f"unknown mode: {cfg.mode}")

    # 4b. Idempotency guard — durable SQLite so correlation IDs survive
    # restarts (duplicate-order protection). Live mode FAILS CLOSED: without
    # a durable guard a dropped response + retry can double-submit, so boot
    # aborts rather than trade without one. Paper/backtest/replay stay
    # guard-free by default (no live money path).
    guard: Any = None
    if cfg.persistence.path:
        from tradex_trading.execution.sqlite_store import SQLiteIdempotencyGuard
        guard = SQLiteIdempotencyGuard(cfg.persistence.path)
    elif cfg.mode == "live":
        raise ValueError(
            "live mode requires a durable idempotency guard; "
            "set persistence.path in the app config"
        )

    # 5. Create risk manager. The live-order gate is FAIL-CLOSED: in live mode
    # the config's ``live_orders_enabled`` (default False) is honored — a live
    # session never places orders unless explicitly enabled. Paper/backtest/
    # replay simulate fills and keep the gate open.
    live_orders = cfg.mode != "live" or cfg.live_orders_enabled
    risk_manager = RiskManager(
        max_order_value=cfg.risk.max_order_value,
        max_position_value=cfg.risk.max_position_value,
        max_orders_per_minute=cfg.risk.max_orders_per_minute,
        live_orders_enabled=live_orders,
    )

    # 6. Create execution engine
    engine = ExecutionEngine(
        bus=bus, fill_source=fill_source, risk_manager=risk_manager, metrics=metrics,
        idempotency_guard=guard, fee_calculator=fee_calculator,
    )
    # Bind the OMS cache as the position source so ``max_position_value`` is
    # enforced against live cumulative exposure (qty * avg_price + incoming).
    risk_manager.set_positions_provider(engine.cache.all_positions)
    engine.kill_switch = cfg.kill_switch_default

    # 6b. Strategy engine — register every auto-discovered extension strategy
    # so user strategies (strategy/extensions) run without touching core.
    # Discovery already isinstance-filters against the Strategy protocol, so
    # registration cannot realistically fail; any error still aborts boot
    # (fail-closed — nothing is swallowed).
    strategy_engine = ReactiveStrategyEngine(
        bus, fill_reference=cfg.execution.fill_reference,
    )
    for strategy in all_strategies:
        strategy_engine.register(strategy)

    # 7. Connect broker (loads instruments/registry for live brokers)
    broker.connect()

    # 7b. Bind the order/portfolio stream backend (live brokers only) so
    # session.stream.subscribe_orders/positions reaches the broker WebSocket
    # instead of falling back to a stub. Live mode FAILS CLOSED: without the
    # order-stream fill bridge, live fills silently never reach the OMS, so
    # boot aborts rather than trade blind.
    stream_backend: Any = None
    fill_bridge: Any = None
    if cfg.mode == "live":
        # Shared with TradingSession.live() via runtime.live_wiring so the
        # two live boot paths cannot drift (REF-5). Fail-closed: any wiring
        # failure raises instead of trading blind.
        from tradex_trading.runtime.live_wiring import build_live_streaming
        stream_backend, fill_bridge = build_live_streaming(
            broker=broker, bus=bus, engine=engine, fail_closed=True,
        )

    # 7c. Scanner engine — bind the market provider so the session's
    # ScannerService can run every auto-discovered extension scanner.
    # Backtest/replay modes scan the local parquet datalake (offline, full
    # Nifty universe) instead of the broker; paper/live keep live data.
    if cfg.mode in ("backtest", "replay"):
        from tradex_trading.datalake.market_provider import ParquetMarketProvider
        scanner_market: Any = ParquetMarketProvider()
    else:
        scanner_market = broker
    scanner_engine = ScannerEngine(market=scanner_market)

    # 7d. Backtest loader — backtest/replay modes expose an offline datalake
    # backtest tool on the session: ``session.backtest.load()``/``.run()``
    # assemble ``BacktestEngine`` inputs from the parquet store (multi-symbol,
    # no broker). Paper/live keep None (live data paths instead).
    backtest_loader: Any = None
    if cfg.mode in ("backtest", "replay"):
        from tradex_trading.datalake.backtest_loader import ParquetBacktestLoader
        backtest_loader = ParquetBacktestLoader()

    # 8. Assemble + start the session — strategies registered, scanners bound
    # into the ScannerService (definitions) so ``session.scanner.run_all()``
    # works. Shared compose() owns the cache-sharing + start invariants.
    session = compose(
        broker=broker,
        bus=bus,
        engine=engine,
        broker_id=cfg.broker_id,
        mode=cfg.mode,
        scanner_engine=scanner_engine,
        scanner_definitions=all_scanners,
        strategy_engine=strategy_engine,
        stream_backend=stream_backend,
        backtest_loader=backtest_loader,
        fill_bridge=fill_bridge,
        live_orders_enabled=live_orders,
    )

    # 9. Event journal (P0-2) — durable recording of every bus DomainEvent
    # when ``journal_path`` is configured. Attached to the session's bus and
    # bound so ``session.stop()`` closes it (durable flush per event).
    if cfg.journal_path:
        from tradex_trading.replay.event_journal import EventJournal
        journal = EventJournal(cfg.journal_path, bus=session.bus)
        session.bind_journal(journal)

    # 9b. Depth tape (P1a) — durable recording of every bus Depth snapshot
    # when ``depth_tape_path`` is configured, so a live/paper session's real
    # order book can drive tick-level L2 backtests later (the datalake only
    # stores OHLCV).
    if cfg.depth_tape_path:
        from tradex_trading.replay.depth_tape import DepthTapeRecorder
        tape = DepthTapeRecorder(cfg.depth_tape_path, bus=session.bus)
        session.bind_depth_tape(tape)

    log.info("Runtime context ready")
    return session


def boot_context(config: AppConfig | None = None) -> RuntimeContext:
    """Boot and return a full RuntimeContext for lifecycle management.

    Like ``boot`` but returns a ``RuntimeContext`` that bundles all components
    and provides a ``close()`` method for clean shutdown.
    """
    cfg = config or AppConfig()
    session = boot(cfg)
    return RuntimeContext(
        config=cfg,
        session=session,
        engine=session.engine,
        strategy_engine=session.strategy_engine,
        bus=session.bus,
        broker=session.broker,
    )


__all__ = ["RuntimeContext", "boot", "boot_context"]
