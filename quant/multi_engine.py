"""QuantCoordinator — multi-symbol orchestrator.

Architecture Overview
=====================
QuantCoordinator owns one QuantEngine per scanned contract, all fed by a
single multiplexed market data feed. It manages the lifecycle of engines,
handles symbol rotation, and provides health/readiness telemetry.

Pipeline Flow:
  Scanner → Symbol List → EngineFactory → QuantEngine (one per symbol)
                                      ↓
                              ThreadPoolExecutor (bounded)
                                      ↓
                              Backend (WS snapshots, health, metrics)

Internal Structure
==================
The coordinator is organized into these functional areas:

1. LIFECYCLE — start, stop, rescan, symbol rotation
2. ENGINE MANAGEMENT — spawn, stop, thread pool, gateway lifecycle
3. POSITION RECONCILIATION — startup restore, stale quarantine
4. HEALTH & READINESS — crashed engines, staleness, readiness status
5. METRICS — per-engine activity, aggregate totals
6. SCHEDULERS — history seed scheduler, EOD watchdog

Pure quant: imports ``quant.*`` and stdlib only — zero backend imports.

Threading and Locking
=====================
The coordinator spawns one QuantEngine per symbol, each running in its own
thread. Cross-engine coordination happens through shared authorities:

- ``PortfolioRiskAuthority``: Aggregate risk ceiling (shared, locked)
- ``SessionLevelStore``: Session persistence (per-symbol, locked)

Lock Ordering Invariant
-----------------------
When acquiring multiple locks, always acquire in this order:

1. ``QuantCoordinator._lifecycle_lock`` (global, guards engine spawn/stop)
2. ``QuantCoordinator._lock`` (global, guards engine registry)
3. ``QuantEngine._close_lock`` (per-engine, serializes position close)
4. ``PortfolioRiskAuthority._lock`` (global, guards aggregate risk)
5. ``SessionRisk._lock`` (per-symbol, guards risk state)

Never acquire locks in reverse order. The EOD watchdog thread may call
``force_close_position()`` on engines running in other threads — this acquires
the engine's ``_close_lock``, which serializes with the engine thread's own
close operations.

EOD Watchdog
------------
The EOD watchdog runs in a separate thread and monitors for end-of-day
conditions. It can call ``force_close_position()`` on any engine, which
acquires the engine's ``_close_lock``. This is safe because ``_close_lock``
serializes close operations across threads.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

from quant.decision.timesfm_forecast_factory import FALLBACK_BAND_PCT
from quant.amt.session.scanner import OptionScannerService
from quant.brokers.live_gateway import LiveGateway
from quant.brokers.multiplexed_feed import MultiplexedMarketFeed
from quant.contracts.aggregates import INITIAL_CAPITAL
from quant.contracts.enums import MarketState
from quant.contracts.contracts import ContractRef
from quant.contracts.instrument_registry import (
    DEFAULT_REGISTRY,
    is_futures_contract,
    is_option_contract,
    root_token,
)
from quant.contracts.vocabulary import is_call_symbol, is_put_symbol
from quant.session_gates import parse_contract_expiry
from quant.contracts.market_calendar import is_trading_day
from quant.contracts.timezones import IST, MCX_SESSION_CLOSE, NSE_SESSION_CLOSE
from quant.events import BarClosed
from quant.execution.live_oms import LiveOMS
from quant.execution.oms import PaperOMS
from quant.execution.paper_reconciliation import PaperPositionReconciler, ReconciliationResult
from quant.execution.ledger_reconstruction import reconstruct_fill_ledger
from quant.execution.readiness import readiness_status, ReadinessStatus
from quant.hotpath import get_hotpath_tracer
from quant.reconciliation_service import canonical_key, partition_keys
from quant.runtime import QuantEngine
from quant.session_levels import SessionLevelStore
from quant.state import project_state
from quant.state_machine import EngineState
from quant.ws_adapter import view_state_to_ws

logger = logging.getLogger(__name__)

# Opt-in hot-path trace (GLASSYTRADE_HOTPATH_TRACE=1) — snapshot phase.
_HOTPATH = get_hotpath_tracer()


def _is_futures_symbol(symbol: str) -> bool:
    """Broker futures formats — never 'ends with FUT' alone."""
    return is_futures_contract(symbol)


def _canonical_root(symbol: str) -> str:
    spec = DEFAULT_REGISTRY.try_resolve(symbol)
    return spec.root if spec is not None else root_token(symbol)


_OPTION_SUFFIX_RE = re.compile(r"[\s\-_]*(?:CALL|PUT|CE|PE)$", re.IGNORECASE)
_PREFIX_RE = re.compile(r"^(?:NSE|NFO|MCX|BSE|BFO):", re.IGNORECASE)
_DELIMITED_STRIKE_RE = re.compile(
    r"(?:[\s\-_])(\d+(?:\.\d+)?)\s*[\-_]?\s*(?:CALL|PUT|CE|PE)$",
    re.IGNORECASE,
)
_MONTH_STRIKE_RE = re.compile(
    r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[\s\-_]*(\d+(?:\.\d+)?)\s*[\-_]?\s*(?:CALL|PUT|CE|PE)$",
    re.IGNORECASE,
)
_WEEKLY_COMPACT_RE = re.compile(
    r"^\d{2}(?:[1-9]|10|11|12|[ONDond])\d{2}(\d+(?:\.\d+)?)\s*[\-_]?\s*(?:CE|PE|CALL|PUT)$",
    re.IGNORECASE,
)
_TRAILING_DIGITS_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[\-_]?\s*(?:CALL|PUT|CE|PE)$",
    re.IGNORECASE,
)


def extract_option_strike(symbol: str) -> float | None:
    """Extract strike price from various option symbol formats.

    Supports:
    - Spaced: 'NIFTY 1 SEP 24200 CALL', 'CRUDEOIL 19 MAR 6800.0 PE', 'NIFTY 23500 CE'
    - Hyphenated: 'NIFTY-27MAR24-23500-CE', 'CRUDEOIL_6800_CE'
    - Compact monthly: 'NIFTY24AUG23500CE', 'CRUDEOIL24MAR6800PE'
    - Compact weekly: 'NIFTY2482823500CE', 'BANKNIFTY24O2851000PE'
    - Compact root+strike: 'NIFTY23500CE', 'RELIANCE2600CE'
    """
    if not symbol:
        return None
    clean = _PREFIX_RE.sub("", str(symbol).strip()).upper()
    if not _OPTION_SUFFIX_RE.search(clean):
        return None

    m = _DELIMITED_STRIKE_RE.search(clean)
    if m:
        try:
            return float(m.group(1))
        except ValueError:  # silent-except - non-numeric regex strike group
            pass

    m = _MONTH_STRIKE_RE.search(clean)
    if m:
        try:
            return float(m.group(1))
        except ValueError:  # silent-except - non-numeric regex strike group
            pass

    root = _canonical_root(clean)
    rem = clean
    if root and clean.startswith(root):
        rem = clean[len(root):].strip(" -_")

    m = _WEEKLY_COMPACT_RE.search(rem)
    if m:
        try:
            return float(m.group(1))
        except ValueError:  # silent-except - non-numeric regex strike group
            pass

    m = _TRAILING_DIGITS_RE.search(rem if rem else clean)
    if m:
        try:
            return float(m.group(1))
        except ValueError:  # silent-except - non-numeric regex strike group
            pass

    return None


# Persist the coordinator's active contracts (JSON, stdlib-only) so a backend
# restart on the same trading day reuses the same strikes instead of re-running
# the option scanner and switching contracts (which also resets per-symbol
# decision history in the UI). Defaults to <repo-root>/backend/.active_contracts.json
# regardless of cwd; override via coord_config["contracts_file"].
_DEFAULT_CONTRACTS_FILE = str(
    Path(__file__).resolve().parents[1] / "backend" / ".active_contracts.json"
)

# Prior-session levels + naked-POC records (Phase 1) live next to the
# contracts file: <repo-root>/backend/.session_levels.json, override via
# coord_config["session_levels_file"]. Survives restarts so the AMT analyzer
# can target the previous balance area from session one.
_DEFAULT_SESSION_LEVELS_FILE = str(
    Path(__file__).resolve().parents[1] / "backend" / ".session_levels.json"
)


def _ist_date_str() -> str:
    """Current trading day as an IST date string (YYYY-MM-DD)."""
    return datetime.now(tz=IST).date().isoformat()


def load_persisted_contracts(
    path: str | None = None, exchange: str | None = None
) -> list[str] | None:
    """Return persisted active contracts if they belong to today's IST trading
    day and (when ``exchange`` is given) were selected for that exchange, else
    None (stale/absent/mismatched selections must trigger a fresh scan).

    Exchange scoping matters for mid-day strategy switches: an NSE selection
    persisted in the morning must never be reused after the app restarts in
    MCX mode (the contracts resolve to different underlyings entirely).
    """
    path = path or _DEFAULT_CONTRACTS_FILE
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if data.get("date") != _ist_date_str():
        return None
    if exchange is not None and str(data.get("exchange") or "").upper() != str(exchange).upper():
        return None
    symbols = data.get("symbols") or []
    if not isinstance(symbols, list) or not all(
        isinstance(s, str) and s.strip() for s in symbols
    ):
        return None
    return [s.strip() for s in symbols]


def save_persisted_contracts(
    symbols: list[str], path: str | None = None, exchange: str | None = None
) -> None:
    """Persist the active contracts for today's IST trading day, tagged with
    the exchange they were selected for so a strategy switch can't reuse them."""
    path = path or _DEFAULT_CONTRACTS_FILE
    payload: dict = {"date": _ist_date_str(), "symbols": list(symbols)}
    if exchange is not None:
        payload["exchange"] = str(exchange).upper()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except OSError:
        logger.warning("Failed to persist active contracts to %s", path)


_DEFAULT_CONFIG = {
    "underlyings": ["NIFTY", "BANKNIFTY", "FINNIFTY"],
    "n": 8,
    "exchange": "NSE",
    "expiry_index": 0,
    "strikes_around_atm": 2,
    "interval_seconds": 60,
    "include_futures": True,
    # Explicit topology: futures and options are independent engines. Legacy
    # futures-to-option translation is never selected by strategy name.
    "execution_model": "independent",
    # EOD square-off backstop: minutes before exchange close at which the
    # watchdog force-flattens any still-open position (intraday-only book).
    "eod_squareoff_minutes_before_close": 15,
    # First-listed roots get first claim on scanner slots (primary series).
    "underlying_priority": None,
    # LLM advisor injection: default OFF — the Fabio AMT strategy is fully
    # deterministic; the LLM advisor is advisory-only (narrative/journal)
    # and must not participate in trading decisions. Set to True only for
    # experimental/experimental runs where LLM narrative is desired.
    "advisor_enabled": False,
    # Default paper execution economics. The coordinator always supplies an
    # explicit profile to the cost-aware OMS factory, including lightweight
    # test/replay coordinators that do not receive backend configuration.
    "cost_profile": {
        "slippage_bps": 15.0,
        "stt_pct": 0.00025,
        "exchange_fee_pct": 0.00053,
        "brokerage_per_order": 20.0,
        "gst_on_brokerage_pct": 0.18,
        "sebi_charges_pct": 0.000001,
        "fill_mode": "bid_ask",
    },
}


