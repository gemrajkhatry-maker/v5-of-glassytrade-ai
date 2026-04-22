"""Prompt Engineering Service — dedicated prompt building for LLM inference.

Extracted from LLMEntryHandler to separate concerns:
- LLMEntryHandler: orchestration (should_run, queue management, gate evaluation)
- PromptEngineeringService: prompt construction (market data formatting, context building)

This makes prompt iteration easier — changes to prompts don't require
modifying the 500-line worker loop.

Usage:
    prompt_service = PromptEngineeringService()
    market_data_ai = prompt_service.build_market_data_ai(ctx, session_info)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from app.domain.fabio_ai.services.entry_gates.three_align import cluster_aggressive_prints, three_align_check
from app.domain.trading.models.enums import MarketStateCodec

if TYPE_CHECKING:
    from app.domain.trading.models.trading_context import TradingContext
    from app.domain.fabio_ai.services.session_context import SessionInfo

logger = logging.getLogger(__name__)

from app.shared.timezones import IST


class PromptEngineeringService:
    """Builds market data dictionaries for LLM prompt construction.

    Single responsibility: Format market context into the structure
    expected by the LLM prompt builder.
    """

    @staticmethod
    def build_market_data_ai(
        ctx: TradingContext,
        session_info: SessionInfo,
        agent_decision=None,
        session_data: list | None = None,
        prior_print_levels: list | None = None,
        episodic_memory: str = "",
        gate_context: str = "",
        is_second_drive: bool = False,
        aggressive_prints=None,
    ) -> dict:
        """Build the market_data_ai dict for LLM prompt.

        Contains all context the LLM needs to make a decision.
        """
        # Profile shape description
        profile_shape_str = ""
        if ctx.profile_shape:
            shape_descriptions = {
                "D": "D-shape (balanced, rotational)",
                "P": "P-shape (top-heavy, sellers may be trapped)",
                "b": "b-shape (bottom-heavy, buying absorption)",
                "B": "B-shape (bimodal, two value areas — potential breakout)",
            }
            profile_shape_str = shape_descriptions.get(ctx.profile_shape, "")

        # Volume bubble summary
        volume_bubble_desc = ""
        if aggressive_prints:
            try:
                cutoff_dt = datetime.now() - timedelta(seconds=3000)
                cutoff_time = cutoff_dt.isoformat()
                recent_prints = [ap for ap in aggressive_prints if ap.time >= cutoff_time][-3:]
                bubble_parts = []
                for ap in recent_prints:
                    bubble_parts.append(
                        f"{ap.side} bubble at {ap.price:.0f} ({ap.volume:.0f} vol, delta {ap.delta:+.0f})"
                    )
                volume_bubble_desc = "; ".join(bubble_parts)
            except Exception:
                logger.debug("Failed to build volume bubble description for prompt")

        # Stacked imbalances from footprint
        imbalance_desc = ""

        # Aggressive prints cluster
        agg_levels = cluster_aggressive_prints(aggressive_prints) if aggressive_prints else []
        all_structural_levels = agg_levels + (prior_print_levels or [])

        # Strategy hint based on market state and session
        market_state_str = "Trending" if MarketStateCodec.is_imbalanced(ctx.market_state) else "Balanced"

        if MarketStateCodec.is_imbalanced(ctx.market_state) and session_info.allow_trend:
            strategy_hint = "Market is IMBALANCED (trending). Favor trend continuation setups."
        elif MarketStateCodec.is_imbalanced(ctx.market_state) and not session_info.allow_trend:
            strategy_hint = "Market is IMBALANCED but session phase favors mean reversion only."
        else:
            strategy_hint = "Market is BALANCED (range-bound). Favor mean reversion setups."

        # Session hints
        session_hints = {
            "NSE_PRIMARY": "[Primary Setup Window 09:30-11:30 — best window for AAA setups.]",
            "NSE_MIDDAY": "[Midday Consolidation 11:30-14:00 — mean reversion only.]",
            "NSE_POWER_HOUR": "[Power Hour 14:00-15:15 — second-best window for AAA setups.]",
        }
        hint = session_hints.get(session_info.session, "")
        if hint:
            strategy_hint += f" {hint}"

        return {
            "ltp": ctx.price,
            "delta": ctx.delta,
            "volume": ctx.volume,
            "vah": ctx.vah,
            "val": ctx.val,
            "poc": ctx.poc,
            "market_state": market_state_str,
            "aggression": f"Aggression Score: {ctx.aggression:.2f}",
            "profile_shape": profile_shape_str,
            "strategy_hint": strategy_hint,
            "volume_bubbles": volume_bubble_desc,
            "stacked_imbalances": imbalance_desc,
            "hvns": list(ctx.amt_result.hvns[:3]) if ctx.amt_result.hvns else [],
            "lvns": list(ctx.amt_result.lvns[:3]) if ctx.amt_result.lvns else [],
            "cvd_slope": ctx.cvd_slope,
            "cvd_divergence": ctx.amt_result.cvd_divergence,
            "vwap": ctx.vwap,
            "leg_poc": ctx.amt_result.leg_poc,
            "leg_lvns": list(ctx.amt_result.leg_lvns[:3]) if ctx.amt_result.leg_lvns else [],
            "opening_relation": ctx.opening_relation,
            "market_structure": ctx.amt_result.market_structure,
            "structure_confidence": ctx.amt_result.structure_confidence,
            "balance_ratio": ctx.amt_result.balance_ratio,
            "episodic_memory": episodic_memory,
            "gate_context": gate_context,
            "ib_high": ctx.amt_result.ib_high,
            "ib_low": ctx.amt_result.ib_low,
            "ib_complete": ctx.amt_result.ib_complete,
            "prior_poc": ctx.amt_result.prior_poc,
            "prior_vah": ctx.amt_result.prior_vah,
            "prior_val": ctx.amt_result.prior_val,
            "gap_type": ctx.amt_result.gap_type,
            "opening_bias": ctx.amt_result.opening_bias,
            "acceptance_above": ctx.amt_result.acceptance_above,
            "acceptance_below": ctx.amt_result.acceptance_below,
            "rejection_at_high": ctx.amt_result.rejection_at_high,
            "rejection_at_low": ctx.amt_result.rejection_at_low,
            "price_velocity": ctx.amt_result.price_velocity,
            "break_direction": ctx.amt_result.break_direction,
            "break_type": ctx.amt_result.break_type,
            "break_level": ctx.amt_result.break_level,
            "poc_signal": ctx.amt_result.poc_signal,
            "poc_vs_price": ctx.amt_result.poc_vs_price,
            "lvn_play": ctx.amt_result.lvn_play,
            "is_second_drive": is_second_drive,
        }

    @staticmethod
    def build_session_context_for_llm(session_info: SessionInfo) -> str:
        """Build session context string for LLM prompt."""
        parts = []
        if not session_info.allow_entry:
            parts.append(f"[WARNING] Current session phase: {session_info.session} — entries discouraged.")
        if session_info.allow_trend:
            parts.append("Trend setups allowed.")
        else:
            parts.append("Mean-reversion only.")
        return " ".join(parts)

    @staticmethod
    def build_episodic_memory(storage, symbol: str) -> str:
        """Build episodic memory string from recent trade history."""
        if not storage:
            return ""
        try:
            
            _today = datetime.now(IST).strftime("%Y-%m-%d")
            recent_trades = storage.get_recent_trades(limit=10)
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
            return (
                f"Session P&L: {pnl_sign}Rs{session_pnl:.0f} ({len(today_trades)} trades). "
                + ", ".join(parts)
                + "."
            )
        except Exception:
            return ""
