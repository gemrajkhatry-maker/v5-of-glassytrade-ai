"""
Rationale generator — rule-based deterministic rationale (no LLM).

Generates human-readable trade explanations from AMT data.
"""

from typing import Dict, Optional


class RationaleGenerator:
    """
    Rule-based rationale generation.

    Uses static methods for pure function behavior.
    """

    @staticmethod
    def generate(
        direction: str,
        market_state: str,
        zone: str,
        poc: Optional[float],
        vah: Optional[float],
        val: Optional[float],
        entry_level: float,
        aggression_score: float,
        aggression_confidence: str,
        drive_number: int,
        risk_reward: float,
        breakdown: Dict[str, float],
    ) -> str:
        """
        Generate deterministic rationale from AMT data.

        Args:
            direction: Trade direction (LONG/SHORT/FLAT)
            market_state: Current market state
            zone: Current zone
            poc: Point of Control
            vah: Value Area High
            val: Value Area Low
            entry_level: Entry price
            aggression_score: Aggression score
            aggression_confidence: Confidence level
            drive_number: Drive number (1/2/3+)
            risk_reward: Risk-reward ratio
            breakdown: Aggression breakdown

        Returns:
            Human-readable rationale string.
        """
        if direction == "FLAT":
            return RationaleGenerator._flat_rationale(market_state, zone)

        parts = []

        # Market context
        if market_state == "BALANCED":
            if zone == "NEAR_VAH":
                parts.append(f"BALANCED market near VAH ({vah:.2f})")
            elif zone == "NEAR_VAL":
                parts.append(f"BALANCED market near VAL ({val:.2f})")
            elif zone == "NEAR_POC":
                parts.append(f"BALANCED market at POC ({poc:.2f})")
            else:
                parts.append(f"BALANCED market (POC: {poc:.2f})")
        elif market_state == "IMBALANCED":
            parts.append(f"IMBALANCED market — trend mode confirmed")
        else:
            parts.append(f"{market_state} market")

        # Direction
        if direction == "LONG":
            parts.append(f"LONG setup at {entry_level:.2f}")
        else:
            parts.append(f"SHORT setup at {entry_level:.2f}")

        # Drive
        if drive_number == 2:
            parts.append("Second drive (D2) — first drive rejected")
        elif drive_number == 1:
            parts.append("First drive (D1) — initial touch")

        # Aggression
        parts.append(f"Aggression: {aggression_score:.1f}/4.5 ({aggression_confidence})")

        # Key signals
        signals = []
        if breakdown.get("footprint", 0) > 0:
            signals.append("footprint confirmed")
        if breakdown.get("cvd", 0) > 0:
            signals.append("CVD aligned")
        if breakdown.get("big_trade", 0) > 0:
            signals.append("institutional prints")
        if breakdown.get("absorption", 0) > 0:
            signals.append("absorption detected")
        if breakdown.get("confluence", 0) > 0:
            signals.append("level confluence")

        if signals:
            parts.append(f"Signals: {', '.join(signals)}")

        # R:R
        parts.append(f"R:R = {risk_reward:.1f}")

        return " | ".join(parts)

    @staticmethod
    def _flat_rationale(market_state: str, zone: str) -> str:
        """Generate rationale for FLAT (no trade)."""
        if market_state == "NO_TRADE":
            return f"NO_TRADE — price at POC dead zone ({zone})"
        elif market_state == "PROBING":
            return f"PROBING — unconfirmed break, waiting for displacement"
        elif market_state == "OUTSIDE":
            return f"OUTSIDE — session not active"
        else:
            return f"FLAT — no valid setup ({market_state})"