def _engine_has_open_position(engine) -> bool:
    """Real position truth for rotation/migration/switch guards.

    QuantEngine never defined an ``engine._position`` attribute — the legacy
    guards used ``getattr(engine, "_position", None)``, which is ALWAYS None
    on a real engine, so dead/drifted contracts could be rotated or migrated
    away WHILE holding a live position. The stopped engine's book was then
    abandoned at the broker with no manager, and because the engine left the
    coordinator's map, even the EOD square-off backstop could no longer see
    it — an overnight orphan (architectural review, phase-5 hardening).

    The authoritative position lives in the folded EngineState
    (``state.position`` — what the run-loop gates on) plus the PositionManager
    book (pyramid add-ons), which is the execution truth.
    """
    if engine is None:
        return False
    state = getattr(engine, "state", None)
    if state is not None:
        # A real QuantEngine ALWAYS carries a folded EngineState; when it says
        # flat (position and pyramids empty) the engine IS flat — trust it
        # (also keeps MagicMock engines from auto-answering "positioned").
        if getattr(state, "position", None) is not None:
            return True
        if getattr(state, "pyramids", ()):
            return True
        return False
    # Stub without a state attribute: consult the execution book directly.
    pm_factory = getattr(engine, "_get_position_manager", None)
    if callable(pm_factory):
        try:
            pm = engine._get_position_manager()
        except Exception:
            return False
        if getattr(pm, "current_position", None) is not None:
            return True
        if getattr(pm, "pyramid_positions", None):
            return True
    return False


def _signed_broker_qty(bp) -> float:
    """Normalize a broker position to a signed quantity (C6).

    The broker adapter reports ``size = abs(quantity)`` plus a ``side``
    (LONG/SHORT), while the engine's persisted rows store SIGNED size
    (+long / -short). Comparing the two directly made every open SHORT look
    like a discrepancy (e.g. broker +10 vs DB -10), so a live restart with a
    short book always failed strict reconciliation.
    """
    qty = abs(float(getattr(bp, "size", 0) or 0))
    side = getattr(bp, "side", None)
    side_str = str(getattr(side, "value", side) or "").upper()
    if "SHORT" in side_str or "SELL" in side_str:
        return -qty
    return qty


def _retrieve_future_exception(future: Future) -> None:
    """Mark a completed engine task's exception as retrieved.

    ``engine.run()`` logs CRITICAL and re-raises after flagging ``_crashed``;
    the raised exception is stored on the pool Future. Without retrieval the
    interpreter warns "exception was never retrieved" when the Future is
    dropped. The engine already logged the failure — this only silences the
    GC warning.
    """
    if not future.cancelled():
        future.exception()


