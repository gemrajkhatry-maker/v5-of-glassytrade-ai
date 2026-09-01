"""QuantCoordinator — multi-symbol orchestrator.

Runs one QuantEngine per scanned option contract on its own daemon thread,
folds engine decisions onto a shared queue for the backend shell. Pure quant:
imports ``quant.*`` and stdlib only — zero backend imports.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from quant.amt.session.scanner import OptionScannerService
from quant.brokers.live_gateway import LiveGateway
from quant.brokers.multiplexed_feed import MultiplexedMarketFeed
from quant.contracts.aggregates import INITIAL_CAPITAL
from quant.contracts.enums import MarketState
from quant.contracts.instrument_registry import DEFAULT_REGISTRY, is_futures_contract, root_token
from quant.contracts.market_calendar import is_trading_day
from quant.contracts.timezones import IST, MCX_SESSION_CLOSE, NSE_SESSION_CLOSE
from quant.events import BarClosed
from quant.execution.live_oms import LiveOMS
from quant.execution.oms import PaperOMS
from quant.runtime import QuantEngine
from quant.session_levels import SessionLevelStore
from quant.ws_adapter import view_state_to_ws

logger = logging.getLogger(__name__)


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
        except ValueError:
            pass

    m = _MONTH_STRIKE_RE.search(clean)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass

    root = _canonical_root(clean)
    rem = clean
    if root and clean.startswith(root):
        rem = clean[len(root):].strip(" -_")

    m = _WEEKLY_COMPACT_RE.search(rem)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass

    m = _TRAILING_DIGITS_RE.search(rem if rem else clean)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
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
    # EOD square-off backstop: minutes before exchange close at which the
    # watchdog force-flattens any still-open position (intraday-only book).
    "eod_squareoff_minutes_before_close": 15,
    # First-listed roots get first claim on scanner slots (primary series).
    "underlying_priority": None,
}


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


class QuantCoordinator:
    """Owns one :class:`QuantEngine` per scanned contract, all fed by a
    single multiplexed :class:`MultiplexedMarketFeed` — one WebSocket
    connection for every symbol (Dhan allows up to 1000 instruments per
    connection)."""

    def __init__(self, market_data, broker=None, config=None, strategy=None, storage=None) -> None:
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
        self._threads: dict[str, threading.Thread] = {}
        self._stop = threading.Event()
        self._gex_by_root: dict[str, object] = {}
        self._eod_thread: threading.Thread | None = None
        self._lock = threading.Lock()
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
        # than the portfolio limit (8 engines x 0.5% each would otherwise
        # simultaneously risk 4% of capital).
        from quant.execution.portfolio_risk import PortfolioRiskAuthority
        self._portfolio_risk = PortfolioRiskAuthority(
            starting_equity=float(self.config.get("starting_equity", float(INITIAL_CAPITAL))),
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
            if engine is None or engine._position is not None:
                # Do not migrate during active trade
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
                    pass

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
            if engine is None or getattr(engine, "_position", None) is not None:
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
                    pass

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

            if not reason:
                continue

            # Find replacement contract using OptionScanner
            try:
                scanner = OptionScannerService(self.market_data)
                exchange = spec.dhan_exchange if spec is not None else self.config.get("exchange", "NSE")
                results = scanner.scan_top_n(
                    n=4,
                    underlyings=[root],
                    exchange=exchange,
                    expiry_index=int(self.config.get("expiry_index", 0)),
                    strikes_around_atm=int(self.config.get("strikes_around_atm", 3)),
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
            self.started = False

    def snapshot(self, symbol: str) -> dict:
        with self._lock:
            engine = self._engines.get(symbol)
        if engine is None:
            return {"_symbol": symbol}
        return view_state_to_ws(engine.projector.snapshot(symbol))

    def symbols(self) -> list[str]:
        with self._lock:
            return list(self._engines.keys())

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
            if getattr(eng, "_position", None) is None and not getattr(eng, "_pyramid_positions", None):
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
            sym = str(getattr(bp, "symbol", "") or "").strip()
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
            engine_by_symbol[sym] = net

        drift = []
        for sym, broker_qty in broker_by_symbol.items():
            engine_qty = engine_by_symbol.get(sym)
            if engine_qty is None:
                drift.append(f"{sym}: broker={broker_qty} but no engine position (orphan?)")
            elif abs(broker_qty - engine_qty) > 0.01:
                drift.append(f"{sym}: broker={broker_qty} vs engine={engine_qty}")
        for sym, engine_qty in engine_by_symbol.items():
            if sym not in broker_by_symbol:
                drift.append(f"{sym}: engine={engine_qty} but broker has none (desync?)")

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
                logger.debug("periodic_reconcile skipped for %s", eng.symbol)

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
            except Exception:
                logger.exception("EOD watchdog: square-off pass failed")

            # Dynamic Contract Rotation: runs every ~60s (every 2nd pass)
            rotation_counter += 1
            if rotation_counter >= 2:
                rotation_counter = 0
                try:
                    self.check_and_rotate_dead_symbols()
                except Exception:
                    logger.exception("Dynamic rotation watchdog: pass failed")

            # C4: intraday broker-vs-engine book reconciliation, every ~60s.
            # Detect-and-alert only (no auto-action) — see _intraday_reconcile.
            recon_counter += 1
            if recon_counter >= 2:
                recon_counter = 0
                try:
                    self._intraday_reconcile()
                except Exception:
                    logger.exception("Intraday reconcile watchdog: pass failed")

            # Periodic state-vs-event-store reconciliation, every ~120s (every 4th pass).
            periodic_recon_counter += 1
            if periodic_recon_counter >= 4:
                periodic_recon_counter = 0
                try:
                    self._periodic_state_reconcile()
                except Exception:
                    logger.exception("Periodic state reconcile watchdog: pass failed")

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
            results = scanner.scan_top_n(
                n=n_options,
                underlyings=self.config["underlyings"],
                exchange=self.config["exchange"],
                expiry_index=self.config["expiry_index"],
                strikes_around_atm=self.config["strikes_around_atm"],
                underlying_priority=self.config.get("underlying_priority"),
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

    def _session_profile_for(self, symbol: str) -> str:
        """NSE/MCX session clock for *symbol* — never the coordinator's mode flag."""
        return DEFAULT_REGISTRY.resolve(symbol).session_profile

    def _resolve_tick_size(self, symbol: str) -> float:
        """InstrumentRegistry tick. Unknown roots raise — never 0.05."""
        return DEFAULT_REGISTRY.resolve(symbol).tick_size

    def _resolve_lot_size(self, symbol: str) -> float:
        """Broker lot if present, else InstrumentRegistry. Unknown roots raise."""
        try:
            raw = self.market_data.get_lot_size(symbol)
            lot_size = float(raw or 0)
            if lot_size > 0:
                return lot_size
        except Exception:
            pass
        return float(DEFAULT_REGISTRY.resolve(symbol).lot_size)

    def _spawn_engine(self, symbol: str) -> None:
        gateway = LiveGateway(self._feed, symbol)
        underlying_gateway = None
        if not _is_futures_symbol(symbol):
            root = _canonical_root(symbol)
            futures = {
                _canonical_root(future): future
                for future in self._engines
                if _is_futures_symbol(future)
            }
            futures_symbol = futures.get(root)
            if not futures_symbol:
                try:
                    spec = DEFAULT_REGISTRY.try_resolve(root)
                    exchange = spec.dhan_exchange if spec is not None else self.config.get("exchange", "NSE")
                    if hasattr(self.market_data, "get_nearest_futures"):
                        futures_symbol = self.market_data.get_nearest_futures(root, exchange=exchange)
                    if not futures_symbol:
                        now = datetime.now(tz=IST)
                        month_str = now.strftime("%b").upper()
                        futures_symbol = f"{root.upper()} {month_str} FUT"
                except Exception:
                    pass
            if futures_symbol:
                self._feed.subscribe(futures_symbol)
                reader = self._feed.add_reader(futures_symbol)
                underlying_gateway = LiveGateway(self._feed, futures_symbol, reader_queue=reader)
        # Per-day event journal (fsync JSONL) — feeds the L1 nightly replay
        # determinism loop. One file per symbol per day keeps writes bounded.
        from datetime import datetime as _dt
        from pathlib import Path as _Path

        _journal_dir = self.config.get("journal_dir")
        # F4: only the LIVE wiring path reads MLX_* env vars and builds the
        # LLMAdvisor (with its worker thread). Backtest/replay constructors
        # pass no advisor — the deterministic engine stays env-free.
        from quant.wiring_advisor import build_live_advisor
        advisor = build_live_advisor(None)
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
            strategy=self._strategy,
            portfolio_risk=self._portfolio_risk,
            max_trades_per_session=int(self.config.get("max_trades_per_session", 6)),
            advisor=advisor,
            risk_per_trade_pct=float(self.config.get("risk_per_trade_pct", 0.005)),
        )
        if advisor is not None:
            # Route advisor emissions through the engine's own bus exactly as
            # the previous in-constructor wiring did.
            advisor.set_emit_fn(engine._emit)
        root_upper = _canonical_root(symbol).upper()
        if root_upper in self._gex_by_root and hasattr(engine, "_amt_engine"):
            engine._amt_engine.set_gex(self._gex_by_root[root_upper])
        # OMS injection: live_oms_enabled + broker → LiveOMS, else PaperOMS.
        # The engine default is PaperOMS (set in QuantEngine.__init__); we
        # override only when the coordinator has a wired broker.
        if self.config.get("live_oms_enabled") and self.broker is not None:
            from quant.contracts.aggregates import Portfolio
            portfolio = Portfolio()
            lot_size = self._resolve_lot_size(symbol)
            live_oms = LiveOMS(
                broker=self.broker,
                portfolio=portfolio,
                lot_size=lot_size,
            )
            engine._oms = live_oms
            live_oms.set_emit_fn(engine._emit)
            logger.warning(
                "LIVE MODE: %s using LiveOMS — orders route to Dhan exchange",
                symbol,
            )
        # Always attach storage (position persistence, restart book).
        if self._storage is not None:
            engine.attach_storage(self._storage)
            try:
                rows = self._storage.load_open_positions() or []
            except Exception:
                logger.exception("load_open_positions failed for %s", symbol)
                rows = []
            from quant.execution.order import row_to_position
            for row in rows:
                if row.get("symbol") == symbol:
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
        thread = threading.Thread(
            target=engine.run, daemon=True, name=f"quant-{symbol}"
        )
        # Publish ownership before starting the thread.  Otherwise shutdown,
        # health, and option-underlying lookup can observe a running engine
        # that is absent from the coordinator maps.
        with self._lock:
            self._engines[symbol] = engine
            self._gateways[symbol] = gateway
            if underlying_gateway is not None:
                self._underlying_gateways[symbol] = underlying_gateway
            self._threads[symbol] = thread
        thread.start()
        return engine

    def _stop_engine(self, symbol: str) -> None:
        with self._lock:
            gateway = self._gateways.pop(symbol, None)
            underlying_gateway = self._underlying_gateways.pop(symbol, None)
            thread = self._threads.pop(symbol, None)
            engine = self._engines.pop(symbol, None)
        # F3: the advisor's daemon worker spins on a 1s poll loop for as long
        # as _running is True — and nothing ever called shutdown() on the
        # coordinator path, so every rescan cycle leaked one thread per
        # stopped engine. Defensive + non-fatal: an engine without an advisor
        # (or a broken shutdown) must never abort the gateway close.
        if engine is not None:
            try:
                engine.persist_prior_profile()
            except Exception:
                pass
            try:
                advisor = getattr(engine, "_advisor", None)
                if advisor is not None and callable(getattr(advisor, "shutdown", None)):
                    advisor.shutdown()
            except Exception:
                logger.exception(
                    "advisor shutdown failed during stop of %s (ignored)", symbol
                )
            try:
                journal = getattr(engine, "_journal", None)
                if journal is not None and callable(getattr(journal, "close", None)):
                    journal.close()
            except Exception:
                logger.exception(
                    "journal close failed during stop of %s (ignored)", symbol
                )
        if gateway is not None:
            gateway.close()
        if underlying_gateway is not None:
            underlying_gateway.close()
        if thread is not None:
            try:
                thread.join(timeout=1.0)
            except RuntimeError:
                pass

    def _stop_engines(self) -> None:
        with self._lock:
            symbols = list(self._engines.keys())
        for symbol in symbols:
            self._stop_engine(symbol)
