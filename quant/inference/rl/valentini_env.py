"""Valentini AMT Gym Environment — RL environment for AMT trading.

Implements a Gymnasium environment with:
  - 28-feature observation vector (expanded from 12 per #28)
  - 7 discrete actions (HOLD, TREND_BUY, TREND_SELL, REVERT_BUY, REVERT_SELL, SCALE_IN, SCALE_OUT)
  - Action masking (balance → reversion only, imbalance → trend only)
  - 2.5σ aggression trigger required for entry
  - Dynamic stop-loss at aggression candle extremes
  - Valentini reward shaping
"""

from __future__ import annotations

from typing import Any

import numpy as np
import gymnasium as gym
from gymnasium import spaces

from quant.contracts.value_objects import OHLC
from quant.amt.models.observation import AMTObservation
# TODO(migration): switch to quant.amt.analyzer once Track A5 merges.
from app.domain.fabio_ai.services.amt_analyzer import (
    AMTAnalyzer,
    AMTConfig,
    compute_aggression_sigma,
)
from quant.inference.rl.reward_shaper import ValentiniRewardShaper, TradeResult


# ---------------------------------------------------------------------------
# Action Definitions
# ---------------------------------------------------------------------------

ACTION_HOLD = 0
ACTION_TREND_BUY = 1
ACTION_TREND_SELL = 2
ACTION_REVERT_BUY = 3
ACTION_REVERT_SELL = 4
ACTION_SCALE_IN = 5  # #28: New — pyramid add
ACTION_SCALE_OUT = 6  # #28: New — partial exit

ACTION_NAMES = {
    ACTION_HOLD: "HOLD",
    ACTION_TREND_BUY: "TREND_BUY",
    ACTION_TREND_SELL: "TREND_SELL",
    ACTION_REVERT_BUY: "REVERT_BUY",
    ACTION_REVERT_SELL: "REVERT_SELL",
    ACTION_SCALE_IN: "SCALE_IN",
    ACTION_SCALE_OUT: "SCALE_OUT",
}


# ---------------------------------------------------------------------------
# Position Tracker
# ---------------------------------------------------------------------------


class _Position:
    """Internal position state for the Gym environment."""

    def __init__(
        self,
        side: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        entry_bar: int,
        aggression_candle: OHLC,
    ) -> None:
        self.side = side  # "LONG" | "SHORT"
        self.entry_price = entry_price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.entry_bar = entry_bar
        self.aggression_candle = aggression_candle
        self.moved_to_be = False
        self.max_favorable = 0.0
        self.failed_auction_hold = False
        self.fighting_flow_count = 0
        self.size_fraction = 1.0  # #28: 1.0 = full, 0.4 = initial, 0.7 = after scale-in


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


