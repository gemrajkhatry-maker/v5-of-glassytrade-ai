"""AuctionCoordinator — folds all six quant detectors into one immutable
AuctionState snapshot per closed bar. Pure and deterministic: same bars in,
same states out."""

from __future__ import annotations

from quant.absorption import AbsorptionDetector
from quant.auction_state import AuctionState
from quant.bars import Bar
from quant.location import LocationBuilder
from quant.order_flow import OrderFlowBuilder
from quant.triple_a import TripleAStateMachine
from quant.volume_profile import VolumeProfileBuilder
from quant.vwap import VWAPBuilder


class AuctionCoordinator:
    def __init__(self) -> None:
        self._vp_builder = VolumeProfileBuilder()
        self._vwap_builder = VWAPBuilder()
        self._of_builder = OrderFlowBuilder()
        self._abs_detector = AbsorptionDetector()
        self._loc_builder = LocationBuilder()
        self._triple_a = TripleAStateMachine()

    def seed_history(self, bars: list[Bar]) -> None:
        """Pre-feed the data builders with session history so the first live
        bar's snapshot (POC/VA/VWAP/IB/zone) is meaningful instead of empty.

        Fed on the engine's seed thread BEFORE live bars start closing; the
        Triple-A machine is intentionally left WAITING (it re-arms only on a
        fresh absorption detection with ``bar_age == 0``).
        """
        for bar in bars:
            self._vp_builder.update(bar)
            self._vwap_builder.update(bar)
            self._of_builder.update(bar)
            self._abs_detector.update(bar)
            self._loc_builder.update(bar)

    def on_bar_close(self, bar: Bar) -> AuctionState:
        self._vp_builder.update(bar)
        self._vwap_builder.update(bar)
        self._of_builder.update(bar)
        self._abs_detector.update(bar)
        self._loc_builder.update(bar)

        vp = self._vp_builder.snapshot()
        vwap = self._vwap_builder.snapshot()
        of = self._of_builder.snapshot()
        absorption = self._abs_detector.snapshot()
        loc = self._loc_builder.snapshot(vp, bar.close)

        phase = self._triple_a.update(bar, vp, vwap, absorption)
        signal = self._triple_a.last_signal

        return AuctionState(
            time=bar.time,
            close=bar.close,
            volume_profile=vp,
            vwap=vwap,
            order_flow=of,
            absorption=absorption,
            location=loc,
            triple_a_phase=phase,
            triple_a_signal=signal,
        )


# ---------------------------------------------------------------------------
# QuantCoordinator — multi-symbol orchestrator. Runs one QuantEngine per
# scanned option contract on its own daemon thread, folds engine decisions
# onto a shared queue for the backend shell. Pure quant: imports ``quant.*``
# and stdlib only — zero backend imports. (Imports live after
# AuctionCoordinator so quant.runtime's ``from quant.coordinator import
# AuctionCoordinator`` does not hit a partially-initialized module.)
# ---------------------------------------------------------------------------

from quant.amt.session.scanner import OptionScannerService
from quant.brokers.live_gateway import LiveGateway
from quant.brokers.multiplexed_feed import MultiplexedMarketFeed
from quant.events import DecisionProduced, SignalApproved
from quant.runtime import QuantEngine
from quant.ws_adapter import view_state_to_ws
from quant.contracts.timezones import IST

import json
import logging
import queue
import threading
from datetime import datetime
from pathlib import Path

from quant.session_levels import SessionLevelStore

logger = logging.getLogger(__name__)


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
    "n": 4,
    "exchange": "NSE",
    "expiry_index": 0,
    "strikes_around_atm": 2,
    "interval_seconds": 60,
    # First-listed roots get first claim on scanner slots (primary series).
    "underlying_priority": None,
}