class QuantCoordinator:
    """Owns one :class:`QuantEngine` per scanned contract, all fed by a
    single multiplexed :class:`MultiplexedMarketFeed` — one WebSocket
    connection for every symbol (Dhan allows up to 1000 instruments per
    connection)."""

    # =========================================================================
    # 1. LIFECYCLE — start, stop, rescan, symbol rotation
    # =========================================================================
    def __init__(
        self,
        market_data,
        broker=None,
        config=None,
        strategy=None,
        storage=None,
    ) -> None:
        self.market_data = market_data
        self.broker = broker
        self.config = {**_DEFAULT_CONFIG, **(config or {})}
        self._strategy = strategy  # TradingStrategy — None means engine uses default
        self._storage = storage
        self._contracts_file = self.config.get("contracts_file") or _DEFAULT_CONTRACTS_FILE
        # Shared across all engines (one file, one lock) so prior levels are
        # consistent and NPOC records dedupe per session.
        self._session_levels = SessionLevelStore(
            path=self.config.get("session_levels_file") or _DEFAULT_SESSION_LEVELS_FILE
        )
        self._feed = MultiplexedMarketFeed(market_data)
        self._engines: dict[str, QuantEngine] = {}
        self._gateways: dict[str, LiveGateway] = {}
        self._underlying_gateways: dict[str, LiveGateway] = {}
        # Bounded engine pool. Each RUNNING engine occupies one worker (its
        # run loop blocks on the symbol's tick queue until the gateway
        # closes), so the pool is sized to the maximum concurrent contracts
        # the coordinator may own (config ``n``) and ``_spawn_engine``
        # refuses anything past that capacity — N contracts can never become
        # N raw daemon threads, and rescan/rotation cycles REUSE pool threads
        # instead of churning one OS thread per engine per cycle. Override
        # the budget with config ``max_engine_threads``.
        try:
            engine_slots = max(1, int(self.config.get("n", 8) or 8))
        except (TypeError, ValueError):
            engine_slots = 8
        try:
            self._max_threads = max(
                1, int(self.config.get("max_engine_threads") or engine_slots)
            )
        except (TypeError, ValueError):
            self._max_threads = engine_slots
        self._executor: ThreadPoolExecutor | None = None
        self._ensure_executor()
        # Per-engine run handles: symbol -> pool Future (None when a test
        # seam suppressed the run task). Mirrors the historical per-engine
        # Thread map — ``_stop_engine`` pops and waits on the handle.
        self._threads: dict[str, Future | None] = {}
        self._stop = threading.Event()
        self._gex_by_root: dict[str, object] = {}
        self._eod_thread: threading.Thread | None = None
        # Dead-man hook for the EOD watchdog: invoked as (where, exc) on
        # every swallowed per-pass exception. None by default; never raises.
        self._on_watchdog_error = None
        self._lock = threading.Lock()
        # Paper position reconciliation: classify persisted positions against
        # the active universe so stale contracts are quarantined, not restored.
        self._quarantined: set[str] = set()
        self._unresolved_startup: set[str] = set()
        self._reconciliation_result: ReconciliationResult | None = None
        # Shared history seed scheduler: one per coordinator so all engines
        # serialize through one rate-limited fetch path (prevents DH-3001).
        from quant.execution.seed_scheduler import HistorySeedScheduler
        self._seed_scheduler = HistorySeedScheduler(
            market_data,
            min_interval_sec=float(os.environ.get("GLASSYTRADE_SEED_INTERVAL_SEC", "0.5")),
        )
        # Serializes LIFECYCLE TRANSITIONS (start/rescan/switch/stop). These
        # compose multiple steps over the shared dicts + threads above — a
        # dict-level lock cannot close the check-then-act window between them
        # (two concurrent switch_symbol(old, …) calls both passed the
        # membership check and spawned DUPLICATE engines for the new symbol).
        # Lifecycle ops are rare admin actions; coarse serialization is the
        # correct ownership boundary here.
        self._lifecycle_lock = threading.RLock()
        # Shared cross-engine risk ceiling: every engine registers entries and
        # exits against ONE authority so the aggregate book can't risk more
        # than the portfolio limit (8 engines x 5% each would otherwise
        # simultaneously risk 40% of capital).
        from quant.execution.portfolio_risk import PortfolioRiskAuthority
        self._portfolio_risk = PortfolioRiskAuthority(
            starting_equity=float(self.config.get("starting_equity", float(INITIAL_CAPITAL))),
            max_portfolio_risk_pct=float(self.config.get("max_portfolio_risk_pct", 0.25)),
            max_portfolio_daily_loss_pct=float(self.config.get("max_portfolio_daily_loss_pct", 0.15)),
            max_root_risk_pct=self.config.get("max_root_risk_pct"),
            max_exchange_risk_pct=self.config.get("max_exchange_risk_pct"),
            separate_by="symbol",
        )
        # One capital book is shared by every LiveOMS. Per-engine Portfolio
        # instances otherwise each report the full account balance and allow
        # aggregate sizing/exposure to diverge from the coordinator authority.
        from quant.contracts.aggregates import Portfolio
        self._portfolio = Portfolio.create_default(
            capital=self.config.get("starting_equity", float(INITIAL_CAPITAL))
        )
        self.started = False
        # Reconciliation service for startup recovery
        self.reconciliation = None  # Set after broker is available

    def start(self) -> None:
        with self._lifecycle_lock:
            if self.config.get("live_oms_enabled") and self.broker is None:
                # live_oms_enabled but no broker adapter wired — refuse to start
                # rather than silently paper-trade under a live process name.
                raise RuntimeError(
                    "Live execution is enabled but no broker adapter is wired. "
                    "Set live_oms_enabled=False or provide a broker adapter."
                )
            # Startup reconciliation is owned by backend/app/main.py
            # (StartupReconciliation) — runs before coordinator start and is
            # wired into startup contracts + telemetry. No duplicate here.
            # Phase 2: zero holiday awareness previously existed anywhere in
            # the coordinator — it would happily scan and spawn engines on
            # NSE/MCX holidays. A calendar-closed day means no contracts to
            # trade at all, not merely a scan with stale/empty results.
            if not is_trading_day():
                logger.info(
                    "QuantCoordinator: today is not an NSE/MCX trading day — "
                    "skipping scan/spawn"
                )
                self.started = True
                return
            symbols = self._scan()
            self._refresh_gex()
            self._feed.set_symbols(symbols)
            # Paper position reconciliation: classify persisted positions
            # against the active universe. Only OPEN positions are restored;
            # stale contracts are quarantined (preserved in storage but not
            # loaded into any engine).
            self._reconciliation_result = PaperPositionReconciler(
                self._storage, active_universe=set(symbols)
            ).reconcile()
            self._unresolved_startup = set()
            self._load_inflight_orders_for_startup()
            self._quarantined = {
                q.symbol for q in self._reconciliation_result.quarantined
            }
            if self._quarantined:
                logger.warning(
                    "QuantCoordinator: %d paper position(s) quarantined "
                    "(not in active universe): %s",
                    len(self._quarantined), sorted(self._quarantined),
                )
            for symbol in symbols:
                self._spawn_engine(symbol)
            # Startup reconciliation: rebuild each engine's state from its event store
            with self._lock:
                for eng in self._engines.values():
                    try:
                        eng.startup_reconcile()
                    except Exception:
                        logger.exception("startup_reconcile failed for %s", eng.symbol)
            self._start_eod_watchdog()
            self.started = True

    def rescan(self) -> list[str]:
        with self._lifecycle_lock:
            if not is_trading_day():
                logger.info(
                    "QuantCoordinator: rescan skipped — not an NSE/MCX trading day"
                )
                self._stop_engines()
                self._feed.set_symbols([])
                return []
            # Abandon-guard: stopping every engine while any holds an open
            # position would orphan that book at the broker (unmanaged, and
            # invisible to the EOD backstop once removed from the map). Refuse
            # the rescan — the intraday exit rules will free the slots.
            with self._lock:
                holding = [
                    sym for sym, eng in self._engines.items()
                    if _engine_has_open_position(eng)
                ]
            if holding:
                logger.warning(
                    "QuantCoordinator: rescan refused — %d engine(s) hold open "
                    "positions: %s (book would be abandoned unmanaged at the "
                    "broker); retry when flat",
                    len(holding), holding,
                )
                return []
            self._stop_engines()
            symbols = self._scan(force=True)
            self._refresh_gex()
            self._feed.set_symbols(symbols)
            for symbol in symbols:
                self._spawn_engine(symbol)
            self._start_eod_watchdog()
            return symbols

    def switch_symbol(self, old: str, new: str) -> bool:
        with self._lifecycle_lock:
            if old not in self._engines:
                return False
            if _engine_has_open_position(self._engines.get(old)):
                # Abandon-guard: stopping this engine while it holds a
                # position would leave the book at the broker with no
                # manager, and the removed engine is invisible to the EOD
                # square-off backstop. Refuse — retry once flat; the normal
                # exit rules (SL/TP/session close) will free the slot.
                logger.warning(
                    "switch_symbol %s -> %s refused: %s holds an open position "
                    "(book would be abandoned unmanaged at the broker)",
                    old, new, old,
                )
                return False
            self._stop_engine(old)
            self._feed.subscribe(new)
            self._spawn_engine(new)
            with self._lock:
                symbols = list(self._engines.keys())
            try:
                save_persisted_contracts(
                    symbols, self._contracts_file, exchange=self.config.get("exchange")
                )
            except Exception:
                logger.debug("Failed to persist updated contracts after switch_symbol", exc_info=True)
            return True

    def check_and_migrate_drifted_strikes(self, max_drift_steps: float = 2.5) -> list[str]:
        """Auto-migrates option contracts when spot drifts too far from strike (Fabio).
        
        Only migrates when no open position is held on the contract.
        """
        migrated: list[str] = []
        with self._lock:
            active_symbols = list(self._engines.keys())

        for symbol in active_symbols:
            if _is_futures_symbol(symbol):
                continue
            engine = self._engines.get(symbol)
            if engine is None or _engine_has_open_position(engine):
                # Do not migrate during active trade (real position truth —
                # see _engine_has_open_position)
                continue

            root = _canonical_root(symbol)
            spec = DEFAULT_REGISTRY.try_resolve(root)
            step = spec.strike_interval if spec and spec.strike_interval > 0 else 50.0

            # Find underlying spot
            futures_symbol = next((s for s in self._engines if _is_futures_symbol(s) and _canonical_root(s) == root), None)
            futures_engine = self._engines.get(futures_symbol) if futures_symbol else None
            spot = 0.0
            if futures_engine and futures_engine._aggregator.current_bar:
                spot = float(futures_engine._aggregator.current_bar.close)
            elif self.market_data and hasattr(self.market_data, "get_quote"):
                try:
                    q = self.market_data.get_quote(futures_symbol or root)
                    spot = float(getattr(q, "ltp", 0.0) or getattr(q, "price", 0.0) or 0.0)
                except Exception:
                    logger.warning("spot quote fallback failed for %s; spot stays at prior/zero", futures_symbol or root, exc_info=True)

            if spot <= 0:
                continue

            strike = extract_option_strike(symbol)
            if strike is not None and strike > 0:
                drift = abs(spot - strike)
                if drift > (max_drift_steps * step):
                    logger.info(
                        "🔄 [STRIKE DRIFT] %s strike=%.2f spot=%.2f drift=%.2f (limit=%.2f) — migrating",
                        symbol, strike, spot, drift, max_drift_steps * step,
                    )
                    migrated.append(symbol)

        if migrated:
            logger.info("QuantCoordinator: migrating %d drifted contract(s): %s", len(migrated), migrated)
            self.rescan()
        return migrated

    def check_and_rotate_dead_symbols(
        self, max_drift_steps: float = 2.5, stale_sec: float = 600.0
    ) -> list[tuple[str, str]]:
        """Identify dead, drifted, or stagnant option contracts and auto-rotate them to active ATM contracts.

        Guards:
        - Never rotates futures underlyings.
        - Never rotates an option with an active open position.
        - Only rotates when a valid, liquid replacement contract is found.
        """
        from quant.amt.session.symbol_registry import is_market_open
        from quant.amt.session.scanner import OptionScannerService

        rotated: list[tuple[str, str]] = []
        if self._stop.is_set():
            return rotated

        with self._lock:
            active_symbols = list(self._engines.keys())

        now = time.time()
        for symbol in active_symbols:
            if _is_futures_symbol(symbol):
                continue
            with self._lock:
                engine = self._engines.get(symbol)
            if engine is None or _engine_has_open_position(engine):
                # Never rotate a contract with an open book (real position
                # truth — see _engine_has_open_position).
                continue

            market = getattr(engine, "_market", None) or self.config.get("exchange", "NSE")
            if not is_market_open(exchange=market):
                continue

            root = _canonical_root(symbol)
            spec = DEFAULT_REGISTRY.try_resolve(root)
            step = spec.strike_interval if spec and spec.strike_interval > 0 else 50.0

            # 1. Check Strike Drift
            futures_symbol = next(
                (s for s in active_symbols if _is_futures_symbol(s) and _canonical_root(s) == root),
                None
            )
            futures_engine = self._engines.get(futures_symbol) if futures_symbol else None
            spot = 0.0
            if futures_engine and getattr(futures_engine, "_aggregator", None) and futures_engine._aggregator.current_bar:
                spot = float(futures_engine._aggregator.current_bar.close)
            elif self.market_data and hasattr(self.market_data, "get_quote"):
                try:
                    q = self.market_data.get_quote(futures_symbol or root)
                    spot = float(getattr(q, "ltp", 0.0) or getattr(q, "price", 0.0) or 0.0)
                except Exception:
                    logger.warning("spot quote fallback failed for %s; spot stays at prior/zero", futures_symbol or root, exc_info=True)

            is_drifted = False
            drift_val = 0.0
            if spot > 0:
                strike = extract_option_strike(symbol)
                if strike is not None and strike > 0:
                    drift_val = abs(spot - strike)
                    if drift_val > (max_drift_steps * step):
                        is_drifted = True

            # 2. Check Stale / Dead Market Stagnation
            last_tick_wall = float(getattr(engine, "_last_tick_wall", now) or now)
            is_stale = (now - last_tick_wall) > stale_sec
            amt_dto = getattr(engine, "last_amt_dto", None) or {}
            is_dead_state = str(amt_dto.get("marketState", "")).upper() in (MarketState.DEAD.value, "DEAD_MARKET")

            reason = ""
            if is_drifted:
                reason = f"Strike drift ({drift_val:.1f} > limit {max_drift_steps * step:.1f})"
            elif is_stale and is_dead_state:
                reason = f"Dead market state and stale feed ({now - last_tick_wall:.0f}s)"
            elif is_dead_state:
                reason = "Dead market state — searching for active momentum contract"

            if not reason:
                # Contract is healthy, active, and near ATM — do not rotate
                continue

            # Find replacement contract using OptionScanner
            try:
                scanner = OptionScannerService(self.market_data)
                exchange = spec.dhan_exchange if spec is not None else self.config.get("exchange", "NSE")
                tfm_forecasts = self._compute_timesfm_forecasts([root])
                results = scanner.scan_top_n(
                    n=4,
                    underlyings=[root],
                    exchange=exchange,
                    expiry_index=int(self.config.get("expiry_index", 0)),
                    strikes_around_atm=int(self.config.get("strikes_around_atm", 3)),
                    timesfm_forecasts=tfm_forecasts,
                )
                replacement = None
                with self._lock:
                    current_set = set(self._engines.keys())
                for r in results:
                    if r.symbol and r.symbol != symbol and r.symbol not in current_set and (r.ltp or 0) > 0:
                        replacement = r.symbol
                        break

                if replacement:
                    logger.info(
                        "🔄 [DYNAMIC ROTATION] %s is idle/dead (%s) -> rotating to %s",
                        symbol, reason, replacement,
                    )
                    if self.switch_symbol(symbol, replacement):
                        rotated.append((symbol, replacement))
            except Exception:
                logger.exception("check_and_rotate_dead_symbols: error rotating %s", symbol)

        return rotated

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._stop.set()
            eod_thread = getattr(self, "_eod_thread", None)
            if eod_thread is not None:
                eod_thread.join(timeout=5)
                self._eod_thread = None
            self._stop_engines()
            self._feed.close()
            # Join the bounded engine pool. Every engine task was already
            # waited (<=1s each) in _stop_engines after its gateway closed,
            # so remaining tasks finish in milliseconds. A fresh executor is
            # built lazily if a later start()/rescan reuses the coordinator.
            executor = getattr(self, "_executor", None)
            if executor is not None:
                try:
                    executor.shutdown(wait=True)
                finally:
                    self._executor = None
            self.started = False

    # -- snapshot helpers -----------------------------------------------------

    @staticmethod
    def _patch_positions_with_live_ltp(fold_positions, live):
        """Patch live LTP into open positions for real-time floating P&L."""
        if live.ltp is None or live.ltp <= 0:
            return fold_positions
        patched = []
        for p in fold_positions:
            p = dict(p)
            if p.get("status") == "OPEN":
                p["pnl"] = round(
                    (live.ltp - float(p.get("entryPrice", 0.0)))
                    * float(p.get("size", 0.0)),
                    2,
                )
                p["currentPrice"] = float(live.ltp)
            patched.append(p)
        return patched

    @staticmethod
    def _recompute_portfolio_equity(portfolio):
        """Recompute equity from balance + closed PnL + open PnL."""
        closed_pnl = sum(
            float(t.get("pnl", 0.0)) for t in portfolio.get("closedTrades", [])
        )
        open_pnl = sum(
            float(p.get("pnl", 0.0)) for p in portfolio.get("positions", [])
        )
        portfolio["equity"] = round(
            float(portfolio.get("balance", float(INITIAL_CAPITAL)))
            + closed_pnl + open_pnl,
            2,
        )
        return open_pnl

    @staticmethod
    def _patch_active_position(agent_dec, curr_px, pnl):
        """Patch live price/PnL into an existing activePosition decision."""
        agent_dec = dict(agent_dec)
        act_pos = dict(agent_dec["activePosition"])
        act_pos["currentPrice"] = curr_px
        act_pos["pnl"] = pnl
        agent_dec["activePosition"] = act_pos
        return agent_dec

    @staticmethod
    def _synthesize_position_mgmt(open_p, agent_dec, symbol, vs,
                                   entry_px, curr_px, sl_px, tp_px,
                                   pos_side, pnl, is_risk_free):
        """Synthesize a full POSITION_MANAGEMENT decision dict."""
        steps = list((agent_dec or {}).get("forecastSteps") or [pos_side] * 32)
        mean_fc = float(
            (agent_dec or {}).get("meanForecast")
            or (curr_px * (1.0 + FALLBACK_BAND_PCT if pos_side == "LONG" else 1.0 - FALLBACK_BAND_PCT))
        )
        q_spread = float((agent_dec or {}).get("quantileSpread") or 0.0)
        rr_achieved = (
            round(abs(curr_px - entry_px) / max(abs(entry_px - sl_px), 1e-4), 2)
            if sl_px > 0 and abs(entry_px - sl_px) > 0
            else 0.0
        )
        return {
            "role": "POSITION_MANAGEMENT",
            "action": "HOLD",
            "direction": pos_side,
            "setup": "POSITION_MGMT",
            "reason": "TREND_INTACT",
            "confidence": "High" if is_risk_free else "Medium",
            "confidenceScore": 0.85 if is_risk_free else 0.65,
            "rationale": (
                f"Position Management active on {symbol}: "
                f"Holding {pos_side} with entry at \u20b9{entry_px:,.2f}; "
                f"stop at \u20b9{sl_px:,.2f}."
            ),
            "forecastSteps": steps,
            "quantileSpread": round(q_spread, 4),
            "meanForecast": round(mean_fc, 2),
            "gateResults": (agent_dec or {}).get("gateResults") or [],
            "activePosition": {
                "side": pos_side,
                "entryPrice": entry_px,
                "currentPrice": curr_px,
                "pnl": pnl,
                "stopLoss": sl_px if sl_px > 0 else None,
                "takeProfit": tp_px if tp_px > 0 else None,
                "barsHeld": int(open_p.get("barsHeld", 0) or 0),
                "isRiskFree": is_risk_free,
                "rrAchieved": rr_achieved,
            },
            "dynamicTrailStop": sl_px if sl_px > 0 else None,
            "source": (agent_dec or {}).get("source") or "TIMESFM_3.0_NATIVE",
            "latencyMs": (agent_dec or {}).get("latencyMs") or 0.1,
            "modelLabel": "TimesFM-POSITION_MANAGEMENT",
            "modelVersions": {"timesfm": "3.0", "agent_role": "POSITION_MANAGEMENT", "engine": "native_direct"},
            "regime": str((vs.amt or {}).get("marketState") or MarketState.BALANCED.value),
            "timing": "REGULAR",
            "sizeFraction": 1.0,
            "latencyUs": 100,
        }

    @staticmethod
    def _build_position_mgmt_decision(open_p, live, agent_dec, symbol, vs):
        """Build a POSITION_MANAGEMENT agent_decision for an open position."""
        entry_px = float(open_p.get("entryPrice", 0.0))
        curr_px = float(
            live.ltp if live.ltp and live.ltp > 0
            else (open_p.get("currentPrice", entry_px) or entry_px)
        )
        sl_px = float(open_p.get("stopLoss", 0.0) or 0.0)
        tp_px = float(open_p.get("takeProfit", 0.0) or 0.0)
        pos_side = str(open_p.get("side", "LONG")).upper()
        mult = 1.0 if pos_side == "LONG" else -1.0
        pnl = float(
            open_p.get(
                "pnl",
                round((curr_px - entry_px) * abs(float(open_p.get("size", 1.0))) * mult, 2),
            )
        )
        is_risk_free = (
            (sl_px >= entry_px) if pos_side == "LONG"
            else (sl_px > 0 and sl_px <= entry_px)
        )
        market_state = str((vs.amt or {}).get("marketState") or "").upper()
        if market_state == "CHOP":
            decision = QuantCoordinator._synthesize_position_mgmt(
                open_p, agent_dec, symbol, vs,
                entry_px, curr_px, sl_px, tp_px, pos_side, pnl, is_risk_free,
            )
            decision["action"] = "EXIT" if pnl <= 0 else "TIGHTEN_SL"
            decision["reason"] = "CHOP_EXIT" if pnl <= 0 else "CHOP_TIGHTEN"
            decision["confidence"] = "High"
            decision["confidenceScore"] = 0.85
            decision["rationale"] = (
                f"AMT CHOP detected on {symbol}: do not hold through a non-directional auction. "
                f"Protect/exit the {pos_side} position at {curr_px:,.2f}."
            )
            return decision
        if (
            agent_dec and isinstance(agent_dec, dict)
            and agent_dec.get("role") == "POSITION_MANAGEMENT"
            and agent_dec.get("activePosition")
        ):
            return QuantCoordinator._patch_active_position(agent_dec, curr_px, pnl)
        return QuantCoordinator._synthesize_position_mgmt(
            open_p, agent_dec, symbol, vs,
            entry_px, curr_px, sl_px, tp_px, pos_side, pnl, is_risk_free,
        )

    @staticmethod
    def _align_agent_decision(agent_dec, fold_positions, live, symbol, vs):
        """Align agent_decision with actual open position state."""
        open_pos_list = [p for p in fold_positions if p.get("status") == "OPEN"]
        if open_pos_list:
            return QuantCoordinator._build_position_mgmt_decision(
                open_pos_list[0], live, agent_dec, symbol, vs,
            )
        if (
            agent_dec and isinstance(agent_dec, dict)
            and agent_dec.get("role") == "POSITION_MANAGEMENT"
        ):
            agent_dec = dict(agent_dec)
            agent_dec["role"] = "SCANNING"
            agent_dec["action"] = "FLAT"
            agent_dec["setup"] = "AMT_AUCTION"
            agent_dec["activePosition"] = None
            agent_dec["dynamicTrailStop"] = None
            agent_dec["modelLabel"] = "TimesFM-SCANNING"
        return agent_dec

    @staticmethod
    def _compose_view_state(vs, symbol, portfolio, live, engine, agent_dec):
        """Merge live data into the folded view state."""
        return replace(
            vs,
            symbol=symbol,
            portfolio=portfolio,
            tick=live.tick if live.tick is not None else vs.tick,
            ltp=live.ltp if live.ltp is not None else vs.ltp,
            oi=live.oi if live.oi is not None else vs.oi,
            depth=live.depth if live.depth is not None else (getattr(engine, "latest_depth", None) or vs.depth),
            amt=getattr(engine, "latest_amt", None),
            quant_decision=getattr(engine, "latest_quant_decision", None),
            agent_decision=agent_dec,
        )

    @staticmethod
    def _emit_hotpath_trace(symbol, fold_positions, open_pnl, live):
        """Emit an opt-in hot-path trace for the WS transport."""
        if not _HOTPATH.enabled:
            return
        _HOTPATH.try_emit(
            symbol, "snapshot",
            positions=len(fold_positions),
            open_pnl=round(float(open_pnl), 2),
            ltp=float(live.ltp) if live.ltp is not None else None,
            has_depth=live.depth is not None,
        )

    # -- end snapshot helpers -------------------------------------------------

    def snapshot(self, symbol: str) -> dict:
        """Compose the WS snapshot for one symbol.

        Single-authority composition:

        - **Positions, risk, portfolio** come from ``EventStore.fold() →
          project_state()`` — the sole source of truth for trading state.
        - **Per-tick live fields** (ltp/oi/depth/forming candle) come from
          the engine's ``LiveQuoteCache`` — values an event-fold cannot know
          between bar closes.
        - **AMT, decisions** come from the engine's ``latest_*`` attributes —
          updated inline by ``_emit()`` as events flow.
        """
        with self._lock:
            engine = self._engines.get(symbol)
        if engine is None:
            return {"_symbol": symbol}
        try:
            vs = project_state(engine.event_store.fold())
        except Exception as e:
            logger.warning(
                "snapshot: EventStore.fold failed for %s (%s) — canonical projection unavailable",
                symbol, e,
            )
            vs = project_state(EngineState(symbol=symbol))
            vs = replace(
                vs,
                risk_state={
                    **(vs.risk_state or {}),
                    "canonicalState": "DEGRADED_CANONICAL_FOLD_UNAVAILABLE",
                    "canonicalError": type(e).__name__,
                },
            )
        if getattr(engine, "persistence_degraded", False):
            vs = replace(
                vs,
                risk_state={
                    **(vs.risk_state or {}),
                    "canonicalState": "DEGRADED_EVENT_APPEND_FAILED",
                    "canonicalError": type(getattr(engine, "persistence_failure", None)).__name__,
                },
            )
        live = engine.live_cache.snapshot(symbol)
        fold_positions = list((vs.portfolio or {}).get("positions", []))
        fold_positions = self._patch_positions_with_live_ltp(fold_positions, live)
        portfolio = dict(vs.portfolio or {})
        portfolio["positions"] = fold_positions
        open_pnl = self._recompute_portfolio_equity(portfolio)
        agent_dec = self._align_agent_decision(
            engine.latest_agent_decision, fold_positions, live, symbol, vs,
        )
        vs = self._compose_view_state(vs, symbol, portfolio, live, engine, agent_dec)
        self._emit_hotpath_trace(symbol, fold_positions, open_pnl, live)
        return view_state_to_ws(vs)

    def symbols(self) -> list[str]:
        with self._lock:
            return list(self._engines.keys())

    # =========================================================================
    # 4. HEALTH & READINESS — crashed engines, staleness, readiness status
    # =========================================================================
    def crashed_engines(self) -> list[str]:
        """Symbols whose engine thread died from an exception (F1 fix).

        Exposed for the /health endpoint — a dead engine previously meant a
        symbol silently stopped trading with no observable signal.
        """
        with self._lock:
            return sorted(
                sym for sym, eng in self._engines.items()
                if getattr(eng, "_crashed", False)
            )

    def unresolved_startup_issues(self) -> set[str]:
        """Orders/recovery conditions that must be resolved before trading."""
        return set(self._unresolved_startup)

    def quarantined_positions(self) -> set[str]:
        """Symbols of persisted paper positions not in the active universe.

        Exposed for the /health endpoint and readiness checks. These positions
        are preserved in storage but not restored into any engine.
        """
        return set(self._quarantined)

    def readiness(self) -> tuple[ReadinessStatus, dict[str, str]]:
        """Compute readiness status for the backend health router.

        Wraps readiness_status() with self as the coordinator.
        """
        return readiness_status(self)

    def stale_engines(self, threshold_sec: float = 300.0) -> list[str]:
        """Symbols whose engine has consumed no tick for ``threshold_sec``.

        Exposed for the /health endpoint — complements ``crashed_engines``:
        a starved-but-alive engine (thread running, feed silently not routing
        its ticks) reports neither as crashed nor in any journal, so it hid
        behind an "ok" health check. Only evaluated while that symbol's market
        is open (ticks are expected), so it does not false-alarm after close.
        """
        from quant.amt.session.symbol_registry import is_market_open

        now = time.time()
        with self._lock:
            engines = list(self._engines.items())
        stale = []
        for sym, eng in engines:
            market = getattr(eng, "_market", None)
            if not is_market_open(exchange=market):
                continue
            last = float(getattr(eng, "_last_tick_wall", now) or now)
            if now - last > threshold_sec:
                stale.append(sym)
        return sorted(stale)

    def emergency_halt(self, reason: str = "emergency halt", *, force_close: bool = False) -> int:
        """Externally halt every engine's SessionRisk (SIGTERM flatten path).

        Audit D-RISK-03: main.py's SIGTERM handler used to set
        ``eng._risk_halted`` — an attribute QuantEngine never had — behind a
        hasattr() guard, so the emergency stop was a silent no-op. The real
        authority is each engine's SessionRisk; halting there blocks new
        entries at Guard 0 of _decide() on every subsequent bar and persists
        across restarts (SessionRisk.halt saves to kv).

        When ``force_close=True``, each engine's open position is closed at
        the last traded price via PaperOMS before halting risk.  This is
        appropriate for SIGTERM / panic-shutdown where leaving positions
        open until session-close is unacceptable risk.  Returns the number
        of engines halted so callers can log/verify.
        """
        halted = 0
        closed = 0
        with self._lock:
            engines = list(self._engines.values())
        for eng in engines:
            risk = getattr(eng, "_risk", None)
            if risk is not None and hasattr(risk, "halt"):
                try:
                    risk.halt(f"external/emergency: {reason}")
                    halted += 1
                except Exception:
                    logger.exception("emergency_halt failed for %s", eng.symbol)

            # Force-close open positions when requested (SIGTERM / panic).
            if force_close:
                try:
                    # C5: route through the engine's own lock-serialized,
                    # pyramid-aware flatten (the same path the EOD watchdog
                    # uses). The previous inline oms.close() ran WITHOUT
                    # engine._close_lock, so it could race the engine thread's
                    # blocking close and double-submit an opposing MARKET order
                    # (flipping the book), and it bypassed PositionManager so
                    # pyramid add-ons were orphaned.
                    if eng.force_close_position(f"EMERGENCY_HALT: {reason}"):
                        closed += 1
                except Exception:
                    logger.exception("emergency_halt force_close failed for %s", eng.symbol)

        if closed:
            logger.warning("emergency_halt: force-closed %d position(s) across %d engine(s)", closed, halted)
        return halted

    # =========================================================================
    # 6. SCHEDULERS — history seed scheduler, EOD watchdog
    # =========================================================================
    def _squareoff_deadline(self, market) -> datetime | None:
        """IST datetime at which the EOD backstop fires (exchange close − N min)."""
        try:
            minutes = float(self.config.get("eod_squareoff_minutes_before_close", 15))
        except (TypeError, ValueError):
            minutes = 15.0
        close_t = MCX_SESSION_CLOSE if str(market).upper() == "MCX" else NSE_SESSION_CLOSE
        now = datetime.now(IST)
        close_dt = datetime.combine(now.date(), close_t).replace(tzinfo=IST)
        return close_dt - timedelta(minutes=minutes)

    def eod_square_off(self, reason: str = "EOD_SQUARE_OFF") -> int:
        """Force-flatten every engine whose market has passed its EOD backstop.

        Intraday-only guarantee: the bar-driven SESSION_CLOSE (Phase 5) closes
        positions while bars flow, but a dead/starved feed near the close could
        carry a position overnight. This time-driven backstop is independent of
        tick/bar flow — it fires on the wall clock. Flatten-only: it does NOT
        persist a risk halt (session gates already block new entries in Phase 5,
        and next-day trading must stay unaffected). Idempotent — safe to call
        repeatedly; engines with no open position are skipped. Returns the
        number of positions force-closed this pass.
        """
        closed = 0
        now = datetime.now(IST)
        with self._lock:
            engines = list(self._engines.values())
        for eng in engines:
            market = getattr(eng, "_market", None) or self.config.get("exchange", "NSE")
            deadline = self._squareoff_deadline(market)
            if deadline is None or now < deadline:
                continue
            # Check if engine has an open position (via state or position manager)
            has_position = (
                getattr(eng, "state", None) is not None and eng.state.position is not None
            ) or (
                getattr(eng, "_get_position_manager", None) is not None
                and eng._get_position_manager().pyramid_positions
            )
            if not has_position:
                continue
            try:
                if eng.force_close_position(reason):
                    closed += 1
            except Exception:
                logger.exception("eod_square_off: force-close failed for %s", eng.symbol)
        if closed:
            logger.warning("eod_square_off: force-closed %d position(s) (%s)", closed, reason)
        return closed

    def _intraday_reconcile(self) -> list[str]:
        """C4: periodic broker-vs-engine book check during the session.

        Detects drift between the broker's positions and the engines' positions
        (a fill the engine missed, a manual broker-side intervention, or an
        orphaned order). Detect-and-alert ONLY — it does not auto-halt or
        auto-close, because an automatic reaction to a transient desync could be
        worse than the drift itself. Entries/exits are synchronous (the engine
        book updates only after the broker confirms), so a drift here is a real
        discrepancy worth operator attention. Returns the list of drift
        descriptions (empty when the books agree) so callers/tests can inspect.
        """
        if not self.config.get("live_oms_enabled") or self.broker is None:
            return []
        try:
            broker_positions = self.broker.get_positions() or []
        except Exception:
            logger.debug("intraday reconcile: broker.get_positions() failed — skipping")
            return []

        broker_by_symbol: dict[str, float] = {}
        for bp in broker_positions:
            sym = canonical_key(str(getattr(bp, "symbol", "") or ""))
            if sym:
                broker_by_symbol[sym] = _signed_broker_qty(bp)

        with self._lock:
            engines = dict(self._engines)

        engine_by_symbol: dict[str, float] = {}
        for sym, eng in engines.items():
            pos = eng.state.position
            pm = eng._get_position_manager()
            pyramids = pm.pyramid_positions or []
            if pos is None and not pyramids:
                continue
            net = float(pos.size) if pos is not None else 0.0
            for pyr in pyramids:
                net += float(getattr(pyr, "size", 0.0))
            engine_by_symbol[canonical_key(sym)] = net

        # Shared presence-compare from the single reconciliation service.
        # Drift strings are unchanged (pinned by audit-regression tests).
        broker_only, both, engine_only = partition_keys(
            broker_by_symbol, engine_by_symbol
        )
        drift = []
        for sym in sorted(broker_only):
            drift.append(
                f"{sym}: broker={broker_by_symbol[sym]} but no engine position (orphan?)"
            )
        for sym in sorted(both):
            broker_qty = broker_by_symbol[sym]
            engine_qty = engine_by_symbol[sym]
            if abs(broker_qty - engine_qty) > 0.01:
                drift.append(f"{sym}: broker={broker_qty} vs engine={engine_qty}")
        for sym in sorted(engine_only):
            drift.append(
                f"{sym}: engine={engine_by_symbol[sym]} but broker has none (desync?)"
            )

        if drift:
            logger.warning(
                "INTRADAY RECONCILE: %d book drift(s) detected (detect-only, no "
                "auto-action): %s",
                len(drift), "; ".join(drift),
            )
        return drift

    def _periodic_state_reconcile(self) -> None:
        """Periodic state-vs-event-store reconciliation across all engines.

        Delegates to each engine's ``periodic_reconcile()`` (runtime.QuantEngine).
        Logs drift and risk-event emissions so ops can detect state desync
        between the in-memory EngineState and the EventStore journal.
        """
        with self._lock:
            engines = list(self._engines.values())
        for eng in engines:
            try:
                result = eng.periodic_reconcile()
                if result.has_drift:
                    logger.warning(
                        "PERIODIC RECONCILE %s: drift detected — %s",
                        eng.symbol, "; ".join(result.discrepancies),
                    )
            except Exception:
                # Reconciliation failures must be visible to ops — a silent
                # DEBUG log would hide drift detection outages. Log at WARNING
                # so the watchdog failure surfaces in production logs.
                logger.warning(
                    "periodic_reconcile FAILED for %s", eng.symbol, exc_info=True
                )

    def _notify_watchdog(self, where: str, exc: Exception) -> None:
        """Safely invoke the dead-man hook (never raises)."""
        cb = getattr(self, "_on_watchdog_error", None)
        if callable(cb):
            try:
                cb(where, exc)
            except Exception:  # silent-except - watchdog callback must never raise
                pass

    def _eod_watchdog_loop(self, poll_sec: float = 30.0) -> None:
        """Background EOD square-off and dynamic symbol rotation watchdog.

        Polls every ``poll_sec``:
        - Force-flattens any still-open position once its market passes square-off deadline.
        - Automatically detects dead/drifted option symbols and rotates them to active ATM contracts.
        Exits when coordinator stop event is set.
        """
        logger.info(
            "Coordinator watchdog started (square-off %s min before close, auto-rotation enabled)",
            self.config.get("eod_squareoff_minutes_before_close", 15),
        )
        rotation_counter = 0
        recon_counter = 0
        periodic_recon_counter = 0
        while not self._stop.is_set():
            try:
                self.eod_square_off()
            except Exception as exc:
                logger.exception("EOD watchdog: square-off pass failed")
                self._notify_watchdog("square-off", exc)

            # Dynamic Contract Rotation: runs every ~60s (every 2nd pass)
            rotation_counter += 1
            if rotation_counter >= 2:
                rotation_counter = 0
                try:
                    self.check_and_rotate_dead_symbols()
                except Exception as exc:
                    logger.exception("Dynamic rotation watchdog: pass failed")
                    self._notify_watchdog("rotation", exc)

            # C4: intraday broker-vs-engine book reconciliation, every ~60s.
            # Detect-and-alert only (no auto-action) — see _intraday_reconcile.
            recon_counter += 1
            if recon_counter >= 2:
                recon_counter = 0
                try:
                    self._intraday_reconcile()
                except Exception as exc:
                    logger.exception("Intraday reconcile watchdog: pass failed")
                    self._notify_watchdog("intraday", exc)

            # Periodic state-vs-event-store reconciliation, every ~120s (every 4th pass).
            periodic_recon_counter += 1
            if periodic_recon_counter >= 4:
                periodic_recon_counter = 0
                try:
                    self._periodic_state_reconcile()
                except Exception as exc:
                    logger.exception("Periodic state reconcile watchdog: pass failed")
                    self._notify_watchdog("periodic", exc)

            self._stop.wait(poll_sec)
        logger.info("Coordinator watchdog stopped")

    def _start_eod_watchdog(self) -> None:
        if self._eod_thread is not None and self._eod_thread.is_alive():
            return
        self._eod_thread = threading.Thread(
            target=self._eod_watchdog_loop,
            name="eod-squareoff-watchdog",
            daemon=True,
        )
        self._eod_thread.start()

    def unhalt_all(self) -> int:
        """Clear external halt state on all running engines."""
        unhalted = 0
        with self._lock:
            for eng in self._engines.values():
                risk = getattr(eng, "_risk", None)
                if risk is not None and hasattr(risk, "unhalt"):
                    risk.unhalt()
                    unhalted += 1
        logger.info("unhalt_all: cleared risk halts across %d engine(s)", unhalted)
        return unhalted

    def journal_consecutive_failures(self) -> int:
        """Max consecutive journal append failures across engines (for /health)."""
        with self._lock:
            engines = list(self._engines.values())
        n = 0
        for eng in engines:
            journal = getattr(eng, "_journal", None)
            n = max(n, int(getattr(journal, "consecutive_failures", 0) or 0))
        return n

    def check_spot_drift(self, underlying: str, spot_price: float) -> bool:
        """Detect when price moves > 1.5 strike intervals away from active option strikes."""
        spec = DEFAULT_REGISTRY.try_resolve(underlying)
        step = spec.strike_interval if spec is not None else 50
        strikes = []
        with self._lock:
            active_symbols = list(self._engines.keys())
        for sym in active_symbols:
            if _is_futures_symbol(sym):
                continue
            if sym.upper().startswith(underlying.upper()):
                stk = extract_option_strike(sym)
                if stk is not None and stk > 0:
                    strikes.append(stk)
        if not strikes:
            return False
        mean_strike = sum(strikes) / len(strikes)
        return abs(spot_price - mean_strike) > 1.5 * step

    def _resolve_futures_symbols(self) -> list[str]:
        """Resolve active front-month futures for the configured underlyings."""
        symbols = []
        underlyings = self.config.get("futures_underlyings") or self.config.get("underlyings", [])
        for u in underlyings:
            fut_sym = None
            spec = DEFAULT_REGISTRY.try_resolve(u)
            exchange = spec.dhan_exchange if spec is not None else self.config.get("exchange", "NSE")
            if hasattr(self.market_data, "get_nearest_futures"):
                fut_sym = self.market_data.get_nearest_futures(u, exchange=exchange)
            if not fut_sym:
                # Dynamic month FUT symbol fallback (e.g. "NIFTY AUG FUT" / "CRUDEOIL SEP FUT")
                now = datetime.now(tz=IST)
                month_str = now.strftime("%b").upper()
                fut_sym = f"{u.upper()} {month_str} FUT"
            if fut_sym and fut_sym not in symbols:
                symbols.append(fut_sym)
        return symbols

    def _persisted_matches_futures(
        self, persisted: list[str], futures_symbols: list[str]
    ) -> bool:
        """Whether a cached selection still has the required futures topology."""
        if not self._persisted_within_configured_n(persisted):
            return False
        futures = [s for s in persisted if _is_futures_symbol(s)]
        if set(futures) != set(futures_symbols):
            return False
        roots = {_canonical_root(symbol) for symbol in futures_symbols}
        return all(
            _canonical_root(symbol) in roots
            for symbol in persisted
            if not _is_futures_symbol(symbol)
        )

    def _persisted_within_configured_n(self, persisted: list[str]) -> bool:
        return (
            len(persisted) <= self.config.get("n", 8)
            and len({symbol.upper() for symbol in persisted}) == len(persisted)
        )

    def _scan(self, *, force: bool = False) -> list[str]:
        """Select active contracts: reuse today's persisted selection unless a
        fresh scan is forced (e.g. an explicit rescan request), otherwise run
        the hybrid futures + option scanner and persist the result."""
        futures_symbols: list[str] = []
        if self.config.get("include_futures", True):
            futures_symbols = self._resolve_futures_symbols()
            logger.info("QuantCoordinator: resolved futures contracts: %s", futures_symbols)

        total_slots = self.config.get("n", 8)
        if len(futures_symbols) > total_slots:
            raise ValueError(
                f"configured n={total_slots} cannot fit {len(futures_symbols)} required futures"
            )

        if not force:
            persisted = load_persisted_contracts(
                self._contracts_file, exchange=self.config.get("exchange")
            )
            if persisted and self._persisted_within_configured_n(persisted) and (
                not self.config.get("include_futures", True)
                or self._persisted_matches_futures(persisted, futures_symbols)
            ):
                logger.info(
                    "QuantCoordinator: reusing persisted contracts: %s", persisted
                )
                if self.config.get("include_futures", True):
                    return futures_symbols + [
                        symbol for symbol in persisted if not _is_futures_symbol(symbol)
                    ]
                return persisted

        # Allocate remaining scanner slots to options
        n_options = max(0, total_slots - len(futures_symbols))
        option_symbols: list[str] = []
        if n_options:
            scanner = OptionScannerService(self.market_data)
            tfm_forecasts = self._compute_timesfm_forecasts(self.config["underlyings"])
            results = scanner.scan_top_n(
                n=n_options,
                underlyings=self.config["underlyings"],
                exchange=self.config["exchange"],
                expiry_index=self.config["expiry_index"],
                strikes_around_atm=self.config["strikes_around_atm"],
                underlying_priority=self.config.get("underlying_priority"),
                timesfm_forecasts=tfm_forecasts,
            )
            option_symbols = [
                r.symbol for r in results if (r.ltp or 0) > 0
            ][:n_options]
        symbols = futures_symbols + option_symbols
        if symbols:
            save_persisted_contracts(
                symbols, self._contracts_file, exchange=self.config.get("exchange")
            )
            logger.info("QuantCoordinator: persisted active contracts: %s", symbols)
        return symbols

    def _refresh_gex(self) -> None:
        """Compute startup GEX per underlying root.

        GEX needs option-chain data, so it runs its own lightweight scanner pass.
        It is deliberately kept OUT of ``_scan()`` so that persisted-contract
        reuse stays scanner-free and deterministic (guarded by
        tests/quant/test_multi_engine_startup.py). Best-effort: a failure here
        only means engines run without GEX enrichment, never a startup crash.
        """
        try:
            scanner = OptionScannerService(self.market_data)
            chains: dict[str, object] = {}
            scanner.scan_top_n(
                n=1,
                underlyings=self.config["underlyings"],
                exchange=self.config["exchange"],
                expiry_index=self.config["expiry_index"],
                strikes_around_atm=self.config["strikes_around_atm"],
                chains_out=chains,
            )
            for root_k, chain_obj in chains.items():
                gex_obj = getattr(chain_obj, "gex", None)
                if gex_obj is not None:
                    self._gex_by_root[root_k.upper()] = gex_obj
        except Exception:
            logger.debug("Failed computing startup GEX", exc_info=True)

    def _compute_timesfm_forecasts(self, roots: list[str]) -> dict[str, Any]:
        """Compute TimesFM 3.0 forecasts for underlying roots to guide option selection.

        Off-path sidecar: disabled by default (``TIMESFM_CONTRACT_SELECTION=false``).
        When enabled, results are cached for 15 minutes so rotation/startup scans
        never block the hot path behind a PyTorch forward pass per call.
        """
        forecasts: dict[str, Any] = {}
        tfm_enabled = (
            os.getenv("TIMESFM_CONTRACT_SELECTION", "false").strip().lower() in ("1", "true", "yes")
            or os.getenv("TIMESFM_ADVISOR_ENABLED", "false").strip().lower() in ("1", "true", "yes")
        )
        if not tfm_enabled:
            return forecasts

        # 15-minute sidecar cache: rotation/startup scans reuse the last
        # forecast instead of blocking behind one forward pass per call.
        _now = time.time()
        _ttl = 900.0
        try:
            with self._lock:
                _cache = getattr(self, "_tfm_forecast_cache", None) or {}
                _ts = float(getattr(self, "_tfm_forecast_cache_ts", 0.0) or 0.0)
            if _cache and (_now - _ts) < _ttl and all(r in _cache for r in roots):
                return {r: _cache[r] for r in roots if r in _cache}
        except Exception:  # silent-except - cache read failure falls through to recompute
            pass

        try:
            from quant.decision.timesfm_engine import (
                _TIMESFM_INFER_LOCK,
                get_timesfm_model,
            )
            from quant.decision.timesfm_forecast_factory import build_forecast
            import numpy as np

            model = get_timesfm_model()
            if model is None:
                return forecasts

            for root in roots:
                prices: list[float] = []
                with self._lock:
                    futures_symbol = next(
                        (s for s in self._engines if _is_futures_symbol(s) and _canonical_root(s) == root),
                        None,
                    )
                    eng = self._engines.get(futures_symbol) if futures_symbol else None
                if eng is not None and hasattr(eng, "_aggregator") and eng._aggregator:
                    recent_bars = getattr(eng._aggregator, "bars", []) or []
                    if recent_bars:
                        prices = [float(b.close) for b in recent_bars[-32:]]

                if len(prices) < 32 and self.market_data is not None:
                    fut_sym = futures_symbol or f"{root.upper()} {datetime.now(tz=IST).strftime('%b').upper()} FUT"
                    if hasattr(self.market_data, "fetch_history"):
                        try:
                            from quant.contracts.sync_boundary import invoke_sync_or_async
                            candles = invoke_sync_or_async(
                                self.market_data.fetch_history,
                                fut_sym,
                                interval="5m",
                                limit=32,
                            )
                            if not candles:
                                candles = invoke_sync_or_async(
                                    self.market_data.fetch_history,
                                    root,
                                    interval="5m",
                                    limit=32,
                                )
                            if candles:
                                closes = [float(getattr(c, "close", 0.0) or getattr(c, "c", 0.0) or 0.0) for c in candles]
                                prices = [c for c in closes if c > 0]
                        except Exception:
                            logger.warning("market-data candle seed for %s failed", root, exc_info=True)
                    if len(prices) < 32 and hasattr(self.market_data, "get_broker") and hasattr(self.market_data, "_make_instrument"):
                        try:
                            raw_b = self.market_data.get_broker()
                            if hasattr(raw_b, "get_historical"):
                                inst = self.market_data._make_instrument(fut_sym or root)
                                end_dt = datetime.now(tz=IST)
                                start_dt = end_dt - timedelta(days=5)
                                df = raw_b.get_historical(instrument=inst, from_date=start_dt, to_date=end_dt, interval="5")
                                if df is not None and not df.empty and "close" in df.columns:
                                    prices = [float(c) for c in df["close"].tail(32)]
                        except Exception:
                            logger.warning("raw-broker historical seed for %s failed", root, exc_info=True)

                if prices:
                    if len(prices) < 32:
                        prices = [prices[0]] * (32 - len(prices)) + prices
                    np_prices = np.array(prices[-32:], dtype=np.float32)
                    with _TIMESFM_INFER_LOCK:
                        res = model.predict(context=np_prices, horizon=32, return_quantiles=True)
                    quantiles = getattr(res, "quantiles", None)
                    curr_price = float(np_prices[-1])
                    forecasts[root] = build_forecast(quantiles, curr_price, 32, 5.0)
                    logger.info("TimesFM forecast computed for %s (drift=%.2f%%, spread=%.2f)", root, forecasts[root].pct_change * 100, forecasts[root].q_spread)
        except Exception as e:
            logger.debug("Failed computing TimesFM forecasts for option selection: %s", e)

        if forecasts:
            try:
                with self._lock:
                    _prev = getattr(self, "_tfm_forecast_cache", None) or {}
                    _prev.update(forecasts)
                    self._tfm_forecast_cache = _prev
                    self._tfm_forecast_cache_ts = time.time()
            except Exception:  # silent-except - cache write failure should not block main flow
                pass
        return forecasts


    def _session_profile_for(self, symbol: str) -> str:
        """NSE/MCX session clock for *symbol* — never the coordinator's mode flag."""
        return DEFAULT_REGISTRY.resolve(symbol).session_profile

    def _cost_profile_for(self, symbol: str) -> dict | None:
        """Return the validated paper cost profile for a contract root."""
        profiles = self.config.get("cost_profiles") or {}
        root = _canonical_root(symbol)
        profile = profiles.get(root) or profiles.get(str(root).upper())
        if profile is None:
            profile = self.config.get("cost_profile")
        return dict(profile) if profile is not None else None

    def _contract_for(self, symbol: str) -> ContractRef:
        """Build the broker-neutral identity used by paper execution.

        Option expiry/strike come from the scanned contract symbol. If a
        provider has richer metadata it may supply an explicit expiry through
        ``contract_expiries``; missing option identity is a startup error.
        """
        spec = DEFAULT_REGISTRY.resolve(symbol)
        expiry = parse_contract_expiry(symbol)
        expiry_text = expiry.isoformat() if expiry is not None else ""
        configured_expiry = (self.config.get("contract_expiries") or {}).get(symbol)
        expiry_text = str(configured_expiry or expiry_text).strip()
        option = is_option_contract(symbol)
        strike = extract_option_strike(symbol) if option else None
        option_type = ""
        if option:
            if is_call_symbol(symbol):
                option_type = "CE"
            elif is_put_symbol(symbol):
                option_type = "PE"
            if strike is None or not expiry_text or not option_type:
                raise ValueError(
                    f"missing option contract metadata for {symbol!r}: "
                    "expiry, strike, and option type are required"
                )
        elif not expiry_text:
            expiry_text = str((self.config.get("contract_expiries") or {}).get(symbol) or "").strip()
            if not expiry_text:
                # 1. Try broker symbol mapper if available
                try:
                    broker = getattr(self.market_data, "get_broker", lambda: None)()
                    mapper = getattr(broker, "_symbol_mapper", None)
                    if mapper is not None:
                        inst = mapper._by_trading_symbol.get(symbol)
                        if not inst:
                            root = _canonical_root(symbol)
                            for cand in mapper._by_security_id.values():
                                if (cand.symbol == root or cand.trading_symbol.startswith(f"{root} ")) and (cand.trading_symbol == symbol or symbol in cand.trading_symbol):
                                    if cand.expiry_date:
                                        inst = cand
                                        break
                        if inst and getattr(inst, "expiry_date", None):
                            expiry_text = inst.expiry_date.isoformat()
                except Exception:
                    logger.warning("contract expiry lookup failed; expiry left unset", exc_info=True)

            # 2. Fallback: derive month date from symbol (e.g. "CRUDEOIL SEP FUT")
            if not expiry_text:
                import calendar
                months = {
                    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
                    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
                }
                today = datetime.now(tz=IST).date()
                for tok in symbol.upper().split():
                    if tok in months:
                        m = months[tok]
                        y = today.year if m >= today.month else today.year + 1
                        last_day = calendar.monthrange(y, m)[1]
                        expiry_text = date(y, m, last_day).isoformat()
                        break

            # 3. Final fallback: today's date
            if not expiry_text:
                expiry_text = datetime.now(tz=IST).date().isoformat()
        return ContractRef(
            symbol=str(symbol),
            exchange=spec.dhan_exchange,
            expiry=expiry_text,
            lot_size=int(self._resolve_lot_size(symbol)),
            tick_size=float(self._resolve_tick_size(symbol)),
            strike=strike,
            option_type=option_type,
        )

    def _quote_provider_for(self, engine):
        """Read the latest executable quote from the engine's canonical depth."""
        def quote():
            book = getattr(engine, "_last_depth", None)
            if book is None or not book.bids or not book.asks:
                return None
            return float(book.bids[0].price), float(book.asks[0].price)
        return quote

    def _resolve_tick_size(self, symbol: str) -> float:
        """InstrumentRegistry tick. Unknown roots raise — never 0.05."""
        return DEFAULT_REGISTRY.resolve(symbol).tick_size

    def _resolve_lot_size(self, symbol: str) -> float:
        """InstrumentRegistry lot for MCX/derivatives, else broker lot if > 1. Unknown roots raise."""
        spec = DEFAULT_REGISTRY.try_resolve(symbol)
        if spec is not None and (spec.exchange == "MCX" or spec.lot_size > 1):
            return float(spec.lot_size)
        try:
            raw = self.market_data.get_lot_size(symbol)
            lot_size = float(raw or 0)
            if lot_size > 1:
                return lot_size
        except Exception:
            logger.warning("lot-size lookup failed for %s; using default", symbol, exc_info=True)
        if spec is not None:
            return float(spec.lot_size)
        return float(DEFAULT_REGISTRY.resolve(symbol).lot_size)

    # ------------------------------------------------------------------
    # Bounded engine pool
    # ------------------------------------------------------------------

    # =========================================================================
    # 2. ENGINE MANAGEMENT — spawn, stop, thread pool, gateway lifecycle
    # =========================================================================
    def _ensure_executor(self) -> ThreadPoolExecutor:
        """Return the coordinator's engine pool, creating it lazily.

        Threads are allocated lazily on first submit and never exceed
        ``self._max_threads``. ``stop()`` shuts the executor down and clears
        the reference so a later lifecycle phase builds a fresh one.
        """
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self._max_threads, thread_name_prefix="quant-engine"
            )
        return self._executor

    def _start_engine_loop(self, engine) -> Future | None:
        """Submit an engine's blocking run loop to the bounded pool.

        Seam: tests that construct engines without running them (they only
        assert construction wiring) replace this method with a no-op so no
        pool worker blocks on a tick queue mid-assertion.
        """
        future = self._ensure_executor().submit(engine.run)
        future.add_done_callback(_retrieve_future_exception)
        return future

    @staticmethod
    def _wait_run_handle(handle, symbol: str) -> None:
        """Wait for an engine to finish stopping, bounded to ~1s.

        ``handle`` is either a pool Future (production) or a plain Thread
        (legacy test doubles that pre-seed ``coord._threads``). A hung engine
        (e.g. stuck in a broker call) must never block rescan/stop forever;
        the coordinator's ``stop()`` joins stragglers via the pool shutdown.
        """
        if handle is None:
            return
        join = getattr(handle, "join", None)
        if callable(join):
            try:
                join(timeout=1.0)
            except RuntimeError:  # silent-except - thread join timeout is best-effort on shutdown
                pass
            return
        # Pool Future: exception(timeout) both waits and retrieves the stored
        # engine exception (crash surfaced; no GC warning at drop).
        try:
            handle.exception(timeout=1.0)
        except TimeoutError:
            logger.debug(
                "engine %s still stopping after 1s — coordinator stop will "
                "join it via pool shutdown", symbol,
            )
        except Exception:
            logger.debug("engine %s run-task wait failed", symbol, exc_info=True)

    def _spawn_engine(self, symbol: str) -> QuantEngine | None:
        # Real thread bound: refuse spawns past pool capacity BEFORE building
        # anything (one pool worker is occupied per RUNNING engine — each run
        # loop blocks on its symbol's tick queue until closed). However large
        # a scan requests, concurrent engines can never exceed
        # self._max_threads OS threads.
        with self._lock:
            if len(self._engines) >= self._max_threads:
                logger.warning(
                    "QuantCoordinator: refusing to spawn %s — at the bounded "
                    "engine ceiling of %d (pool capacity). Stop an engine or "
                    "raise config n / max_engine_threads before adding more.",
                    symbol, self._max_threads,
                )
                return None
        gateway = LiveGateway(self._feed, symbol)
        # Every instrument (futures and options) trades independently as a self-contained scalper.
        # No underlying gateway coupling or cross-feed translation.
        underlying_gateway = None

        # Per-day event journal (fsync JSONL) — feeds the L1 nightly replay
        # determinism loop. One file per symbol per day keeps writes bounded.
        from datetime import datetime as _dt
        from pathlib import Path as _Path

        _journal_dir = self.config.get("journal_dir")
        # F4: only the LIVE wiring path reads MLX_* env vars and builds the
        # LLMAdvisor (with its worker thread). Backtest/replay constructors
        # pass no advisor — the deterministic engine stays env-free.
        # advisor_enabled config gate: the Fabio AMT strategy is fully
        # deterministic; LLM advisor is advisory-only and defaults to OFF.
        from quant.wiring_advisor import build_live_advisor
        advisor = None
        if self.config.get("advisor_enabled", False):
            advisor = build_live_advisor(None)

        # Ultra-fast independent scalping: all symbols (futures and options) have execution enabled.
        execution_enabled = True

        # Resolve the exact broker-neutral identity before engine construction.
        # The engine and OMS must share one contract object; no execution path
        # may infer identity independently from a display symbol.
        contract = self._contract_for(symbol)

        engine = QuantEngine(
            gateway,
            symbol,
            interval_seconds=self.config["interval_seconds"],
            history_source=self.market_data,
            lot_size=self._resolve_lot_size(symbol),
            tick_size=self._resolve_tick_size(symbol),
            market=self._session_profile_for(symbol),
            session_levels=self._session_levels,
            underlying_gateway=underlying_gateway,
            execution_model=self.config.get("execution_model", "independent"),
            contract=contract,
            strategy=self._strategy,
            portfolio_risk=self._portfolio_risk,
            max_trades_per_session=int(self.config.get("max_trades_per_session", 6)),
            advisor=advisor,
            risk_per_trade_pct=float(self.config.get("risk_per_trade_pct", 0.05)),
            capital_deployment_pct=(
                float(self.config["capital_deployment_pct"])
                if "capital_deployment_pct" in self.config
                else None
            ),
            max_daily_loss_pct=float(self.config.get("max_daily_loss_pct", 0.10)),
            max_consecutive_losses=int(self.config.get("max_consecutive_losses", 3)),
            cooldown_minutes=int(self.config.get("cooldown_minutes", 15)),
            execution_enabled=execution_enabled,
            seed_scheduler=self._seed_scheduler,
            max_lots=(
                int(self.config["max_lots"])
                if "max_lots" in self.config
                else (2 if self._session_profile_for(symbol) == "MCX" else 10)
            ),
        )
        if advisor is not None:
            # Route advisor emissions through the engine's own bus exactly as
            # the previous in-constructor wiring did.
            advisor.set_emit_fn(engine._emit)

        # Wire TimesFM historical pre-seed: when AMT finishes seeding session
        # candles, push those closes into TimesFMEngine so the model starts
        # with a full context window instead of a single repeated price.
        if hasattr(engine, "_amt_engine") and engine._amt_engine is not None:
            seed_targets = []
            if advisor is not None and getattr(advisor, "_native_engine", None) is not None:
                seed_targets.append(advisor._native_engine.seed_history)
            strat = getattr(engine, "_strategy", None)
            if strat is not None and getattr(strat, "_engine", None) is not None:
                if strat._engine.seed_history not in seed_targets:
                    seed_targets.append(strat._engine.seed_history)

            if seed_targets:
                def _seed_all_timesfm(sym: str, prices: list[float]) -> None:
                    for s_fn in seed_targets:
                        try:
                            s_fn(sym, prices)
                        except Exception:  # silent-except - timesfm seed callback is best-effort
                            pass
                engine._amt_engine._timesfm_seed_fn = _seed_all_timesfm

        root_upper = _canonical_root(symbol).upper()
        if root_upper in self._gex_by_root and hasattr(engine, "_amt_engine"):
            engine._amt_engine.set_gex(self._gex_by_root[root_upper])
        # OMS composition is explicit at the coordinator boundary. Live mode
        # receives LiveOMS; every paper engine receives the cost-aware factory
        # with a validated ContractRef. QuantEngine's direct-construction
        # fallback remains test/replay-only and is not reachable here.
        if self.config.get("live_oms_enabled") and self.broker is not None:
            portfolio = self._portfolio
            lot_size = self._resolve_lot_size(symbol)
            live_oms = LiveOMS(
                broker=self.broker,
                portfolio=portfolio,
                lot_size=lot_size,
                contract=contract,
            )
            engine._oms = live_oms
            live_oms.set_emit_fn(engine._emit)
            logger.warning(
                "LIVE MODE: %s using LiveOMS — orders route to Dhan exchange",
                symbol,
            )
        elif not execution_enabled:
            # Underlying observer engines never submit orders, so no OMS is
            # needed. Keep the explicit non-execution boundary rather than
            # inventing an invalid paper contract for the observer.
            pass
        else:
            from quant.execution.oms_factory import make_paper_oms
            paper_oms = make_paper_oms(
                contract=contract,
                cost_profile=self._cost_profile_for(symbol),
            )
            paper_oms.set_quote_provider(self._quote_provider_for(engine))
            engine._oms = paper_oms
            logger.info(
                "PAPER MODE: %s using bid_ask PaperExecutionSimulator "
                "contract=%s costs=enabled",
                symbol, contract.instrument_key if hasattr(contract, "instrument_key") else contract.symbol,
            )
        # Always attach storage (position persistence, restart book).
        if self._storage is not None:
            engine.attach_storage(self._storage)
            inflight = self._load_inflight_orders_for_startup()
            for row in inflight:
                if row.get("symbol") == symbol:
                    engine.restore_unresolved_order(row)
                    self._reconcile_restored_order(engine, row)
            # Only restore positions classified as OPEN by the reconciler.
            # Quarantined positions are preserved in storage but NOT loaded
            # into any engine (they are not in the active universe).
            open_rows: list[dict] = []
            if self._reconciliation_result is not None:
                open_rows = [
                    r for r in self._reconciliation_result.open_positions
                    if r.get("symbol") == symbol
                ]
            else:
                # No reconciler result (e.g., tests that bypass start()): fall
                # back to loading directly, filtering by symbol.
                try:
                    rows = self._storage.load_open_positions() or []
                except Exception:
                    logger.exception("load_open_positions failed for %s", symbol)
                    rows = []
                open_rows = [r for r in rows if r.get("symbol") == symbol]
            from quant.execution.order import row_to_position
            for row in open_rows:
                # The fill ledger is the durable authority. A snapshot may be
                # used only when it agrees with reconstructed quantity; a
                # mismatch is quarantined and must not enter the run loop.
                if hasattr(self._storage, "load_fills"):
                    position_id = str(row.get("id") or "")
                    try:
                        reconstruction = reconstruct_fill_ledger(
                            self._storage.load_fills(position_id=position_id) or []
                        )
                    except Exception:
                        reconstruction = None
                    if reconstruction is None or reconstruction.issues:
                        self._unresolved_startup.add(
                            f"ledger:{position_id or symbol}"
                        )
                        continue
                    rebuilt = reconstruction.positions.get(position_id)
                    if rebuilt is None or abs(
                        rebuilt.signed_quantity - float(row.get("size") or 0.0)
                    ) > 1e-9:
                        self._unresolved_startup.add(
                            f"ledger-mismatch:{position_id or symbol}"
                        )
                        continue
                engine.restore_position(row_to_position(row))
                break

        if _journal_dir:
            from quant.persistence import Journal

            day = _dt.now().strftime("%Y-%m-%d")
            safe = "".join(ch if ch.isalnum() or ch in " -" else "_" for ch in symbol)
            jdir = _Path(_journal_dir)
            jdir.mkdir(parents=True, exist_ok=True)
            engine.journal_path = str(jdir / f"{day}_{safe}.jsonl")
            engine.attach_journal()
        # Keep the guard live: reconciliation/ledger failures can be discovered
        # while this engine is being assembled, after its decision loop exists.
        engine._startup_issue_fn = lambda: bool(self._unresolved_startup)
        # Publish ownership and submit the run loop atomically under one
        # lock: shutdown/health/option-underlying lookup must never observe an
        # engine whose run task is missing, nor a run task for a symbol the
        # maps no longer own.
        with self._lock:
            self._engines[symbol] = engine
            self._gateways[symbol] = gateway
            if underlying_gateway is not None:
                self._underlying_gateways[symbol] = underlying_gateway
            self._threads[symbol] = self._start_engine_loop(engine)
        return engine

    def _reconcile_restored_order(self, engine, row: dict) -> None:
        """Reconcile restored broker exposure before the engine can decide."""
        broker = self.broker
        order_id = str(row.get("broker_order_id") or row.get("order_id") or "")
        if broker is None or not order_id:
            self._unresolved_startup.add(f"broker-reconciliation-unavailable:{order_id or engine.symbol}")
            return
        try:
            if hasattr(broker, "reconcile_order"):
                snapshot = broker.reconcile_order(order_id)
            elif hasattr(broker, "get_order_status"):
                snapshot = broker.get_order_status(order_id)
            else:
                self._unresolved_startup.add(f"broker-reconciliation-unavailable:{order_id}")
                snapshot = None
        except Exception:
            logger.exception("broker reconciliation failed for %s", order_id)
            self._unresolved_startup.add(f"broker-reconciliation-failed:{order_id}")
            return
        if snapshot is None:
            self._unresolved_startup.add(f"broker-reconciliation-unresolved:{order_id}")
            return
        if not isinstance(snapshot, dict):
            status = str(getattr(snapshot, "status", "")).upper()
            filled = float(getattr(snapshot, "filled_quantity", 0.0) or 0.0)
            requested = float(getattr(snapshot, "quantity", row.get("quantity", 0.0)) or 0.0)
            if status in {"FILLED", "OPEN", "PARTIALLY_FILLED", "PARTIAL"}:
                normalized = {
                    "status": "OPEN",
                    "symbol": row.get("symbol"),
                    "order_id": order_id,
                    "filled_qty": filled or requested,
                    "fill_price": float(getattr(snapshot, "average_fill_price", 0.0) or 0.0),
                }
            elif status in {"CANCELLED", "REJECTED", "CLOSED", "EXPIRED"}:
                normalized = {"status": "FLAT", "symbol": row.get("symbol"), "order_id": order_id}
            else:
                normalized = None
        else:
            normalized = dict(snapshot)
        engine.reconcile_unresolved_order(normalized)
        if not row.get("risk_reserved") and not row.get("reserved_risk"):
            self._unresolved_startup.add(f"risk-reservation-unavailable:{order_id}")
        if engine.exposure_state.status.name != "RECONCILIATION_REQUIRED":
            self._unresolved_startup.discard(order_id)

    def _load_inflight_orders_for_startup(self) -> list[dict]:
        """Load durable inflight rows without converting storage failure to flat."""
        issues = getattr(self, "_unresolved_startup", None)
        if issues is None:
            issues = self._unresolved_startup = set()
        if self._storage is None or not hasattr(self._storage, "load_inflight_orders"):
            if getattr(self, "config", {}).get("live_oms_enabled"):
                issues.add("order-storage-unavailable")
            return []
        try:
            rows = self._storage.load_inflight_orders()
        except Exception:
            issues.add("order-storage-unavailable")
            raise
        rows = list(rows or [])
        issues.update(
            str(row.get("broker_order_id") or row.get("order_id") or "unknown-order")
            for row in rows
        )
        return rows

    def _stop_engine(self, symbol: str) -> None:
        with self._lock:
            gateway = self._gateways.pop(symbol, None)
            underlying_gateway = self._underlying_gateways.pop(symbol, None)
            run_handle = self._threads.pop(symbol, None)
            engine = self._engines.pop(symbol, None)
        if engine is not None:
            try:
                engine.persist_prior_profile()
            except Exception:
                logger.warning("persist_prior_profile failed for %s on shutdown", symbol, exc_info=True)
            # F3: the advisor's daemon worker spins on a 1s poll loop for as
            # long as _running is True — and nothing ever called shutdown()
            # on the coordinator path, so every rescan cycle leaked one
            # thread per stopped engine. Defensive + non-fatal: an engine
            # without an advisor (or a broken shutdown) must never abort the
            # gateway close.
            try:
                advisor = getattr(engine, "_advisor", None)
                if advisor is not None and callable(getattr(advisor, "shutdown", None)):
                    advisor.shutdown()
            except Exception:
                logger.exception(
                    "advisor shutdown failed during stop of %s (ignored)", symbol
                )
        # Close the gateways FIRST so the engine's blocking run loop wakes on
        # the end-of-stream None (feed.unsubscribe -> queue.put(None)) and
        # exits promptly — only then wait for the run handle.
        if gateway is not None:
            gateway.close()
        if underlying_gateway is not None:
            underlying_gateway.close()
        if run_handle is not None:
            self._wait_run_handle(run_handle, symbol)
        # The run loop has exited (or timed out), so closing the journal can
        # no longer race an in-flight append from the engine thread.
        if engine is not None:
            try:
                journal = getattr(engine, "_journal", None)
                if journal is not None and callable(getattr(journal, "close", None)):
                    journal.close()
            except Exception:
                logger.exception(
                    "journal close failed during stop of %s (ignored)", symbol
                )

    def _stop_engines(self) -> None:
        with self._lock:
            symbols = list(self._engines.keys())
        for symbol in symbols:
            self._stop_engine(symbol)