class ValentiniAMTEnv(gym.Env):
    """Gymnasium environment for Valentini AMT RL training.

    Supports ``action_masks()`` for sb3-contrib MaskablePPO.
    """

    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        data: list[OHLC],
        initial_equity: float = 100_000.0,
        max_risk_pct: float = 0.5,
        tick_size: float = 0.01,
        max_bars_in_trade: int = 50,
        lookback: int = 200,
        render_mode: str | None = None,
    ) -> None:
        super().__init__()

        self._all_data = data
        self._initial_equity = initial_equity
        self._max_risk_pct = max_risk_pct / 100.0  # convert to decimal
        self._tick_size = tick_size
        self._max_bars = max_bars_in_trade
        self._lookback = lookback
        self.render_mode = render_mode

        # Spaces
        # #28: Expanded from 12 to 27 features
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(27,),
            dtype=np.float32,
        )
        # #28: Expanded from 5 to 7 actions
        self.action_space = spaces.Discrete(7)

        # Internal state
        self._analyzer = AMTAnalyzer()
        self._reward_shaper = ValentiniRewardShaper(max_risk_pct=max_risk_pct)
        self._step_idx = 0
        self._equity = initial_equity
        self._position: _Position | None = None
        self._last_obs: AMTObservation | None = None
        self._episode_reward = 0.0
        self._trade_log: list[dict] = []
        self._prior_vah = 0.0
        self._prior_val = 0.0

    # -------------------------------------------------------------------
    # Gymnasium API
    # -------------------------------------------------------------------

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict | None = None,
    ) -> tuple[np.ndarray, dict]:
        super().reset(seed=seed)
        self._step_idx = self._lookback  # start after enough lookback
        self._equity = self._initial_equity
        self._position = None
        self._last_obs = None
        self._episode_reward = 0.0
        self._trade_log = []
        self._prior_vah = 0.0
        self._prior_val = 0.0
        self._analyzer = AMTAnalyzer()  # fresh trackers
        obs = self._compute_obs()
        return obs, self._info()

    def step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict]:
        reward = 0.0
        terminated = False
        truncated = False

        current = self._all_data[self._step_idx]
        mask = self.action_masks()

        # Enforce action masking (invalid action → HOLD + small penalty)
        if not mask[action]:
            action = ACTION_HOLD
            reward -= 0.01  # tiny penalty for proposing invalid action

        # --- Position management ---
        if self._position is not None:
            pos = self._position
            pnl = pos.pnl_at(current.close)
            bars_held = self._step_idx - pos.entry_bar

            # Check stop loss
            if pos.side == "LONG" and current.low <= pos.stop_loss:
                reward += self._close_position(
                    pos.stop_loss, bars_held, hit_target=False
                )
            elif pos.side == "SHORT" and current.high >= pos.stop_loss:
                reward += self._close_position(
                    pos.stop_loss, bars_held, hit_target=False
                )
            # Check take profit
            elif pos.side == "LONG" and current.high >= pos.take_profit:
                reward += self._close_position(
                    pos.take_profit, bars_held, hit_target=True
                )
            elif pos.side == "SHORT" and current.low <= pos.take_profit:
                reward += self._close_position(
                    pos.take_profit, bars_held, hit_target=True
                )
            else:
                # Update max favorable excursion
                if pos.side == "LONG":
                    pos.max_favorable = max(
                        pos.max_favorable, current.high - pos.entry_price
                    )
                else:
                    pos.max_favorable = max(
                        pos.max_favorable, pos.entry_price - current.low
                    )

                # Move to break-even after first impulse (> 1R favorable)
                risk_per_unit = abs(pos.entry_price - pos.stop_loss)
                if not pos.moved_to_be and pos.max_favorable >= risk_per_unit:
                    pos.stop_loss = pos.entry_price
                    pos.moved_to_be = True

                # Check hesitation: did price re-enter a failed auction state?
                if self._last_obs and not self._last_obs.is_in_balance:
                    obs_now = self._compute_obs_raw()
                    if obs_now.is_in_balance:
                        pos.failed_auction_hold = True

                # Check fighting flow
                is_fighting = self._is_fighting_flow(pos)
                if is_fighting:
                    pos.fighting_flow_count += 1

                # Per-step shaping
                reward += self._reward_shaper.step_reward(
                    pnl,
                    self._equity,
                    is_fighting,
                )

                # Max bars → force close
                if bars_held >= self._max_bars:
                    reward += self._close_position(
                        current.close, bars_held, hit_target=False
                    )

        # --- Entry logic (only if no position) ---
        if self._position is None and action != ACTION_HOLD:
            obs_raw = self._last_obs or self._compute_obs_raw()

            # Require 2.5σ aggression for entry
            if obs_raw.aggression_sigma >= 2.5:
                self._open_position(action, current, obs_raw)

        # Advance
        self._step_idx += 1
        self._episode_reward += reward

        # Episode end
        if self._step_idx >= len(self._all_data) - 1:
            truncated = True
            # Force close any open position
            if self._position is not None:
                last = self._all_data[self._step_idx - 1]
                bars = self._step_idx - self._position.entry_bar
                reward += self._close_position(last.close, bars, hit_target=False)

        obs = self._compute_obs()
        return obs, reward, terminated, truncated, self._info()

    def action_masks(self) -> np.ndarray:
        """Return boolean mask of valid actions for current state."""
        # #28: 7 actions instead of 5
        mask = np.ones(7, dtype=bool)

        if self._position is not None:
            # While in position, only HOLD, SCALE_IN, SCALE_OUT are valid
            mask[ACTION_TREND_BUY] = False
            mask[ACTION_TREND_SELL] = False
            mask[ACTION_REVERT_BUY] = False
            mask[ACTION_REVERT_SELL] = False
            # #28: SCALE_IN masked unless confirmation conditions met
            if self._position.size_fraction >= 0.7:
                mask[ACTION_SCALE_IN] = False
            # #28: SCALE_OUT masked unless adverse conditions detected
            if self._position.fighting_flow_count < 2:
                mask[ACTION_SCALE_OUT] = False
            return mask

        obs = self._last_obs
        if obs is None:
            return mask

        # Entry actions masked by market state
        if obs.is_in_balance:
            # In balance → mask out trend actions
            mask[ACTION_TREND_BUY] = False
            mask[ACTION_TREND_SELL] = False
        else:
            # Imbalanced → mask out reversion actions
            mask[ACTION_REVERT_BUY] = False
            mask[ACTION_REVERT_SELL] = False

        # SCALE_IN/SCALE_OUT only valid when in position
        mask[ACTION_SCALE_IN] = False
        mask[ACTION_SCALE_OUT] = False

        return mask

    # -------------------------------------------------------------------
    # Internals
    # -------------------------------------------------------------------

    def _compute_obs(self) -> np.ndarray:
        """Build observation vector and cache raw AMTObservation."""
        obs_raw = self._compute_obs_raw()
        self._last_obs = obs_raw
        return self._obs_to_array(obs_raw)

    def _compute_obs_raw(self) -> AMTObservation:
        """Run AMT analyzer to get raw observation."""
        start = max(0, self._step_idx - self._lookback)
        window = self._all_data[start : self._step_idx + 1]
        return self._analyzer.compute_observation(
            window,
            prior_vah=self._prior_vah,
            prior_val=self._prior_val,
        )

    @staticmethod
    def _obs_to_array(obs: AMTObservation) -> np.ndarray:
        """Convert AMTObservation to a float32 numpy array.

        #28: Expanded from 12 to 28 features.
        """
        # Encode categoricals as floats
        shape_map = {"D": 0.0, "P": 1.0, "b": -1.0}
        poc_map = {"RISING": 1.0, "FALLING": -1.0, "STABLE": 0.0}
        session_map = {"ASIA": 0.0, "LONDON": 1.0, "NEW_YORK": 2.0, "OVERLAP": 3.0}
        opening_map = {"IN_BALANCE": 0.0, "OUT_ABOVE": 1.0, "OUT_BELOW": -1.0}
        drive_map = {"FRESH": 0.0, "MATURING": 0.33, "DECAYING": 0.66, "EXHAUSTED": 1.0}
        absorption_map = {"SELL_ABSORBED": 1.0, "BUY_ABSORBED": -1.0}
        tf_align_map = {
            "ALIGNED_LONG": 1.0,
            "ALIGNED_SHORT": -1.0,
            "CONFLICTED": 0.0,
            "NEUTRAL": 0.0,
        }

        return np.array(
            [
                # Group A: Price Microstructure (12)
                obs.dist_to_poc,
                1.0 if obs.is_in_balance else 0.0,
                obs.delta_divergence,
                obs.nearest_lvn,
                obs.cvd_slope,
                shape_map.get(obs.profile_shape, 0.0),
                poc_map.get(obs.poc_migration, 0.0),
                session_map.get(obs.session, 0.0),
                opening_map.get(obs.opening_relation, 0.0),
                obs.aggression_sigma,
                obs.obi,
                obs.norm_delta,
                # Group C: Order Book (3)
                obs.bid_imbalance,
                obs.depth_imbalance,
                obs.spread_pct,
                # Group D: Options-Specific (4)
                obs.pcr_ratio,
                obs.oi_change,
                obs.moneyness,
                obs.iv_rank,
                # Group E: Temporal (3)
                obs.session_minute,
                obs.minutes_to_expiry,
                obs.day_of_week,
                # Group F: AMT Context (5)
                drive_map.get(obs.drive_state, 0.0),
                absorption_map.get(obs.absorption_side, 0.0),
                obs.gap_fill_probability,
                tf_align_map.get(obs.tf_alignment, 0.0),
                # Opening type (1)
                1.0 if obs.opening_type else 0.0,
            ],
            dtype=np.float32,
        )

    def _open_position(
        self,
        action: int,
        candle: OHLC,
        obs: AMTObservation,
    ) -> None:
        """Open a new position based on action."""
        if action in (ACTION_TREND_BUY, ACTION_REVERT_BUY):
            side = "LONG"
            # Dynamic SL: 2 ticks below the aggression candle's low
            sl = candle.low - 2 * self._tick_size
            # TP: for trend → structural extension (5%), for reversion → POC
            if action == ACTION_TREND_BUY:
                tp = candle.close * 1.05
            else:
                # Mean reversion target = nearest_lvn or current close + small move
                tp_lvn = obs.nearest_lvn if obs.nearest_lvn > 0 else candle.close * 1.02
                tp = tp_lvn if tp_lvn > candle.close else candle.close * 1.01
        else:
            side = "SHORT"
            sl = candle.high + 2 * self._tick_size
            if action == ACTION_TREND_SELL:
                tp = candle.close * 0.95
            else:
                tp_lvn = obs.nearest_lvn if obs.nearest_lvn > 0 else candle.close * 0.98
                tp = tp_lvn if tp_lvn < candle.close else candle.close * 0.99

        # Check max risk constraint
        risk_per_unit = abs(candle.close - sl)
        risk_pct = (risk_per_unit / self._equity) * 100 if self._equity > 0 else 100.0
        if risk_pct > self._max_risk_pct * 100:
            return  # Skip — risk too high

        self._position = _Position(
            side=side,
            entry_price=candle.close,
            stop_loss=sl,
            take_profit=tp,
            entry_bar=self._step_idx,
            aggression_candle=candle,
        )

    def _close_position(
        self,
        exit_price: float,
        bars_held: int,
        hit_target: bool,
    ) -> float:
        """Close the current position and return shaped reward."""
        pos = self._position
        if pos is None:
            return 0.0

        pnl = pos.pnl_at(exit_price)
        risk_pct = abs(pnl) / self._equity * 100 if self._equity > 0 else 0.0
        self._equity += pnl

        result = TradeResult(
            pnl=pnl,
            hit_target=hit_target,
            moved_to_be=pos.moved_to_be,
            risk_pct=risk_pct,
            bars_held=bars_held,
            max_bars=self._max_bars,
            failed_auction_hold=pos.failed_auction_hold,
            fighting_flow=(pos.fighting_flow_count > 3),
        )

        reward = self._reward_shaper.compute(result)

        self._trade_log.append(
            {
                "side": pos.side,
                "entry": pos.entry_price,
                "exit": exit_price,
                "pnl": pnl,
                "bars": bars_held,
                "hit_target": hit_target,
                "reward": reward,
            }
        )

        self._position = None
        return reward

    def _is_fighting_flow(self, pos: _Position) -> bool:
        """Check if the position is fighting the dominant flow."""
        if self._last_obs is None:
            return False
        obs = self._last_obs
        # Long while CVD falling and delta negative
        if pos.side == "LONG" and obs.cvd_slope < 0 and obs.norm_delta < 0:
            return True
        # Short while CVD rising and delta positive
        if pos.side == "SHORT" and obs.cvd_slope > 0 and obs.norm_delta > 0:
            return True
        return False

    def _info(self) -> dict[str, Any]:
        return {
            "equity": self._equity,
            "episode_reward": self._episode_reward,
            "trades": len(self._trade_log),
            "position": self._position.side if self._position else None,
            "step": self._step_idx,
        }
