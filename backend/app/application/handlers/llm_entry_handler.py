"""LLM Entry Handler — LLM inference coordination with delegated gate/signal logic.

This module coordinates LLM inference and delegates to specialized modules:
- EntryGateCoordinator: Gate checking orchestration
- build_entry_signal: Signal building logic (called directly)
- PositionSizer: Position sizing logic
"""

from __future__ import annotations

import concurrent.futures
import logging
import re
import threading
import time
from dataclasses import replace as _replace
from datetime import datetime, timedelta, timezone
import queue
from typing import TYPE_CHECKING, Callable, Optional

# Compiled regex patterns for _sanitize_rationale (avoid per-call compilation)
_UNCLOSED_JSON_RE = re.compile(r'\{[^}]{0,100}$')
_ORPHANED_BRACE_RE = re.compile(r'\}[^{]{0,50}')
_TRAILING_JSON_RE = re.compile(r'[\[{}\]"]\s*$')
_WHITESPACE_RE = re.compile(r'\s+')

from app.shared.symbol_utils import detect_option_type

from app.domain.trading.models.enums import (
    MarketStateCodec,
    SignalType,
    Source,
    SetupType,
)
from app.domain.trading.models.entities import Signal
from app.config import settings
from app.domain.fabio_ai.services.regime_detector import RegimeDetector
from app.domain.fabio_ai.services.exit_engine import ExitEngine as TradeManager
from app.domain.trading.events import SignalGenerated
from app.domain.fabio_ai.services.session_context import get_session_info
from app.shared.parsing import resolve_session_market
from app.domain.fabio_ai.services.entry_gates.signal_builder import build_entry_signal
from app.domain.fabio_ai.services.entry_gates.three_align import cluster_aggressive_prints

# Import delegated modules
from app.application.handlers.entry_gate_coordinator import EntryGateCoordinator
# SignalConstructor removed - use build_entry_signal directly
from app.shared.timezones import IST

from app.domain.fabio_ai.services.position_sizer import PositionSizer

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, AMTResult
    from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService
    from app.domain.ports.storage import IStorage

logger = logging.getLogger(__name__)