class QuantCoordinator:
    """Owns one :class:`QuantEngine` per scanned contract, all fed by a
    single multiplexed :class:`MultiplexedMarketFeed` — one WebSocket
    connection for every symbol (Dhan allows up to 1000 instruments per
    connection). Plus a shared decision queue."""

    def __init__(self, market_data, broker=None, config=None) -> None:
        self.market_data = market_data
        self.broker = broker
        self.config = {**_DEFAULT_CONFIG, **(config or {})}
        self._contracts_file = self.config.get("contracts_file") or _DEFAULT_CONTRACTS_FILE
        # Shared across all engines (one file, one lock) so prior levels are
        # consistent and NPOC records dedupe per session.
        self._session_levels = SessionLevelStore(
            path=self.config.get("session_levels_file") or _DEFAULT_SESSION_LEVELS_FILE
        )
        self._feed = MultiplexedMarketFeed(market_data)
        self._engines: dict[str, QuantEngine] = {}
        self._gateways: dict[str, LiveGateway] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._decisions: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self.started = False

    def start(self) -> None:
        symbols = self._scan()
        self._feed.set_symbols(symbols)
        for symbol in symbols:
            self._spawn_engine(symbol)
        self.started = True

    def rescan(self) -> list[str]:
        self._stop_engines()
        symbols = self._scan(force=True)
        self._feed.set_symbols(symbols)
        for symbol in symbols:
            self._spawn_engine(symbol)
        return symbols

    def switch_symbol(self, old: str, new: str) -> bool:
        if old not in self._engines:
            return False
        self._stop_engine(old)
        self._feed.subscribe(new)
        self._spawn_engine(new)
        return True

    def stop(self) -> None:
        self._stop.set()
        self._stop_engines()
        self._feed.close()
        self.started = False

    def snapshot(self, symbol: str) -> dict:
        engine = self._engines.get(symbol)
        if engine is None:
            return {"_symbol": symbol}
        return view_state_to_ws(engine.projector.snapshot(symbol))

    def symbols(self) -> list[str]:
        return list(self._engines.keys())

    def decisions(self) -> queue.Queue:
        return self._decisions

    def _scan(self, *, force: bool = False) -> list[str]:
        """Select active contracts: reuse today's persisted selection unless a
        fresh scan is forced (e.g. an explicit rescan request), otherwise run
        the option scanner and persist the result."""
        if not force:
            persisted = load_persisted_contracts(
                self._contracts_file, exchange=self.config.get("exchange")
            )
            if persisted:
                logger.info(
                    "QuantCoordinator: reusing persisted contracts: %s", persisted
                )
                return persisted
        scanner = OptionScannerService(self.market_data)
        results = scanner.scan_top_n(
            n=self.config["n"],
            underlyings=self.config["underlyings"],
            exchange=self.config["exchange"],
            expiry_index=self.config["expiry_index"],
            strikes_around_atm=self.config["strikes_around_atm"],
            underlying_priority=self.config.get("underlying_priority"),
        )
        symbols = [r.symbol for r in results if (r.ltp or 0) > 0]
        if symbols:
            save_persisted_contracts(
                symbols, self._contracts_file, exchange=self.config.get("exchange")
            )
            logger.info("QuantCoordinator: persisted active contracts: %s", symbols)
        return symbols

    def _resolve_lot_size(self, symbol: str) -> float:
        """Exchange lot size for *symbol* (units per lot) for paper OMS parity.

        Routes through the market-data adapter's option-aware ``get_lot_size``
        (resolves an actual NFO option contract of the underlying, e.g.
        NIFTY=65/BANKNIFTY=30/FINNIFTY=60). Falls back to 1.0 (equity
        semantics) on any failure so engine startup never blocks on a broker
        hiccup; the warning surfaces the fallback.
        """
        try:
            raw = self.market_data.get_lot_size(symbol)
        except Exception:
            logger.warning(
                "lot size lookup failed for %s — paper sizing falls back to 1.0",
                symbol, exc_info=True,
            )
            return 1.0
        try:
            lot_size = float(raw or 0)
        except (TypeError, ValueError):
            return 1.0
        return lot_size if lot_size > 0 else 1.0

    def _spawn_engine(self, symbol: str) -> None:
        gateway = LiveGateway(self._feed, symbol)
        engine = QuantEngine(
            gateway,
            symbol,
            interval_seconds=self.config["interval_seconds"],
            history_source=self.market_data,
            lot_size=self._resolve_lot_size(symbol),
            market=self.config.get("exchange") or "NSE",
            session_levels=self._session_levels,
        )
        engine._bus.subscribe(DecisionProduced, self._on_decision)
        engine._bus.subscribe(SignalApproved, self._on_decision)
        thread = threading.Thread(
            target=engine.run, daemon=True, name=f"quant-{symbol}"
        )
        thread.start()
        self._engines[symbol] = engine
        self._gateways[symbol] = gateway
        self._threads[symbol] = thread

    def _on_decision(self, event) -> None:
        self._decisions.put(event)

    def _stop_engine(self, symbol: str) -> None:
        gateway = self._gateways.pop(symbol, None)
        if gateway is not None:
            gateway.close()
        thread = self._threads.pop(symbol, None)
        if thread is not None:
            thread.join(timeout=1.0)
        self._engines.pop(symbol, None)

    def _stop_engines(self) -> None:
        for symbol in list(self._engines):
            self._stop_engine(symbol)
