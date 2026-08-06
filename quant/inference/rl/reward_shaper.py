"""Reward Shaper — Valentini AMT reward shaping for RL training.

Implements the reward/penalty structure from Fabio Valentini's methodology:
  +1.0  hit target (POC or extension)
  +0.5  moved stop to break-even after first impulse
  bonus  efficiency velocity (faster = better)
  -10.0  exceeded 0.5% drawdown per trade
  -2.0   hesitation (held through failed auction)
  -3.0   fighting the flow (short while CVD positive + above VWAP)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TradeResult:
    """Outcome of a single trade for reward computation."""
    pnl: float                  # Profit/loss in currency units
    hit_target: bool            # Did we reach the TP level?
    moved_to_be: bool           # Was stop moved to break-even?
    risk_pct: float             # Max drawdown as % of equity
    bars_held: int              # Duration in bars
    max_bars: int               # Max allowed bars for velocity calc
    failed_auction_hold: bool   # Held while price re-entered failed state
    fighting_flow: bool         # Traded against dominant CVD + VWAP


class ValentiniRewardShaper:
    """Compute shaped rewards following Valentini's risk psychology."""

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
        """Compute the total shaped reward for a completed trade."""
        reward = 0.0

        # --- Positive rewards ---
        if result.hit_target:
            reward += self.target_reward

        if result.moved_to_be:
            reward += self.be_reward

        # Velocity bonus: faster exits get higher reward
        if result.max_bars > 0 and result.bars_held > 0:
            velocity = 1.0 - (result.bars_held / result.max_bars)
            reward += max(0.0, velocity * 0.3)  # up to +0.3

        # Small PnL-proportional component (normalised)
        if result.pnl > 0:
            reward += min(0.5, result.pnl * 0.01)
        elif result.pnl < 0:
            reward += max(-0.5, result.pnl * 0.01)

        # --- Negative penalties ---
        if result.risk_pct > self.max_risk_pct:
            reward += self.drawdown_penalty

        if result.failed_auction_hold:
            reward += self.hesitation_penalty

        if result.fighting_flow:
            reward += self.fighting_penalty

        return reward

    def step_reward(
        self,
        unrealised_pnl: float,
        equity: float,
        is_fighting_flow: bool = False,
    ) -> float:
        """Per-step reward while a position is open (small shaping signal)."""
        reward = 0.0

        # Mild PnL tracking
        if equity > 0:
            pnl_pct = unrealised_pnl / equity
            reward += pnl_pct * 0.1  # very small shaping

        # Per-step penalty for fighting flow
        if is_fighting_flow:
            reward -= 0.05

        return reward
