"""Reward shaping primitives for Valentini AMT RL environment."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TradeResult:
    """Finalized trade outcome used by reward shaping."""

    pnl: float
    hit_target: bool
    moved_to_be: bool
    risk_pct: float
    bars_held: int
    max_bars: int
    failed_auction_hold: bool
    fighting_flow: bool


class ValentiniRewardShaper:
    """Compute shaped rewards balancing execution and risk controls."""

    def __init__(
        self,
        target_reward: float = 1.0,
        be_reward: float = 0.5,
        drawdown_penalty: float = -10.0,
        hesitation_penalty: float = -2.0,
        fighting_penalty: float = -3.0,
        max_risk_pct: float = 0.5,
    ) -> None:
        self.target_reward = target_reward
        self.be_reward = be_reward
        self.drawdown_penalty = drawdown_penalty
        self.hesitation_penalty = hesitation_penalty
        self.fighting_penalty = fighting_penalty
        self.max_risk_pct = max_risk_pct

    def compute(self, result: TradeResult) -> float:
        """Compute reward for a closed trade."""
        reward = 0.0
        if result.hit_target:
            reward += self.target_reward
        if result.moved_to_be:
            reward += self.be_reward

        if result.max_bars > 0 and result.bars_held > 0:
            velocity = 1.0 - (result.bars_held / result.max_bars)
            reward += max(0.0, velocity * 0.3)

        if result.pnl > 0:
            reward += min(0.5, result.pnl * 0.01)
        elif result.pnl < 0:
            reward += max(-0.5, result.pnl * 0.01)

        if result.risk_pct > self.max_risk_pct:
            reward += self.drawdown_penalty
        if result.failed_auction_hold:
            reward += self.hesitation_penalty
        if result.fighting_flow:
            reward += self.fighting_penalty
        return reward

    def step_reward(self, unrealised_pnl: float, equity: float, is_fighting_flow: bool = False) -> float:
        """Per-step shaping while a trade is open."""
        reward = 0.0
        if equity > 0:
            reward += (unrealised_pnl / equity) * 0.1
        if is_fighting_flow:
            reward -= 0.05
        return reward

