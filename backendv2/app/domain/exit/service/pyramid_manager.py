"""Pyramid manager — structured scale-in for winning positions."""

from __future__ import annotations

from app.domain.exit.model.exit_models import PyramidSignal

PYRAMID_AGGRESSION_SCORE = 3.0


class PyramidManager:
    """Evaluate whether to pyramid add into a winner."""

    MAX_ADDS = 2

    def check_pyramid(
        self,
        entry_price: float,
        current_price: float,
        is_long: bool,
        aggression_score: float,
        add_count: int,
        entry_lvns: list[float],
        current_lvn: float,
        current_sl: float,
    ) -> PyramidSignal | None:
        if add_count >= self.MAX_ADDS:
            return None

        if is_long and current_price <= entry_price:
            return None
        if (not is_long) and current_price >= entry_price:
            return None

        if aggression_score < PYRAMID_AGGRESSION_SCORE:
            return None

        if current_lvn > 0:
            for prev_lvn in entry_lvns:
                if abs(current_lvn - prev_lvn) < abs(current_lvn) * 0.003:
                    return None

        size_multiplier = 1.0 if add_count == 0 else 0.5
        unified_sl = max(current_sl, current_price * 0.995) if is_long else min(current_sl, current_price * 1.005)
        return PyramidSignal(
            size_multiplier=size_multiplier,
            level=current_price,
            unified_sl=unified_sl,
        )

    @staticmethod
    def serialize_position_state(
        position_id: str, add_count: int, entry_lvns: list[float]
    ) -> dict:
        """Serialize pyramid state for persistence."""
        return {
            "position_id": position_id,
            "add_count": add_count,
            "entry_lvns": list(entry_lvns),
        }

    @staticmethod
    def deserialize_position_state(data: dict) -> tuple[str, int, list[float]]:
        """Deserialize pyramid state from persisted data."""
        return (
            data["position_id"],
            data.get("add_count", 0),
            list(data.get("entry_lvns", [])),
        )
