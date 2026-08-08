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
from quant.events import DecisionProduced, LLMAnalysisProduced, SignalApproved
from quant.runtime import QuantEngine
from quant.ws_adapter import view_state_to_ws

import logging
import queue
import threading

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG = {
    "underlyings": ["NIFTY", "BANKNIFTY", "FINNIFTY"],
    "n": 4,
    "exchange": "NSE",
    "expiry_index": 0,
    "strikes_around_atm": 2,
    "interval_seconds": 60,
}


class QuantCoordinator:
    """Owns one :class:`QuantEngine` per scanned contract, all fed by a
    single multiplexed :class:`MultiplexedMarketFeed` — one WebSocket
    connection for every symbol (Dhan allows up to 1000 instruments per
    connection). Plus a shared decision queue."""

    def __init__(self, market_data, inference=None, broker=None, config=None,
                 llm_sink=None) -> None:
        self.market_data = market_data
        self.inference = inference
        self.broker = broker
        self.config = {**_DEFAULT_CONFIG, **(config or {})}
        # Optional persistence sink — the backend injects storage.save_llm_decision
        # so live LLM fold-backs get durable rows. Kept as a plain callable so the
        # quant layer stays free of backend imports.
        self._llm_sink = llm_sink
        self._feed = MultiplexedMarketFeed(market_data)
        self._engines: dict[str, QuantEngine] = {}
        self._gateways: dict[str, LiveGateway] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._history: dict[str, list[dict]] = {}
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
        symbols = self._scan()
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

    def llm_history(self, symbol: str) -> list[dict]:
        return list(self._history.get(symbol, []))

    def decisions(self) -> queue.Queue:
        return self._decisions

    def _scan(self) -> list[str]:
        scanner = OptionScannerService(self.market_data)
        results = scanner.scan_top_n(
            n=self.config["n"],
            underlyings=self.config["underlyings"],
            exchange=self.config["exchange"],
            expiry_index=self.config["expiry_index"],
            strikes_around_atm=self.config["strikes_around_atm"],
        )
        return [r.symbol for r in results if (r.ltp or 0) > 0]

    def _spawn_engine(self, symbol: str) -> None:
        gateway = LiveGateway(self._feed, symbol)
        engine = QuantEngine(
            gateway,
            symbol,
            interval_seconds=self.config["interval_seconds"],
            inference=self.inference,
            llm_history=self._history.setdefault(symbol, []),
            history_source=self.market_data,
        )
        engine._bus.subscribe(DecisionProduced, self._on_decision)
        engine._bus.subscribe(SignalApproved, self._on_decision)
        if self._llm_sink is not None:
            engine._bus.subscribe(LLMAnalysisProduced, self._on_llm_analysis)
        thread = threading.Thread(
            target=engine.run, daemon=True, name=f"quant-{symbol}"
        )
        thread.start()
        self._engines[symbol] = engine
        self._gateways[symbol] = gateway
        self._threads[symbol] = thread

    def _on_decision(self, event) -> None:
        self._decisions.put(event)

    def _on_llm_analysis(self, event) -> None:
        """Persist a live LLM fold-back via the injected sink.

        Runs on the engine's LLM-fold thread; the sink is a single small DB
        write, so no extra queuing is needed. Enriched analyses carry
        ``timestamp``/``created_at``/``input_prompt``/``raw_output`` set by
        QuantEngine._schedule_llm.
        """
        if self._llm_sink is None:
            return
        try:
            data = dict(event.analysis or {})
            data.setdefault("symbol", event.symbol)
            data.setdefault("created_at", event.time)
            self._llm_sink(data)
        except Exception:
            logger.warning(
                "LLM decision sink failed for %s", event.symbol, exc_info=True
            )

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