class LLMEntryHandler:
    """Handles LLM-based entry decisions with delegated gate/signal logic."""

    def __init__(
        self,
        gen_ai_service: GenerativeAIService,
        storage: IStorage | None = None,
        trade_manager: TradeManager | None = None,
        journal=None,
        exchange: str = "MCX",
        allow_short: bool = False,
        llm_timeout: float = 15.0,
    ) -> None:
        self._gen_ai_service = gen_ai_service
        self._storage = storage
        self._trade_manager = trade_manager
        self._journal = journal
        self._exchange = exchange
        self._allow_short = allow_short  # Use injected allow_short
        self._llm_timeout = llm_timeout
        self._regime_detectors: dict[str, RegimeDetector] = {}
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self._predict_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        # Per-symbol workers for parallel LLM inference across symbols
        # Bounded queue (10) per symbol prevents regime-change storms
        self._llm_queues: dict[str, queue.Queue] = {}
        self._worker_threads: dict[str, threading.Thread] = {}
        self._workers_lock = threading.Lock()

        # Delegated modules
        self._gate_coordinator = EntryGateCoordinator()
        # SignalConstructor removed - build_entry_signal used directly
        self._position_sizer = PositionSizer()

    def session_market_for_symbol(self, symbol: str) -> str:
        """IST session calendar for LLM/session gate — must match tradable venue."""
        return resolve_session_market(self._exchange, symbol)

    # ------------------------------------------------------------------
    # Extracted helpers for _llm_worker_loop (CC reduction)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_session_phase_block_result(session_info, symbol, market_state_str, amt_result, tick) -> dict:
        """Build FLAT result when session phase blocks entry."""
        return {
            "direction": "FLAT",
            "rationale": f"Market in {session_info.session} phase. Entries are blocked by Session Gate.",
            "confidence": "High",
            "input_prompt": f"[SESSION GATE: Bypassed LLM] Market is currently in the {session_info.session} phase. Entering new trades is blocked by system rules until the active trading window resumes.",
            "raw_output": "QUANT_PHASE_BLOCKED",
            "market_state": market_state_str,
        }

    def _save_session_block_decision(self, symbol, market_state_str, amt_result, tick):
        """Persist session block decision to storage."""
        if self._storage:
            try:
                self._storage.save_llm_decision({
                    "symbol": symbol, "direction": "FLAT", "confidence": "High",
                    "rationale": f"Market in session phase block. Entries blocked.",
                    "input_prompt": "", "raw_output": "QUANT_PHASE_BLOCKED",
                    "market_state": market_state_str,
                    "aggression": f"{amt_result.aggression:.4f}",
                    "price": tick.close, "vah": amt_result.value_area_high,
                    "val": amt_result.value_area_low, "poc": amt_result.poc,
                    "delta": tick.delta, "volume": tick.volume,
                    "profile_shape": getattr(amt_result, "profile_shape", ""),
                    "setup_type": "SESSION_BLOCK", "strategy_hint": "",
                })
            except Exception:
                logger.debug("Session block AMT snapshot persistence failed", exc_info=True)

    def _build_strategy_hint(self, amt_result, session_info, symbol, session=None) -> str:
        """Build strategy hint based on market state and session phase."""
        if MarketStateCodec.is_imbalanced(amt_result.market_state) and session_info.allow_trend:
            hint = "Market is IMBALANCED (trending). Favor trend continuation setups. Look for breakouts beyond VA boundaries."
        elif MarketStateCodec.is_imbalanced(amt_result.market_state) and not session_info.allow_trend:
            hint = "Market is IMBALANCED but session phase favors mean reversion only. Look for fades at VA extremes back toward POC."
        else:
            hint = "Market is BALANCED (range-bound). Favor mean reversion setups. Look for fades at VA extremes back toward POC."

        session_hints = {
            "NSE_PRIMARY": "[Primary Setup Window 09:30-11:30 — best window for AAA setups.]",
            "NSE_MIDDAY": "[Midday Consolidation 11:30-14:00 — mean reversion only, no new trend trades.]",
            "NSE_POWER_HOUR": "[Power Hour 14:00-15:15 — second-best window for AAA setups.]",
        }
        hint += session_hints.get(session_info.session, "")

        if session and session.data and self._get_regime_detector(symbol).is_contracting(session.data):
            hint += " [CAUTION: Market is contracting after expansion — prefer Stay Flat or mean reversion only.]"
        return hint

    def _build_profile_description(self, amt_result) -> str:
        """Convert profile shape code to human-readable description."""
        shape_descriptions = {
            "D": "D-shape (balanced, rotational)",
            "P": "P-shape (top-heavy, sellers may be trapped)",
            "b": "b-shape (bottom-heavy, buying absorption)",
            "B": "B-shape (bimodal, two value areas — potential breakout)",
        }
        return shape_descriptions.get(amt_result.profile_shape, "") if amt_result.profile_shape else ""

    def _build_volume_bubble_summary(self, amt_result, tick) -> str:
        """Summarize recent aggressive prints for LLM context."""
        if not amt_result.aggressive_prints:
            return ""
        try:
            time_str = tick.time.replace(".", "", 1).replace("-", "").replace("+", "")
            if time_str.isdigit():
                cutoff_dt = datetime.fromtimestamp(float(tick.time)) - timedelta(seconds=3000)
            else:
                cutoff_dt = datetime.fromisoformat(tick.time.replace("Z", "+00:00")) - timedelta(seconds=3000)
        except (ValueError, OSError):
            cutoff_dt = datetime.now() - timedelta(seconds=3000)

        cutoff_time = cutoff_dt.isoformat()
        recent_prints = [ap for ap in amt_result.aggressive_prints if ap.time >= cutoff_time][-3:]
        parts = [f"{ap.side} bubble at {ap.price:.0f} ({ap.volume:.0f} vol, delta {ap.delta:+.0f})" for ap in recent_prints]
        return "; ".join(parts)

    @staticmethod
    def _get_amt_time_window(ist_now) -> dict:
        """Get current AMT time window for timing transparency.
        
        Fix 4: Exposes Fabio's time-based filters to frontend.
        """
        from app.domain.fabio_ai.services.session_context import get_amt_time_window
        return get_amt_time_window(ist_now)

    def _build_imbalance_summary(self, session) -> str:
        """Extract stacked imbalances from footprint domain."""
        fp_domain = getattr(session, "_last_fp_domain", None)
        if not fp_domain:
            return ""
        try:
            fp_vals = list(fp_domain.values()) if isinstance(fp_domain, dict) else None
            latest_fp = fp_vals[-1] if fp_vals else None
            if latest_fp and hasattr(latest_fp, "levels"):
                stacked = [lv for lv in latest_fp.levels if getattr(lv, "stacked", False)]
                if stacked:
                    parts = []
                    for lv in stacked[:3]:
                        side = getattr(lv, "direction", getattr(lv, "side", "UNKNOWN"))
                        price = getattr(lv, "price", 0)
                        parts.append(f"{side} imbalance at {price:.0f}")
                    return "STACKED IMBALANCES: " + ", ".join(parts)
        except Exception:
            logger.debug("Stacked imbalance extraction for LLM prompt failed", exc_info=True)
        return ""

    @staticmethod
    def _build_institutional_context(amt_result) -> str:
        """Summarize large institutional prints with weighting.
        
        Identifies prints >3x median volume as institutional and flags
        dominant buying or selling pressure that should override CVD slope.
        """
        if not amt_result.aggressive_prints:
            return ""
        
        volumes = [ap.volume for ap in amt_result.aggressive_prints]
        if not volumes:
            return ""
        
        sorted_vols = sorted(volumes)
        median_vol = sorted_vols[len(sorted_vols) // 2]
        threshold = median_vol * 3  # 3x median = institutional
        
        institutional_prints = [ap for ap in amt_result.aggressive_prints if ap.volume > threshold]
        if not institutional_prints:
            return ""
        
        total_inst_vol = sum(ap.volume for ap in institutional_prints)
        buy_inst = sum(ap.volume for ap in institutional_prints if ap.side == "BUY")
        sell_inst = sum(ap.volume for ap in institutional_prints if ap.side == "SELL")
        
        parts = [f"[INSTITUTIONAL ALERT] {len(institutional_prints)} large prints (>{threshold:.0f} vol)"]
        parts.append(f"Total: {total_inst_vol:.0f} | Buy: {buy_inst:.0f} | Sell: {sell_inst:.0f}")
        
        if buy_inst > sell_inst * 1.5:
            parts.append("Dominant: INSTITUTIONAL BUYING")
        elif sell_inst > buy_inst * 1.5:
            parts.append("Dominant: INSTITUTIONAL SELLING")
        
        # Recent large prints (last 3)
        for ap in institutional_prints[-3:]:
            parts.append(f"  {ap.side} {ap.volume:.0f} at {ap.price:.0f}")
        
        return " | ".join(parts)

    def _load_episodic_memory(self) -> str:
        """Load recent trade history for LLM context."""
        if not self._storage:
            return ""
        try:
            _today = datetime.now(IST).strftime("%Y-%m-%d")
            recent_trades = self._storage.get_recent_trades(limit=10)
            if not recent_trades:
                return ""
            today_trades = [t for t in recent_trades if _today in str(t.get("time", ""))]
            if not today_trades:
                today_trades = recent_trades[:5]

            parts = []
            session_pnl = 0.0
            for i, t in enumerate(today_trades, 1):
                side = t.get("side", "?")
                pnl = t.get("pnl", 0)
                reason = t.get("reason", "")
                session_pnl += pnl
                sign = "+" if pnl >= 0 else ""
                parts.append(f"{i}) {side} {sign}Rs{pnl:.0f} ({reason})")

            pnl_sign = "+" if session_pnl >= 0 else ""
            return f"Session P&L: {pnl_sign}Rs{session_pnl:.0f} ({len(today_trades)} trades). " + ", ".join(parts) + "."
        except Exception:
            logger.debug("Failed to load episodic memory", exc_info=True)
            return ""

    def _build_gate_context(self, amt_result, tick, session, session_info, agg_levels, fp_domain) -> str:
        """Build Three-Align gate warning context for LLM."""
        gate_passed, gate_reason, is_second_drive = self._gate_coordinator.check_entry_eligibility(
            data=session.data, amt_result=amt_result, tick=tick,
            order_book=session.order_book, direction="LONG",
            aggressive_levels=agg_levels, footprint_domain=fp_domain,
            session_info=session_info,
        )
        if gate_passed:
            return "", is_second_drive
        return (
            f"[GATE WARNING] Three-Align NOT MET: "
            f"Market state: {amt_result.market_state}, "
            f"Price: {tick.close:.1f}, POC: {amt_result.poc:.1f}, "
            f"VAH: {amt_result.value_area_high:.1f}, VAL: {amt_result.value_area_low:.1f}. "
            f"You must have STRONG conviction to override. "
        ), is_second_drive

    def _build_market_data_ai(self, symbol, session, tick, amt_result, session_info,
                               setup_type, strategy_hint, profile_shape_str, market_state_str,
                               gate_context, is_second_drive, session_context_for_llm) -> dict:
        """Build the complete market data dictionary for LLM inference."""
        # Session elapsed time
        from app.domain.fabio_ai.services.session_context import _to_ist
        ist_now = _to_ist(tick.time)
        market_open = ist_now.replace(hour=9, minute=15, second=0, microsecond=0)
        elapsed_min = max(0, (ist_now - market_open).total_seconds() / 60)

        # Prior cycle context
        prior_context = []
        with session._lock:
            memory = getattr(session, "_llm_memory", [])
            for m in memory[-2:]:
                prior_context.append(f"[PRIOR CYCLE]: {m}")

        # Quant context
        agent_decision = getattr(session, "_agent_decision", None)
        quant_context = {}
        if agent_decision:
            agent_regime = getattr(agent_decision, "regime", "")
            if agent_regime == "DEAD":
                return None, "DEAD"  # Signal DEAD regime
            quant_context = {
                "probability": round(getattr(agent_decision, "probability", 0.5), 3),
                "has_edge": abs(getattr(agent_decision, "probability", 0.5) - 0.5) >= 0.10,
                "regime": agent_regime,
                "direction": agent_decision.direction,
                "note": "If P is near 0.5, structural/aggression context MUST outweigh this quant estimate."
            }

        market_data_ai = {
            "ltp": tick.close, "delta": tick.delta, "volume": tick.volume,
            "vah": amt_result.value_area_high, "val": amt_result.value_area_low,
            "poc": amt_result.poc, "market_state": market_state_str,
            "aggression": amt_result.aggression,
            "profile_shape": getattr(amt_result, "profile_shape", profile_shape_str),
            "session_elapsed_minutes": round(elapsed_min, 1),
            "prior_analysis_context": "\n".join(prior_context),
            "quant_context": quant_context,
            "strategy_hint": strategy_hint,
            "volume_bubbles": self._build_volume_bubble_summary(amt_result, tick),
            "institutional_context": self._build_institutional_context(amt_result),
            "stacked_imbalances": self._build_imbalance_summary(session),
            "hvns": amt_result.hvns[:3] if amt_result.hvns else (),
            "lvns": amt_result.lvns[:3] if amt_result.lvns else (),
            "cvd_slope": amt_result.cvd_slope, "cvd_divergence": amt_result.cvd_divergence,
            "vwap": amt_result.session_vwap if amt_result.session_vwap > 0 else tick.vwap,
            "leg_poc": amt_result.leg_poc,
            "leg_lvns": amt_result.leg_lvns[:3] if amt_result.leg_lvns else (),
            "opening_relation": session_info.opening_relation,
            "market_structure": amt_result.market_structure,
            "structure_confidence": amt_result.structure_confidence,
            "balance_ratio": amt_result.balance_ratio,
            "episodic_memory": self._load_episodic_memory(),
            "gate_context": session_context_for_llm + gate_context,
            "ib_high": amt_result.ib_high, "ib_low": amt_result.ib_low,
            "ib_complete": amt_result.ib_complete,
            "prior_poc": amt_result.prior_poc, "prior_vah": amt_result.prior_vah,
            "prior_val": amt_result.prior_val, "gap_type": amt_result.gap_type,
            "opening_bias": amt_result.opening_bias,
            "acceptance_above": amt_result.acceptance_above,
            "acceptance_below": amt_result.acceptance_below,
            "rejection_at_high": amt_result.rejection_at_high,
            "rejection_at_low": amt_result.rejection_at_low,
            "absorption_side": getattr(amt_result, "absorption_side", ""),
            "absorption_range_ratio": getattr(amt_result, "absorption_range_ratio", 0.0),
            "absorption_vol_ratio": getattr(amt_result, "absorption_vol_ratio", 0.0),
            "price_velocity": amt_result.price_velocity,
            "break_direction": amt_result.break_direction,
            "break_type": amt_result.break_type, "break_level": amt_result.break_level,
            "poc_signal": amt_result.poc_signal, "poc_vs_price": amt_result.poc_vs_price,
            "lvn_play": amt_result.lvn_play, "is_second_drive": is_second_drive,
            # Fix 1: Option type detection for direction labeling
            "option_type": detect_option_type(symbol),
            # Fix 4: AMT time window for timing transparency
            "amt_time_window": self._get_amt_time_window(ist_now),
        }

        # ML signal for LLM meta-filter
        agent = getattr(session, "_agent_decision", None)
        if agent and agent.direction != "FLAT":
            market_data_ai["ml_signal"] = {
                "direction": agent.direction, "probability": agent.probability,
                "regime": agent.regime,
            }
        return market_data_ai, "OK"

    @staticmethod
    def _enrich_market_context(market_data_ai: dict, amt_result) -> None:
        """Add contextual warning flags to market_data_ai for LLM prompt."""
        if amt_result.aggression < 1.0:
            market_data_ai["aggression_warning"] = "Weak aggression — higher risk"
        if amt_result.market_state == "IMBALANCED":
            market_data_ai["drive_warning"] = "First drive — wait for second if possible"
        if abs(amt_result.cvd_slope) > 50:
            market_data_ai["cvd_warning"] = (
                f"Extreme CVD ({amt_result.cvd_slope:.0f}) — respect institutional pressure"
            )

    @staticmethod
    def _resolve_fallback_direction(session, amt_result) -> str:
        """Determine fallback direction when LLM is bypassed or times out."""
        _ml_dir = getattr(session, "_agent_decision", None)
        if _ml_dir and getattr(_ml_dir, "direction", "FLAT") != "FLAT":
            return _ml_dir.direction
        if getattr(amt_result, "signal", None):
            if amt_result.signal.type == SignalType.BUY:
                return "LONG"
            else:
                return "SHORT"
        return "FLAT"

    @staticmethod
    def _compute_journal_attribution(_agent, direction: str) -> str:
        """Determine attribution string for journaling (LLM vs Quant agreement)."""
        if not _agent:
            return "llm_only"
        if _agent.direction == direction and direction != "FLAT":
            return "llm_plus_quant_agree"
        if _agent.direction not in ("", "FLAT", direction):
            return "llm_override_quant"
        return "llm_only"

    @staticmethod
    def _is_extreme_volatility(amt_result) -> bool:
        """Check if market conditions warrant LLM bypass."""
        return (
            getattr(amt_result, "market_structure", "") == "EXPANSION"
            or getattr(amt_result, "price_velocity", 0) > 5.0
        )

    @staticmethod
    def _mark_ai_done(session, worker_queue) -> None:
        """Reset session AI flag. Mark queue task done is handled by main loop."""
        with session._lock:
            session._ai_running = False
            session._llm_status = "AVAILABLE"

    @staticmethod
    def _sanitize_rationale(raw_rationale: str, direction: str) -> str:
        """Sanitize LLM rationale output to remove JSON artifacts and clean text.
        
        Prevents raw JSON from bleeding into UI and database storage.
        
        Args:
            raw_rationale: Raw rationale text from LLM (may contain JSON artifacts)
            direction: Trade direction (LONG/SHORT/FLAT)
            
        Returns:
            Clean rationale text suitable for UI display and database storage
        """
        import json
        
        if not raw_rationale:
            return f"{direction} signal — no rationale provided"
        
        text = raw_rationale.strip()
        
        # Try to extract from JSON if the entire response is JSON
        if text.startswith('{') or '"direction"' in text:
            try:
                # Try direct JSON parse
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    # Extract rationale field if present
                    if 'rationale' in parsed:
                        return str(parsed['rationale']).strip()
                    # If no rationale but has direction, return direction
                    if 'direction' in parsed:
                        return f"{parsed['direction']} signal based on market analysis"
            except (json.JSONDecodeError, ValueError):
                pass
            
            # Try to extract JSON block from mixed text
            json_match = re.search(r'\{[^}]*"rationale"[^}]*\}', text, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group(0))
                    if 'rationale' in parsed:
                        return str(parsed['rationale']).strip()
                except (json.JSONDecodeError, ValueError):
                    pass
        
        # Remove JSON-like artifacts at the end (truncated JSON)
        text = _UNCLOSED_JSON_RE.sub('', text)  # Remove unclosed JSON at end
        text = _ORPHANED_BRACE_RE.sub('', text)  # Remove orphaned closing brace

        # Remove HTML tags to prevent stored XSS (ITR-3-003)
        text = re.sub(r'<[^>]+>', '', text)

        # Remove trailing JSON fragments
        text = _TRAILING_JSON_RE.sub('', text)
        
        # Remove escaped characters
        text = text.replace('\\n', ' ').replace('\\t', ' ').replace('\\"', '"')
        
        # Clean up whitespace
        text = _WHITESPACE_RE.sub(' ', text).strip()
        
        # If text is now empty, return generic message
        if not text:
            return f"{direction} signal based on market analysis"
        
        return text

    def _check_direction_mismatch(self, _ad, direction: str, symbol: str,
                                  session, worker_queue) -> bool:
        """Check if agent decision conflicts with LLM direction. Returns True if mismatch."""
        if (
            _ad
            and _ad.direction in ("LONG", "SHORT")
            and _ad.direction != direction
        ):
            if self._journal:
                self._journal.log_rejection(
                    symbol=symbol,
                    reason="AGENT_DIRECTION_MISMATCH",
                    amt=session.last_amt,
                    llm_direction=direction,
                )
            self._mark_ai_done(session, worker_queue)
            return True
        return False

    def _apply_safety_nets(self, direction: str, confidence: str, rationale: str,
                           tick, amt_result) -> tuple:
        """Apply post-LLM safety nets: buy-only mode, VWAP extreme check.
        
        Returns (direction, confidence, rationale) possibly modified.
        """
        # Buy-only mode
        if direction == "SHORT" and not self._allow_short:
            logger.info("BUY-ONLY mode: SHORT blocked → FLAT")
            direction = "FLAT"
            rationale = "System in BUY-ONLY mode"

        # VWAP EXTREME check: LONG at >+2σ is suspicious
        if (
            direction == "LONG"
            and amt_result.vwap_upper_2 > 0
            and tick.close >= amt_result.vwap_upper_2 * 1.01
        ):
            logger.info(
                "VWAP EXTREME: LONG at >+2σ — institutional anomaly (price=%.2f, band=%.2f)",
                tick.close,
                amt_result.vwap_upper_2,
            )
            confidence = "Low"
            rationale += " [VWAP extreme: >+2σ]"

        return direction, confidence, rationale

    def _process_build_signal(self, symbol, session, tick, direction, setup_type,
                              ai_result, confidence, market_state_str, session_info,
                              amt_result, profile_shape_str, strategy_hint,
                              worker_queue) -> None:
        """Check re-entry gates, circuit breakers, and build signal if eligible.
        
        Extracted from _llm_worker_loop for readability and CC reduction.
        
        TODO(Task 51): Simplify - this method should return the raw LLM decision dict
        instead of building signals. The caller (trading_session) should use SignalPipeline
        to validate gates and create signals. This keeps LLMEntryHandler focused on
        LLM inference management only.
        """
        _ad = getattr(session, "_agent_decision", None)
        if self._check_direction_mismatch(_ad, direction, symbol, session, worker_queue):
            return

        with session._lock:
            live_positions = [
                p for p in session.portfolio.positions if p.status == "OPEN"
            ]
            if not live_positions:
                
                # Circuit breaker check
                _det = self._get_regime_detector(symbol)
                if _det.is_circuit_breaker_active():
                    logger.info(
                        "Circuit breaker blocked %s entry for %s",
                        direction,
                        symbol,
                    )
                    if self._journal:
                        self._journal.log_rejection(
                            symbol=symbol,
                            reason="CIRCUIT_BREAKER",
                            amt=session.last_amt,
                            llm_direction=direction,
                        )
                    return

                # Re-entry gate check
                _squeeze = _det.detect_squeeze(session.data, amt_result)
                from app.domain.fabio_ai.services.entry_gates.confirmation_bundle import compute_atr
                _atr = compute_atr(session.data, 14)

                if _det.is_re_entry_blocked(
                    tick.close,
                    direction,
                    session_info.phase,
                    squeeze_active=bool(_squeeze and _squeeze.direction == direction),
                    atr=_atr,
                ):
                    if self._journal:
                        self._journal.log_rejection(
                            symbol=symbol,
                            reason="RE_ENTRY_BLOCKED",
                            amt=session.last_amt,
                            llm_direction=direction,
                        )
                    return
                
                # Max trades check removed — _session_risk_manager no longer exists on SessionState
                # Risk capping is now handled by SessionRiskCoordinator at the engine level

                _cushion_sl = None  # TODO: source from SessionRiskCoordinator when available
                from app.domain.fabio_ai.services.exit_engine import ExitEngine as TradeManager
                from app.config import settings

                entry_signal = build_entry_signal(
                    direction=direction,
                    tick=tick,
                    amt_result=amt_result,
                    ai_result=ai_result,
                    setup_type=setup_type,
                    data=session.data,
                    risk_sl_pct=_cushion_sl,
                    session_context=session_info.session,
                    confidence=confidence,
                    inside_extreme=settings.SL_INSIDE_EXTREME,
                )

                if (
                    not entry_signal
                    or not TradeManager.is_valid_rr(
                        entry_signal.price,
                        entry_signal.stop_loss,
                        entry_signal.take_profit,
                    )
                ):
                    if self._journal:
                        self._journal.log_rejection(
                            symbol=symbol,
                            reason="RR_FILTER",
                            amt=session.last_amt,
                            llm_direction=direction,
                        )
                else:
                    logger.info(
                        "LLM inference complete — advisory-only signal for %s",
                        symbol,
                    )
                    if self._journal:
                        self._journal.log_rejection(
                            symbol=symbol,
                            reason="LLM_ADVISORY_ONLY",
                            amt=session.last_amt,
                            llm_direction=direction,
                            decision_source="llm",
                            attribution=self._compute_journal_attribution(_ad, direction),
                            trade_thesis=(
                                entry_signal.metadata or {}
                            ).get("trade_thesis"),
                        )

    def _get_regime_detector(self, symbol: str) -> RegimeDetector:
        """Return per-symbol RegimeDetector, creating one if needed."""
        det = self._regime_detectors.get(symbol)
        if det is not None:
            return det
        with self._workers_lock:
            if symbol not in self._regime_detectors:
                self._regime_detectors[symbol] = RegimeDetector()
            return self._regime_detectors[symbol]

    def should_run(
        self,
        last_ai_time: float,
        ai_running: bool,
        has_position: bool,
        has_managed_positions: bool,
        in_cooldown: bool,
        last_entry_time: float = 0,
        data: list | None = None,
        amt_result: AMTResult | None = None,
        tick: OHLC | None = None,
        order_book=None,
    ) -> bool:
        """Check if LLM entry logic should run."""
        import time as _time

        # Guard against degenerate AMT data
        if amt_result.poc <= 0 or amt_result.value_area_high <= 0:
            logger.debug(
                "LLM blocked: degenerate AMT (poc=%.1f vah=%.1f)",
                amt_result.poc,
                amt_result.value_area_high,
            )
            return False

        if ai_running:
            return False

        # Only block if THIS specific symbol already has an open position
        if has_position:
            logger.debug("LLM blocked: symbol already has an open position")
            return False

        # Don't call until model is loaded
        if not self._gen_ai_service.is_ready():
            logger.info(
                "LLM blocked: model not ready (is_loading=%s)",
                not self._gen_ai_service.is_ready(),
            )
            return False

        # Fix-429: Extended cooldown between LLM calls to prevent rate limiting
        # 30s minimum between calls (was 10s) — prevents hammering during error loops
        elapsed = _time.time() - last_ai_time
        if elapsed < 30:
            return False

        # DEAD session gate: don't waste LLM API calls on every new candle
        # when market is dead. The monitoring_trigger path (every 5 min in
        # BALANCED/NO_TRADE) still provides periodic context updates.
        if amt_result and amt_result.market_state == "DEAD":
            logger.debug(
                "LLM blocked: DEAD market — skip candle-triggered LLM for %s",
                getattr(amt_result, '_symbol', ''),
            )
            return False

        return True

    def run_entry(
        self,
        session,
        symbol: str,
        tick: OHLC,
        amt_result: AMTResult,
    ) -> None:
        """Run LLM entry analysis in background thread."""
        with session._lock:
            session._last_ai_time = time.time()
            session._ai_running = True
            session._llm_status = "RUNNING"

        market_state_str = (
            "Trending" if MarketStateCodec.is_imbalanced(amt_result.market_state) else "Balanced"
        )

        # Session-aware setup bias
        prior = getattr(session, "_prior_profile", None)
        prior_vah = prior.get("vah", 0) if prior else 0
        prior_val = prior.get("val", 0) if prior else 0
        open_price = session.data[0].open if session.data else 0
        _market = self.session_market_for_symbol(symbol)
        session_info = get_session_info(
            timestamp=tick.time, market=_market, open_price=open_price,
            prior_vah=prior_vah, prior_val=prior_val,
        )

        # Session phase gate — block entries in restricted phases
        if not session_info.allow_entry:
            logger.info("SESSION GATE: Phase %s blocks entries — skipping LLM for %s",
                        session_info.session, symbol)
            ai_result = self._build_session_phase_block_result(
                session_info, symbol, market_state_str, amt_result, tick
            )
            with session._lock:
                session.last_ai_analysis = ai_result
                session._ai_running = False
                session._llm_status = "AVAILABLE"
            self._save_session_block_decision(symbol, market_state_str, amt_result, tick)
            return

        # Session context for LLM
        session_context_for_llm = (
            "Trend setups allowed. " if session_info.allow_trend else "Mean-reversion only. "
        )

        # Gate checking
        agg_levels = cluster_aggressive_prints(amt_result.aggressive_prints)
        prior_prints = getattr(session, "_prior_print_levels", [])
        fp_domain = getattr(session, "_last_fp_domain", None)
        gate_context, is_second_drive = self._build_gate_context(
            amt_result, tick, session, session_info, agg_levels + prior_prints, fp_domain
        )

        # Setup type determination
        if MarketStateCodec.is_imbalanced(amt_result.market_state) and session_info.allow_trend:
            setup_type = SetupType.TREND_MODEL
        else:
            setup_type = SetupType.MEAN_REVERSION

        strategy_hint = self._build_strategy_hint(amt_result, session_info, symbol, session)
        profile_shape_str = self._build_profile_description(amt_result)

        # Build market data for LLM
        market_data_ai, regime_status = self._build_market_data_ai(
            symbol, session, tick, amt_result, session_info, setup_type,
            strategy_hint, profile_shape_str, market_state_str,
            gate_context, is_second_drive, session_context_for_llm,
        )

        if regime_status == "DEAD":
            logger.info("QUANT GATE: Market regime=DEAD — skipping LLM for %s", symbol)
            agent_decision = getattr(session, "_agent_decision", None)
            if agent_decision:
                agent_decision = _replace(agent_decision, timing="SKIP")
            ai_result = {
                "direction": "FLAT",
                "rationale": "DEAD market: volume < 5% of average. No trade.",
                "confidence": "High",
                "input_prompt": "[QUANT GATE: Bypassed LLM] Market regime is DEAD (no volume). Waiting for expansion.",
                "raw_output": "QUANT_DEAD_MARKET",
                "market_state": market_state_str,
            }
            with session._lock:
                session.last_ai_analysis = ai_result
                session._ai_running = False
                session._llm_status = "AVAILABLE"
            return

        # Enqueue for per-symbol LLM worker
        with self._workers_lock:
            if symbol not in self._llm_queues:
                self._llm_queues[symbol] = queue.Queue(maxsize=10)
                wt = threading.Thread(
                    target=self._llm_worker_loop, args=(symbol,),
                    daemon=True, name=f"LLM-Worker-{symbol}",
                )
                self._worker_threads[symbol] = wt
                wt.start()

        item = {
            "session": session, "symbol": symbol, "tick": tick,
            "amt_result": amt_result, "market_data_ai": market_data_ai,
            "setup_type": setup_type, "session_info": session_info,
            "strategy_hint": strategy_hint, "profile_shape_str": profile_shape_str,
            "market_state_str": market_state_str, "enqueue_time": time.time(),
        }
        try:
            self._llm_queues[symbol].put_nowait(item)
            logger.debug(f"Queued LLM analysis for {symbol}")
        except queue.Full:
            logger.warning(f"LLM Queue full, dropping analysis for {symbol}")
            with session._lock:
                session._ai_running = False
                session._llm_status = "AVAILABLE"

    def _llm_worker_loop(self, queue_symbol: str) -> None:
        """Dedicated background thread that processes LLM requests sequentially for a specific symbol."""

        with self._workers_lock:
            worker_queue = self._llm_queues.get(queue_symbol)

        if not worker_queue:
            logger.error(f"Worker for {queue_symbol} started but no queue found!")
            return

        while True:
            try:
                item = worker_queue.get()
                if item is None:
                    break

                task_done_called = False  # Track to prevent double task_done()
                enqueue_time = item["enqueue_time"]
                session = item["session"]
                symbol = item["symbol"]
                tick = item["tick"]
                amt_result = item["amt_result"]
                market_data_ai = item["market_data_ai"]
                setup_type = item["setup_type"]
                session_info = item["session_info"]
                strategy_hint = item["strategy_hint"]
                profile_shape_str = item["profile_shape_str"]
                market_state_str = item["market_state_str"]

                # Staleness check
                # Tightened to 20s (from 30s) to ensuring we don't start stale inferences
                if time.time() - enqueue_time > 20.0:
                    logger.warning(
                        f"Dropping stale LLM request for {symbol} (queued {time.time() - enqueue_time:.1f}s ago)"
                    )
                    with session._lock:
                        session._ai_running = False
                        session._llm_status = "AVAILABLE"
                    if not task_done_called:
                        worker_queue.task_done()
                        task_done_called = True
                    continue

                if not self._gen_ai_service.is_ready():
                    with session._lock:
                        session.last_ai_analysis = {
                            "direction": "FLAT",
                            "rationale": "Model loading...",
                            "confidence": "Low",
                        }
                        session._ai_running = False
                        session._llm_status = "AVAILABLE"
                    worker_queue.task_done()
                    continue

                # Add context flags to market_data_ai
                self._enrich_market_context(market_data_ai, amt_result)

                # Refresh volatile fields from latest AMT result on session.
                # The LLM worker runs asynchronously — by the time it processes,
                # the aggression/cvd_slope/ofi/delta values from enqueue-time may
                # be stale (e.g., "neutral aggression" vs live display showing +1.50).
                # This mirrors the existing LTP refresh pattern below.
                try:
                    _latest_amt = session.last_amt
                    if _latest_amt:
                        market_data_ai["aggression"] = _latest_amt.get("aggression", market_data_ai.get("aggression", 0))
                        market_data_ai["cvd_slope"] = _latest_amt.get("cvdSlope", market_data_ai.get("cvd_slope", 0))
                        market_data_ai["ofi"] = _latest_amt.get("ofi", market_data_ai.get("ofi", 0))
                        market_data_ai["delta"] = _latest_amt.get("deltaNormalizedOption", _latest_amt.get("delta", market_data_ai.get("delta", 0)))
                        _new_ms = _latest_amt.get("marketState", "")
                        if _new_ms:
                            market_data_ai["market_state"] = _new_ms
                except Exception:
                    pass  # Non-critical — stale values are acceptable during active inference

                # Update LTP to use the absolute latest tick to avoid stale context during inference delay
                try:
                    if session.data:
                        market_data_ai["ltp"] = session.data[-1].close
                except Exception:
                    pass  # LTP refresh failure — non-critical; stale LTP is acceptable during active inference
                try:
                    is_extreme_volatility = self._is_extreme_volatility(amt_result)
                except Exception:
                    is_extreme_volatility = False
                try:
                    fallback_direction = self._resolve_fallback_direction(
                        session, amt_result
                    )
                except Exception:
                    fallback_direction = "FLAT"

                try:
                    predict_future = None
                    if is_extreme_volatility and fallback_direction != "FLAT":
                        logger.warning(
                            f"Extreme volatility detected. Bypassing LLM. Using: {fallback_direction}"
                        )
                        ai_result = {
                            "direction": fallback_direction,
                            "rationale": "Volatility bypass — quant signal",
                            "confidence": "High",
                            "input_prompt": f"[VOLATILITY GATE: Bypassed LLM] Extreme volatility detected in the market. The LLM call has been skipped to ensure execution speed, and we are relying on the Quant engine's {fallback_direction} signal.",
                            "raw_output": "QUANT_FALLBACK",
                            "market_state": market_state_str,
                        }
                    else:
                        predict_future = self._predict_executor.submit(
                            self._gen_ai_service.analyze_market,
                            market_data_ai,
                        )
                        ai_result = predict_future.result(timeout=self._llm_timeout)
                except concurrent.futures.TimeoutError:
                    if predict_future is not None:
                        predict_future.cancel()
                    logger.warning(
                        "LLM timed out after %.0fs — using fallback",
                        self._llm_timeout,
                    )
                    if fallback_direction != "FLAT":
                        ai_result = {
                            "direction": fallback_direction,
                            "rationale": "Timeout fallback — quant signal",
                            "confidence": "Medium",
                            "input_prompt": f"[TIMEOUT GATE: LLM Request Aborted] The LLM failed to respond within the {self._llm_timeout}s timeout limit. Falling back to the Quant engine's {fallback_direction} signal.",
                            "raw_output": "TIMEOUT_FALLBACK",
                            "market_state": market_state_str,
                        }
                    else:
                        with session._lock:
                            session._ai_running = False
                            session._llm_status = "AVAILABLE"
                        worker_queue.task_done()
                        continue
                except Exception as e:
                    logger.error(f"LLM inference exception: {e}", exc_info=True)
                    with session._lock:
                        session._ai_running = False
                        session._llm_status = "AVAILABLE"
                    worker_queue.task_done()
                    continue

                # Final safety guard against malformed ai_result
                if not ai_result or not isinstance(ai_result, dict):
                    logger.error(f"LLM worker received invalid ai_result: {ai_result}")
                    with session._lock:
                        session._ai_running = False
                        session._llm_status = "AVAILABLE"
                    worker_queue.task_done()
                    continue

                direction = ai_result.get("direction", "FLAT")
                confidence = ai_result.get("confidence", "Low")
                raw_rationale = ai_result.get("rationale", "System error: invalid AI return")
                
                # CONSISTENCY GUARD: Prevent rapid confidence flips (Block 1.4)
                # Track last LLM evaluation to prevent contradictions within 60s
                current_time = time.time()
                min_interval = 60  # seconds
                
                last_eval_time = getattr(session, '_last_llm_evaluation_time', 0)
                last_confidence = getattr(session, '_last_llm_confidence', "Medium")
                last_direction = getattr(session, '_last_llm_direction', "FLAT")
                
                # Check if we're within the minimum re-evaluation interval
                if current_time - last_eval_time < min_interval:
                    logger.info(
                        "LLM re-evaluation skipped: %.1fs since last evaluation (min %ds)",
                        current_time - last_eval_time,
                        min_interval,
                    )
                    # Hold previous decision
                    direction = last_direction
                    confidence = last_confidence
                    rationale = "Held from previous evaluation (cooldown active)"
                else:
                    # CONSISTENCY GUARD: Check for High→Low confidence flips
                    if (last_confidence == "High" and 
                        confidence in ["Low", "None"] and
                        direction == "FLAT"):
                        logger.warning(
                            "LLM CONSISTENCY VIOLATION: High→%s confidence flip within %.1fs. "
                            "Previous: %s %s, Current: %s %s. Holding previous decision.",
                            confidence,
                            current_time - last_eval_time,
                            last_direction,
                            last_confidence,
                            direction,
                            confidence,
                        )
                        # Hold previous decision instead of flipping
                        direction = last_direction
                        confidence = last_confidence
                        rationale = "CONSISTENCY GUARD: Prevented High→Low flip"
                    else:
                        # Sanitize and apply safety nets as normal
                        rationale = self._sanitize_rationale(raw_rationale, direction)
                        direction, confidence, rationale = self._apply_safety_nets(
                            direction, confidence, rationale, tick, amt_result
                        )
                    
                    # Update tracking
                    session._last_llm_evaluation_time = current_time
                    session._last_llm_confidence = confidence
                    session._last_llm_direction = direction
                logger.info(
                    "LLM result: direction=%s confidence=%s", direction, confidence
                )

                # Journal logging
                if self._journal:
                    try:
                        _agent = getattr(session, "_agent_decision", None)
                        self._journal.log_signal(
                            symbol=symbol,
                            amt=session.last_amt,
                            llm_direction=direction,
                            llm_confidence=confidence,
                            llm_rationale=ai_result.get("rationale", ""),
                            agent_direction=_agent.direction if _agent else "",
                            agent_regime=_agent.regime if _agent else "",
                            agent_feature_drivers=getattr(_agent, "feature_drivers", ())
                            if _agent
                            else (),
                            probability_long=_agent.probability
                            if _agent and _agent.direction == "LONG"
                            else 0,
                            probability_short=_agent.probability
                            if _agent and _agent.direction == "SHORT"
                            else 0,
                            decision_source="llm",
                            attribution=self._compute_journal_attribution(_agent, direction),
                        )
                    except Exception:
                        logger.warning("Journal log_signal failed", exc_info=True)

                # Use delegated modules for gate checking and signal construction
                if direction in ("LONG", "SHORT"):
                    # Delegate gate checking
                    gate_passed, gate_reason, is_second_drive = (
                        self._gate_coordinator.check_entry_eligibility(
                            data=session.data,
                            amt_result=amt_result,
                            tick=tick,
                            order_book=session.order_book,
                            direction=direction,
                            session_info=session_info,
                        )
                    )

                    if not gate_passed:
                        logger.info(
                            "Gate check failed for %s: %s", direction, gate_reason
                        )
                        if self._journal:
                            self._journal.log_rejection(
                                symbol=symbol,
                                reason=gate_reason,
                                amt=session.last_amt,
                                llm_direction=direction,
                            )
                        direction = "FLAT"
                        rationale += f" [GATE BLOCKED: {gate_reason}]"

                # Save LLM decision & Update Memory
                with session._lock:
                    # Include quant engine probability for Monitor panel consistency
                    _agent = getattr(session, "_agent_decision", None)
                    _quant_p = _agent.probability if _agent else 0.0
                    _quant_dir = _agent.direction if _agent else ""
                    
                    # Use sanitized rationale (already cleaned by _sanitize_rationale)
                    cleaned_rationale = rationale
                    session.last_ai_analysis = {
                        "direction": direction,
                        "rationale": cleaned_rationale,
                        "confidence": confidence,
                        "input_prompt": ai_result.get("input_prompt", ""),
                        "raw_output": ai_result.get("raw_output", ""),
                        "market_state": ai_result.get("market_state", "Unknown"),
                        "aggression": ai_result.get("aggression", "0.00"),
                        "quant_probability": round(_quant_p, 3),
                        "quant_direction": _quant_dir,
                    }
                    
                    # Update memory for next cycle (direction + short summary)
                    summary = f"{direction}: {cleaned_rationale[:100]}..."
                    if not hasattr(session, "_llm_memory"):
                        session._llm_memory = []
                    session._llm_memory.append(summary)
                    if len(session._llm_memory) > 5:  # Buffer extra but cap strictly in prompt
                        session._llm_memory = session._llm_memory[-5:]

                # Persist LLM decision
                if self._storage:
                    try:
                        self._storage.save_llm_decision(
                            {
                                "symbol": symbol,
                                "direction": direction,
                                "confidence": confidence,
                                "rationale": ai_result["rationale"],
                                "input_prompt": ai_result.get("input_prompt", ""),
                                "raw_output": ai_result.get("raw_output", ""),
                                "market_state": market_state_str,
                                "aggression": f"{amt_result.aggression:.4f}",
                                "price": tick.close,
                                "vah": amt_result.value_area_high,
                                "val": amt_result.value_area_low,
                                "poc": amt_result.poc,
                                "delta": tick.delta,
                                "volume": tick.volume,
                                "profile_shape": profile_shape_str,
                                "setup_type": setup_type.value,
                                "strategy_hint": strategy_hint,
                            }
                        )
                    except Exception:
                        logger.warning("LLM decision persistence to storage failed", exc_info=True)

                # Build signal using build_entry_signal (via _process_build_signal)
                # TODO(Task 51): Simplify - return raw LLM decision and let caller use SignalPipeline
                self._process_build_signal(
                    symbol, session, tick, direction, setup_type, ai_result,
                    confidence, market_state_str, session_info, amt_result,
                    profile_shape_str, strategy_hint, worker_queue,
                )


                with session._lock:
                    session._ai_running = False
                    session._llm_status = "AVAILABLE"

                if not task_done_called:
                    worker_queue.task_done()
                    task_done_called = True

            except Exception as e:
                logger.error(f"Worker loop fatal error: {e}", exc_info=True)
                try:
                    if "session" in locals() and session:
                        with session._lock:
                            session._ai_running = False
                            session._llm_status = "AVAILABLE"
                except Exception:
                    pass  # Cleanup: _ai_running reset failed — next heartbeat will time out and clear
                try:
                    if not task_done_called:
                        worker_queue.task_done()
                        task_done_called = True
                except Exception:
                    pass  # Cleanup: task_done on already-processed item — queue may be drained

    def record_stop_out(
        self, level: float, direction: str, session_phase: int, symbol: str = ""
    ) -> None:
        """Record a stopped-out position so re-entry at the same level is blocked."""
        self._get_regime_detector(symbol).record_failed_entry(
            level, direction, session_phase
        )

    def record_successful_exit(self, symbol: str = "") -> None:
        """Reset consecutive stop counter on a profitable exit."""
        self._get_regime_detector(symbol).record_successful_exit()

    def clear_failed_entries(self, symbol: str = "") -> None:
        """Clear failed entry records — call on new session start."""
        if symbol:
            self._get_regime_detector(symbol).clear_failed_entries()
        else:
            with self._workers_lock:
                for det in self._regime_detectors.values():
                    det.clear_failed_entries()

    def cleanup(self) -> None:
        """Shutdown thread pools on handler destruction."""
        for pool_attr in ("_executor", "_predict_executor"):
            pool = getattr(self, pool_attr, None)
            if pool:
                pool.shutdown(wait=False)
        with self._workers_lock:
            for q in self._llm_queues.values():
                try:
                    q.put_nowait(None)
                except queue.Full:
                    pass
