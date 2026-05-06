"""Signal Tracking Service — comprehensive tracking of signal generation decisions.

Tracks every decision point in the signal generation pipeline:
- When signals ARE generated (with full context)
- When signals are NOT generated (gate blocks, rejections, cooldowns)
- Why signals were blocked (gate name, reason, detail)

This enables post-trade analysis of:
- Which gates block most often
- Signal generation rate vs rejection rate
- Quality of generated signals (win rate by gate passage)
- Timing patterns (when signals cluster)

Usage:
    tracker = SignalTrackingService(storage)
    tracker.track_gate_block(symbol="CRUDEOIL", gate="CVD", reason="CVD_OPPOSING", ...)
    tracker.track_signal_generated(symbol="CRUDEOIL", signal=signal, ...)
    tracker.get_stats(symbol="CRUDEOIL")  # → {generated: 10, blocked: 45, ...}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.async_boundary import ensure_sync_adapter_result

logger = logging.getLogger(__name__)


@dataclass
class SignalDecision:
    """A single signal generation decision point."""

    decision_id: str
    symbol: str
    timestamp: str
    decision_type: str  # "GENERATED" | "BLOCKED" | "WAITING" | "COOLDOWN"

    # Gate information (if blocked)
    gate_name: str = ""
    gate_reason: str = ""
    gate_detail: str = ""

    # Signal information (if generated)
    direction: str = ""  # "LONG" | "SHORT" | "FLAT"
    confidence: str = ""  # "High" | "Medium" | "Low"
    aggression_score: float = 0.0
    drive_number: int = 0
    market_state: str = ""

    # Context
    price: float = 0.0
    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0
    cvd_slope: float = 0.0

    # LLM/Agent info
    agent_direction: str = ""
    agent_probability: float = 0.0
    agent_regime: str = ""
    llm_direction: str = ""
    llm_confidence: str = ""

    # Timing
    time_since_last_signal: float = 0.0
    candle_number: int = 0
    tick_trace_id: str = ""


class SignalTrackingService:
    """Comprehensive tracking of signal generation decisions.

    Single responsibility: Record and analyze signal generation patterns.
    """

    def __init__(self, storage=None) -> None:
        self._storage = storage
        self._decisions: dict[str, list[SignalDecision]] = {}  # symbol -> decisions
        self._stats: dict[str, dict] = {}  # symbol -> stats

    def track_signal_generated(
        self,
        symbol: str,
        direction: str,
        confidence: str,
        aggression_score: float,
        drive_number: int,
        market_state: str,
        price: float,
        poc: float,
        vah: float,
        val: float,
        cvd_slope: float,
        agent_direction: str = "",
        agent_probability: float = 0.0,
        agent_regime: str = "",
        llm_direction: str = "",
        llm_confidence: str = "",
        time_since_last: float = 0.0,
        candle_number: int = 0,
        tick_trace_id: str = "",
    ) -> SignalDecision:
        """Track a successfully generated signal."""
        decision = SignalDecision(
            decision_id=str(uuid4()),
            symbol=symbol,
            timestamp=datetime.now(timezone.utc).isoformat(),
            decision_type="GENERATED",
            direction=direction,
            confidence=confidence,
            aggression_score=aggression_score,
            drive_number=drive_number,
            market_state=market_state,
            price=price,
            poc=poc,
            vah=vah,
            val=val,
            cvd_slope=cvd_slope,
            agent_direction=agent_direction,
            agent_probability=agent_probability,
            agent_regime=agent_regime,
            llm_direction=llm_direction,
            llm_confidence=llm_confidence,
            time_since_last_signal=time_since_last,
            candle_number=candle_number,
            tick_trace_id=tick_trace_id,
        )
        self._record(symbol, decision)
        logger.info(
            "SIGNAL GENERATED: %s %s confidence=%s aggression=%.1f drive=%d state=%s",
            symbol,
            direction,
            confidence,
            aggression_score,
            drive_number,
            market_state,
        )
        return decision

    def track_gate_block(
        self,
        symbol: str,
        gate_name: str,
        gate_reason: str,
        gate_detail: str,
        market_state: str = "",
        price: float = 0.0,
        poc: float = 0.0,
        vah: float = 0.0,
        val: float = 0.0,
        cvd_slope: float = 0.0,
        aggression_score: float = 0.0,
        drive_number: int = 0,
        agent_direction: str = "",
        agent_probability: float = 0.0,
        tick_trace_id: str = "",
    ) -> SignalDecision:
        """Track a gate block (signal NOT generated)."""
        decision = SignalDecision(
            decision_id=str(uuid4()),
            symbol=symbol,
            timestamp=datetime.now(timezone.utc).isoformat(),
            decision_type="BLOCKED",
            gate_name=gate_name,
            gate_reason=gate_reason,
            gate_detail=gate_detail,
            market_state=market_state,
            price=price,
            poc=poc,
            vah=vah,
            val=val,
            cvd_slope=cvd_slope,
            aggression_score=aggression_score,
            drive_number=drive_number,
            agent_direction=agent_direction,
            agent_probability=agent_probability,
            tick_trace_id=tick_trace_id,
        )
        self._record(symbol, decision)
        logger.debug(
            "GATE BLOCK: %s — %s (%s): %s",
            symbol,
            gate_name,
            gate_reason,
            gate_detail,
        )
        return decision

    def track_waiting(
        self,
        symbol: str,
        reason: str,
        market_state: str = "",
        price: float = 0.0,
        poc: float = 0.0,
    ) -> SignalDecision:
        """Track a waiting state (not blocked, but not ready)."""
        decision = SignalDecision(
            decision_id=str(uuid4()),
            symbol=symbol,
            timestamp=datetime.now(timezone.utc).isoformat(),
            decision_type="WAITING",
            gate_reason=reason,
            market_state=market_state,
            price=price,
            poc=poc,
        )
        self._record(symbol, decision)
        return decision

    def track_cooldown(
        self,
        symbol: str,
        time_remaining: float,
    ) -> SignalDecision:
        """Track a cooldown state."""
        decision = SignalDecision(
            decision_id=str(uuid4()),
            symbol=symbol,
            timestamp=datetime.now(timezone.utc).isoformat(),
            decision_type="COOLDOWN",
            gate_reason=f"Cooldown active ({time_remaining:.0f}s remaining)",
        )
        self._record(symbol, decision)
        return decision

    def _record(self, symbol: str, decision: SignalDecision) -> None:
        """Record a decision and update stats.

        Deduplication: skip entirely if the last decision has the same
        decision_type + gate_name + gate_reason. The timestamp is updated
        so the UI shows the latest time, but no new entry is created and
        stats are not incremented.
        """
        if symbol not in self._decisions:
            self._decisions[symbol] = []

        last = self._decisions[symbol][-1] if self._decisions[symbol] else None
        if last and decision.decision_type == last.decision_type == "BLOCKED":
            if (
                decision.gate_name == last.gate_name
                and decision.gate_reason == last.gate_reason
            ):
                # Update previous entry timestamp so the UI shows the latest time
                last.timestamp = decision.timestamp
                return  # skip duplicate — do not count again

        self._decisions[symbol].append(decision)

        # Update stats
        if symbol not in self._stats:
            self._stats[symbol] = {
                "generated": 0,
                "blocked": 0,
                "waiting": 0,
                "cooldown": 0,
                "gate_blocks": {},
                "last_generated": None,
                "last_blocked": None,
            }

        stats = self._stats[symbol]
        if decision.decision_type == "GENERATED":
            stats["generated"] += 1
            stats["last_generated"] = decision.timestamp
        elif decision.decision_type == "BLOCKED":
            stats["blocked"] += 1
            stats["last_blocked"] = decision.timestamp
            gate = decision.gate_name
            if gate not in stats["gate_blocks"]:
                stats["gate_blocks"][gate] = 0
            stats["gate_blocks"][gate] += 1
        elif decision.decision_type == "WAITING":
            stats["waiting"] += 1
        elif decision.decision_type == "COOLDOWN":
            stats["cooldown"] += 1

        # Persist to storage
        if self._storage and hasattr(self._storage, "save_position_event"):
            try:
                ensure_sync_adapter_result(
                    "storage.save_position_event",
                    self._storage.save_position_event,
                    {
                        "position_id": decision.decision_id,
                        "symbol": symbol,
                        "event_type": f"SIGNAL_{decision.decision_type}",
                        "event_time": decision.timestamp,
                        "decision_id": decision.decision_id,
                        "gate_name": decision.gate_name,
                        "gate_reason": decision.gate_reason,
                        "direction": decision.direction,
                        "confidence": decision.confidence,
                    },
                )
            except Exception:
                logger.warning("Failed to persist signal tracking record", exc_info=True)

    def get_stats(self, symbol: str | None = None) -> dict:
        """Get signal generation statistics.

        Args:
            symbol: If provided, stats for this symbol. Otherwise, aggregate.

        Returns:
            Dict with generated, blocked, waiting, cooldown counts and gate breakdown.
        """
        if symbol:
            return self._stats.get(symbol, self._empty_stats())

        # Aggregate across all symbols
        total = self._empty_stats()
        for sym_stats in self._stats.values():
            total["generated"] += sym_stats["generated"]
            total["blocked"] += sym_stats["blocked"]
            total["waiting"] += sym_stats["waiting"]
            total["cooldown"] += sym_stats["cooldown"]
            for gate, count in sym_stats.get("gate_blocks", {}).items():
                if gate not in total["gate_blocks"]:
                    total["gate_blocks"][gate] = 0
                total["gate_blocks"][gate] += count

        total_decisions = (
            total["generated"] + total["blocked"] + total["waiting"] + total["cooldown"]
        )
        if total_decisions > 0:
            total["generation_rate"] = round(
                total["generated"] / total_decisions * 100, 1
            )
            total["block_rate"] = round(total["blocked"] / total_decisions * 100, 1)
        else:
            total["generation_rate"] = 0.0
            total["block_rate"] = 0.0

        return total

    def get_recent_decisions(self, symbol: str, limit: int = 1000) -> list[dict]:
        """Get recent decisions for a symbol (extended to full session history)."""
        decisions = self._decisions.get(symbol, [])
        recent = decisions[-limit:] if len(decisions) > limit else decisions
        return [
            {
                "decision_id": d.decision_id,
                "timestamp": d.timestamp,
                "type": d.decision_type,
                "gate_name": d.gate_name,
                "gate_reason": d.gate_reason,
                "direction": d.direction,
                "confidence": d.confidence,
                "aggression_score": d.aggression_score,
                "market_state": d.market_state,
                "agent_direction": d.agent_direction,
                "agent_probability": d.agent_probability,
            }
            for d in recent
        ]

    def get_gate_block_summary(self, symbol: str | None = None) -> dict:
        """Get summary of gate blocks by gate name."""
        if symbol:
            return self._stats.get(symbol, {}).get("gate_blocks", {})

        # Aggregate
        total_blocks: dict[str, int] = {}
        for sym_stats in self._stats.values():
            for gate, count in sym_stats.get("gate_blocks", {}).items():
                total_blocks[gate] = total_blocks.get(gate, 0) + count
        return total_blocks

    def clear(self, symbol: str | None = None) -> None:
        """Clear tracking data."""
        if symbol:
            self._decisions.pop(symbol, None)
            self._stats.pop(symbol, None)
        else:
            self._decisions.clear()
            self._stats.clear()

    @staticmethod
    def _empty_stats() -> dict:
        return {
            "generated": 0,
            "blocked": 0,
            "waiting": 0,
            "cooldown": 0,
            "gate_blocks": {},
            "generation_rate": 0.0,
            "block_rate": 0.0,
        }
