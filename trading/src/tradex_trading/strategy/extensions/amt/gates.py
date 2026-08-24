"""AMT decision gates; no broker or execution dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from tradex_trading.strategy.extensions.amt.model import AMTDecision, AMTPhase, AMTSnapshot


@dataclass(frozen=True, slots=True)
class AMTDecisionContext:
    snapshot: AMTSnapshot
    position_open: bool = False
    position_direction: str | None = None
    cooldown_bars: int = 0
    warmup_complete: bool = True
    agent_direction: str | None = None
    agent_probability: Decimal = Decimal("1")
    stop_cushion: Decimal = Decimal("0")
    pyramid_enabled: bool = True
    pyramid_threshold: Decimal = Decimal("3.0")


def _structural_plan(
    snapshot: AMTSnapshot,
    direction: str,
    cushion: Decimal = Decimal("0"),
) -> tuple[Decimal, Decimal, Decimal, Decimal] | None:
    entry = snapshot.close
    if direction == "LONG":
        levels = [
            level
            for level in (snapshot.val, snapshot.lower_1, snapshot.lower_2)
            if level is not None
        ]
        candidates = [level for level in levels if level < entry]
        stop = max(candidates) if candidates else None
        if stop is None:
            return None
        stop -= cushion  # room beyond the structural support (avoid wick-outs)
        risk = entry - stop
        target = entry + risk * Decimal("2")
    else:
        levels = [
            level
            for level in (snapshot.vah, snapshot.upper_1, snapshot.upper_2)
            if level is not None
        ]
        candidates = [level for level in levels if level > entry]
        stop = min(candidates) if candidates else None
        if stop is None:
            return None
        stop += cushion
        risk = stop - entry
        target = entry - risk * Decimal("2")
    if risk <= 0:
        return None
    return entry, stop, target, (target - entry).copy_abs() / risk


def evaluate(context: AMTDecisionContext) -> AMTDecision:
    snapshot = context.snapshot
    failed: list[str] = []
    if not context.warmup_complete:
        failed.append("warmup")
    if context.cooldown_bars > 0:
        failed.append("cooldown")

    direction = snapshot.direction
    pyramid = False
    if context.position_open:
        same_direction = bool(
            direction and direction == context.position_direction
        )
        strong = snapshot.aggression_score >= context.pyramid_threshold
        if context.pyramid_enabled and same_direction and strong:
            pyramid = True
        else:
            failed.append("position_open")

    setup = "TRIPLE_A" if snapshot.phase is AMTPhase.AGGRESSION and direction else ""
    if not setup and snapshot.location == "BELOW_VA" and snapshot.delta > 0:
        setup, direction = "VA_FADE", "LONG"
    elif not setup and snapshot.location == "ABOVE_VA" and snapshot.delta < 0:
        setup, direction = "VA_FADE", "SHORT"
    if pyramid:
        setup = "PYRAMID"
    if not setup:
        failed.append("no_edge")
    if context.agent_direction and direction and context.agent_direction != direction:
        failed.append("direction_conflict")
    if context.agent_probability < Decimal("0.5"):
        failed.append("probability")

    plan = _structural_plan(snapshot, direction, context.stop_cushion) if direction else None
    if plan is None:
        failed.append("risk_reward")
    elif plan[3] < Decimal("1.5"):
        failed.append("risk_reward")

    if failed:
        return AMTDecision(
            False,
            setup or "NO_EDGE",
            direction,
            None,
            None,
            None,
            Decimal("0"),
            "gate rejected",
            tuple(failed),
        )
    entry, stop, target, rr = plan
    return AMTDecision(
        True, setup, direction, entry, stop, target, rr, "approved",
        cushion=context.stop_cushion,
        pyramid=pyramid,
    )
