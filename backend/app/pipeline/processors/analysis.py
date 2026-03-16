"""AMTAnalysisProcessor — wraps AMTHandler in the NiFi-style pipeline interface.

Consumes CandleMessage from inbox["candles"].
Produces Message[AMTResultPayload] to outbox["amt_results"].

This processor is purely a pipeline adapter: it does NOT contain business
logic. All analysis is delegated to AMTHandler (which wraps AMTAnalyzer).

Configuration (ProcessorConfig.settings):
    lookback: int — maximum closed candles kept per symbol (default 50)
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from app.pipeline.channel import Channel
from app.pipeline.message import (
    AMTResultPayload,
    CandleMessage,
    CandlePayload,
    Message,
)
from app.pipeline.processor import BaseProcessor, ProcessorConfig

logger = logging.getLogger(__name__)


class AMTAnalysisProcessor(BaseProcessor):
    """Adapts the AMTHandler domain service to the pipeline Channel interface.

    Per-symbol state:
      - A dedicated AMTHandler instance (holds incremental VP state)
      - A rolling candle history (max ``lookback`` closed candles)

    Candle handling:
      - closed=True  -> append to history, run analysis, emit AMTResultPayload
      - closed=False -> live bar; do NOT append to history (bar is incomplete)
    """

    name = "amt_analysis"

    async def setup(self, config: ProcessorConfig) -> None:
        """Initialise per-symbol state containers and load settings."""
        await super().setup(config)

        self._lookback: int = int(config.settings.get("lookback", 50))

        # Lazy-initialised per-symbol AMTHandler instances.
        # We import here rather than at module level so the processor module
        # itself does not fail to import in environments where the AMT stack is
        # unavailable (e.g. pure unit tests that mock the handler).
        self._handlers: dict[str, Any] = {}

        # Rolling closed-candle histories keyed by symbol.
        # We store raw CandlePayload dicts so we can reconstruct OHLC objects
        # as needed by the existing domain service interface.
        self._histories: dict[str, list[CandlePayload]] = defaultdict(list)

    async def teardown(self) -> None:
        """No external resources to clean up."""
        self._handlers.clear()
        self._histories.clear()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def process(
        self,
        inbox: dict[str, Channel],
        outbox: dict[str, Channel],
    ) -> None:
        """Read CandleMessages forever; emit AMTResultMessages on closed candles."""
        in_ch: Channel = inbox["candles"]
        out_ch: Channel = outbox["amt_results"]

        async for msg in in_ch:
            try:
                await self._handle_candle(msg, out_ch)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error(
                    "[%s] Error processing candle for %s",
                    self.name,
                    getattr(msg, "symbol", "?"),
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_handler(self, symbol: str) -> Any:
        """Lazy-init and return the AMTHandler for *symbol*."""
        if symbol not in self._handlers:
            # Import here to isolate the heavy domain import from pipeline
            # startup and to make unit-testing with mocks straightforward.
            from app.application.handlers.amt_handler import AMTHandler

            self._handlers[symbol] = AMTHandler(session_only_vp=True)
            logger.debug("[%s] Created AMTHandler for symbol %s", self.name, symbol)
        return self._handlers[symbol]

    def _candle_payload_to_ohlc(self, p: CandlePayload) -> Any:
        """Convert a frozen CandlePayload to a float-attribute OHLC-like object.

        AMTHandler._to_float_ohlc expects objects with the attributes:
        time, open, high, low, close, volume, vwap, taker_buy_volume, delta.
        We build a simple namespace here so we stay decoupled from any
        concrete domain model import at this layer.
        """
        from types import SimpleNamespace

        return SimpleNamespace(
            time=p.time,
            open=float(p.open),
            high=float(p.high),
            low=float(p.low),
            close=float(p.close),
            volume=float(p.volume),
            vwap=float(p.vwap),
            # CandlePayload tracks delta but not the raw buy/sell split;
            # taker_buy_volume is derived from positive-delta portion.
            taker_buy_volume=max(0.0, float(p.delta)),
            delta=float(p.delta),
        )

    async def _handle_candle(self, msg: CandleMessage, out: Channel) -> None:
        """Process a single CandleMessage and emit an AMTResultMessage."""
        symbol = msg.symbol
        p: CandlePayload = msg.payload

        history = self._histories[symbol]

        # Only closed candles extend history.  Live bars carry useful price
        # context (most recent close) but must not be committed to history
        # until the bar is complete — appending them early would permanently
        # distort the volume profile.
        if p.closed:
            history.append(p)
            # Enforce lookback window
            if len(history) > self._lookback:
                del history[: len(history) - self._lookback]

        # Need at least one closed candle to analyse; a live-only bar with no
        # history means the session literally just started — skip silently.
        if not history:
            logger.debug(
                "[%s] %s: no closed candles yet, skipping analysis", self.name, symbol
            )
            return

        # Build the OHLC list: all closed history + the live bar (if open).
        # AMTHandler works correctly when the last element is the current bar,
        # whether closed or not.
        ohlc_list = [self._candle_payload_to_ohlc(c) for c in history]
        if not p.closed:
            # Append the live (updating) candle so AMT sees current price context
            ohlc_list.append(self._candle_payload_to_ohlc(p))

        handler = self._get_handler(symbol)
        try:
            amt_result, _amt_dto, _fp_dto = handler.analyze(ohlc_list)
        except Exception:
            logger.error(
                "[%s] AMTHandler.analyze failed for %s", self.name, symbol, exc_info=True
            )
            return

        # Map AMTResult domain object → pipeline payload
        # AMTResultPayload.leg_state maps to AMTResult.market_structure
        # which classifies the leg profile (BALANCE / TREND / etc.).
        amt_payload = AMTResultPayload(
            market_state=amt_result.market_state,
            leg_state=amt_result.market_structure,
            poc=float(amt_result.poc),
            vah=float(amt_result.value_area_high),
            val=float(amt_result.value_area_low),
            cvd_slope=float(amt_result.cvd_slope),
            cvd_divergence=bool(amt_result.cvd_divergence),
            profile_shape=str(amt_result.profile_shape or "D"),
            delta_score=float(amt_result.aggression),
            aggression=(
                "AGGRESSIVE"
                if float(amt_result.aggression) >= 2.5
                else "NEUTRAL"
            ),
            balance_pct=float(amt_result.balance_ratio * 100),
            near_level=False,  # Computed by SignalGateProcessor
            confirmation_score=0,  # Computed by SignalGateProcessor
        )

        result_msg = Message(
            payload=amt_payload,
            symbol=symbol,
            timestamp=msg.timestamp,
            correlation_id=msg.correlation_id,
            source_processor=self.name,
            pipeline_id=msg.pipeline_id,
        )

        await self._safe_send(out, result_msg)
