"""QuantCoordinator — multi-symbol orchestrator.

Runs one QuantEngine per scanned option contract on its own daemon thread,
folds engine decisions onto a shared queue for the backend shell. Pure quant:
imports ``quant.*`` and stdlib only — zero backend imports.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path

from quant.amt.session.scanner import OptionScannerService
from quant.brokers.live_gateway import LiveGateway
from quant.brokers.multiplexed_feed import MultiplexedMarketFeed
from quant.contracts.timezones import IST
from quant.contracts.exchange_config import ExchangeConfig
from quant.events import BarClosed
from quant.runtime import QuantEngine
from quant.session_levels import SessionLevelStore
from quant.ws_adapter import view_state_to_ws

logger = logging.getLogger(__name__)


def _is_futures_symbol(symbol: str) -> bool:
    """Whether *symbol* uses one of the broker's futures contract formats."""
    return symbol.strip().upper().endswith("FUT")


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
    # First-listed roots get first claim on scanner slots (primary series).
    "underlying_priority": None,
}


class QuantCoordinator:
    """Owns one :class:`QuantEngine` per scanned contract, all fed by a
    single multiplexed :class:`MultiplexedMarketFeed` — one WebSocket
    connection for every symbol (Dhan allows up to 1000 instruments per
    connection)."""

    def __init__(self, market_data, broker=None, config=None, strategy=None) -> None:
        self.market_data = market_data
        self.broker = broker
        self.config = {**_DEFAULT_CONFIG, **(config or {})}
        self._strategy = strategy  # TradingStrategy — None means engine uses default
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
        self._lock = threading.Lock()
        # Serializes LIFECYCLE TRANSITIONS (start/rescan/switch/stop). These
        # compose multiple steps over the shared dicts + threads above — a
        # dict-level lock cannot close the check-then-act window between them
        # (two concurrent switch_symbol(old, …) calls both passed the
        # membership check and spawned DUPLICATE engines for the new symbol).
        # Lifecycle ops are rare admin actions; coarse serialization is the
        # correct ownership boundary here.
        self._lifecycle_lock = threading.RLock()
        self.started = False

    def start(self) -> None:
        with self._lifecycle_lock:
            symbols = self._scan()
            self._feed.set_symbols(symbols)
            for symbol in symbols:
                self._spawn_engine(symbol)
            self.started = True

    def rescan(self) -> list[str]:
        with self._lifecycle_lock:
            self._stop_engines()
            symbols = self._scan(force=True)
            self._feed.set_symbols(symbols)
            for symbol in symbols:
                self._spawn_engine(symbol)
            return symbols

    def switch_symbol(self, old: str, new: str) -> bool:
        with self._lifecycle_lock:
            if old not in self._engines:
                return False
            self._stop_engine(old)
            self._feed.subscribe(new)
            self._spawn_engine(new)
            return True

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._stop.set()
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

    def check_spot_drift(self, underlying: str, spot_price: float) -> bool:
        """Detect when price moves > 1.5 strike intervals away from active option strikes."""
        from quant.amt.session.scanner import OptionScannerService
        step = OptionScannerService._STRIKE_INTERVALS.get(underlying.upper(), 50)
        strikes = []
        with self._lock:
            active_symbols = list(self._engines.keys())
        for sym in active_symbols:
            if _is_futures_symbol(sym):
                continue
            if sym.upper().startswith(underlying.upper()):
                tokens = sym.split()
                for tok in tokens:
                    if tok.isdigit() and int(tok) > 1000:
                        strikes.append(int(tok))
        if not strikes:
            return False
        mean_strike = sum(strikes) / len(strikes)
        return abs(spot_price - mean_strike) > 1.5 * step

    def _resolve_futures_symbols(self) -> list[str]:
        """Resolve active front-month futures for the configured underlyings."""
        symbols = []
        underlyings = self.config.get("futures_underlyings") or self.config.get("underlyings", [])
        exchange = self.config.get("exchange", "NSE")
        for u in underlyings:
            fut_sym = None
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
        config = ExchangeConfig.for_exchange(self.config.get("exchange", "NSE"))
        roots = {config.extract_underlying(symbol) for symbol in futures_symbols}
        return all(
            config.extract_underlying(symbol) in roots
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

    def _resolve_lot_size(self, symbol: str) -> float:
        """Exchange lot size for *symbol* (units per lot) for paper OMS parity.

        Routes through the market-data adapter's option-aware ``get_lot_size``
        (resolves an actual NFO/MCX option contract of the underlying).
        Falls back to ExchangeConfig metadata if lookup fails.
        """
        try:
            raw = self.market_data.get_lot_size(symbol)
            lot_size = float(raw or 0)
            if lot_size > 0:
                return lot_size
        except Exception:
            pass

        # Fallback to ExchangeConfig metadata
        from quant.contracts.exchange_config import ExchangeConfig
        ex = str(self.config.get("exchange", "MCX")).upper()
        for market in (ex, "MCX", "NSE"):
            try:
                cfg = ExchangeConfig.for_exchange(market)
                lot_size = float(cfg.get_lot_size(symbol))
                if lot_size > 0:
                    return lot_size
            except Exception:
                pass

        logger.warning(
            "lot size lookup failed for %s — paper sizing falls back to 1.0",
            symbol,
        )
        return 1.0

    def _spawn_engine(self, symbol: str) -> None:
        gateway = LiveGateway(self._feed, symbol)
        underlying_gateway = None
        if not _is_futures_symbol(symbol):
            config = ExchangeConfig.for_exchange(self.config.get("exchange", "NSE"))
            root = config.extract_underlying(symbol)
            futures = {
                config.extract_underlying(future): future
                for future in self._engines
                if _is_futures_symbol(future)
            }
            futures_symbol = futures.get(root)
            if futures_symbol:
                reader = self._feed.add_reader(futures_symbol)
                underlying_gateway = LiveGateway(self._feed, futures_symbol, reader_queue=reader)
        engine = QuantEngine(
            gateway,
            symbol,
            interval_seconds=self.config["interval_seconds"],
            history_source=self.market_data,
            lot_size=self._resolve_lot_size(symbol),
            market=self.config.get("exchange") or "NSE",
            session_levels=self._session_levels,
            underlying_gateway=underlying_gateway,
            strategy=self._strategy,
        )
        thread = threading.Thread(
            target=engine.run, daemon=True, name=f"quant-{symbol}"
        )
        thread.start()
        with self._lock:
            self._engines[symbol] = engine
            self._gateways[symbol] = gateway
            if underlying_gateway is not None:
                self._underlying_gateways[symbol] = underlying_gateway
            self._threads[symbol] = thread
        return engine

    def _stop_engine(self, symbol: str) -> None:
        with self._lock:
            gateway = self._gateways.pop(symbol, None)
            underlying_gateway = self._underlying_gateways.pop(symbol, None)
            thread = self._threads.pop(symbol, None)
            self._engines.pop(symbol, None)
        if gateway is not None:
            gateway.close()
        if underlying_gateway is not None:
            underlying_gateway.close()
        if thread is not None:
            thread.join(timeout=1.0)

    def _stop_engines(self) -> None:
        with self._lock:
            symbols = list(self._engines.keys())
        for symbol in symbols:
            self._stop_engine(symbol)
