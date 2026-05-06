"""Gymnasium environment used for RL training of AMT policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from app.domain.ai.rl.reward_shaper import TradeResult, ValentiniRewardShaper
from app.domain.amt.service.amt_analyzer import AMTAnalyzer
from app.domain.trading.model.value_objects import OHLC


def _to_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


ACTION_HOLD = 0
ACTION_TREND_BUY = 1
ACTION_TREND_SELL = 2
ACTION_REVERT_BUY = 3
ACTION_REVERT_SELL = 4
ACTION_SCALE_IN = 5
ACTION_SCALE_OUT = 6

OBSERVATION_DIM = 27
ACTION_DIM = 7

ACTION_NAMES = {
    ACTION_HOLD: "HOLD",
    ACTION_TREND_BUY: "TREND_BUY",
    ACTION_TREND_SELL: "TREND_SELL",
    ACTION_REVERT_BUY: "REVERT_BUY",
    ACTION_REVERT_SELL: "REVERT_SELL",
    ACTION_SCALE_IN: "SCALE_IN",
    ACTION_SCALE_OUT: "SCALE_OUT",
}


@dataclass(frozen=True)
class AMTObservation:
    dist_to_poc: float
    is_in_balance: bool
    delta_divergence: float
    nearest_lvn: float
    cvd_slope: float
    profile_shape: str
    poc_migration: str
    session: str
    opening_relation: str
    aggression_sigma: float
    obi: float
    norm_delta: float
    bid_imbalance: float
    depth_imbalance: float
    spread_pct: float
    pcr_ratio: float
    oi_change: float
    moneyness: float
    iv_rank: float
    session_minute: float
    minutes_to_expiry: float
    day_of_week: float
    drive_state: str
    absorption_side: str
    gap_fill_probability: float
    tf_alignment: str
    opening_type: str


class _Position:
    def __init__(
        self,
        side: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        entry_bar: int,
        aggression_candle: AMTObservation,
    ) -> None:
        self.side = side
        self.entry_price = entry_price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.entry_bar = entry_bar
        self.aggression_candle = aggression_candle
        self.moved_to_be = False
        self.max_favorable = 0.0
        self.failed_auction_hold = False
        self.fighting_flow_count = 0
        self.size_fraction = 1.0

    def pnl_at(self, price: float) -> float:
        if self.side == "LONG":
            return price - self.entry_price
        return self.entry_price - price


class ValentiniAMTEnv(gym.Env):
    """RL environment for Valentini AMT policy experiments."""

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
        self._max_risk_pct = max_risk_pct / 100.0
        self._tick_size = tick_size
        self._max_bars = max_bars_in_trade
        self._lookback = lookback
        self.render_mode = render_mode

        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(OBSERVATION_DIM,), dtype=np.float64)
        self.action_space = spaces.Discrete(ACTION_DIM)

        self._analyzer = AMTAnalyzer()
        self._reward_shaper = ValentiniRewardShaper(max_risk_pct=max_risk_pct)
        self._step_idx = 0
        self._equity = initial_equity
        self._position: _Position | None = None
        self._last_obs: AMTObservation | None = None
        self._episode_reward = 0.0
        self._trade_log: list[dict[str, float]] = []
        self._prior_poc = 0.0
        self._prior_vah = 0.0
        self._prior_val = 0.0

    def reset(self, *, seed: int | None = None, options: dict | None = None) -> tuple[np.ndarray, dict]:
        super().reset(seed=seed)
        self._step_idx = self._lookback
        self._equity = self._initial_equity
        self._position = None
        self._last_obs = None
        self._episode_reward = 0.0
        self._trade_log = []
        self._prior_poc = 0.0
        self._prior_vah = 0.0
        self._prior_val = 0.0
        self._analyzer = AMTAnalyzer()
        return self._compute_obs(), self._info()

    def step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict]:
        reward = 0.0
        terminated = False
        truncated = False

        if self._step_idx >= len(self._all_data) - 1:
            truncated = True
            return self._compute_obs(), 0.0, terminated, truncated, self._info()

        current = self._all_data[self._step_idx]
        mask = self.action_masks()
        if not mask[action]:
            action = ACTION_HOLD
            reward -= 0.01

        if self._position is not None:
            pos = self._position
            pnl = pos.pnl_at(_to_float(current.close))
            bars_held = self._step_idx - pos.entry_bar

            if pos.side == "LONG" and _to_float(current.low) <= pos.stop_loss:
                reward += self._close_position(pos.stop_loss, bars_held, hit_target=False)
            elif pos.side == "SHORT" and _to_float(current.high) >= pos.stop_loss:
                reward += self._close_position(pos.stop_loss, bars_held, hit_target=False)
            elif pos.side == "LONG" and _to_float(current.high) >= pos.take_profit:
                reward += self._close_position(pos.take_profit, bars_held, hit_target=True)
            elif pos.side == "SHORT" and _to_float(current.low) <= pos.take_profit:
                reward += self._close_position(pos.take_profit, bars_held, hit_target=True)
            else:
                if pos.side == "LONG":
                    pos.max_favorable = max(pos.max_favorable, _to_float(current.high) - pos.entry_price)
                else:
                    pos.max_favorable = max(pos.max_favorable, pos.entry_price - _to_float(current.low))

                risk_per_unit = abs(pos.entry_price - pos.stop_loss)
                if not pos.moved_to_be and pos.max_favorable >= risk_per_unit:
                    pos.stop_loss = pos.entry_price
                    pos.moved_to_be = True

                if self._last_obs is not None and pos is not None:
                    obs_now = self._compute_obs_raw()
                    if not obs_now.is_in_balance and self._last_obs.is_in_balance:
                        pos.failed_auction_hold = True

                if self._is_fighting_flow(pos):
                    pos.fighting_flow_count += 1

                reward += self._reward_shaper.step_reward(
                    pnl,
                    self._equity,
                    is_fighting_flow=self._is_fighting_flow(pos),
                )

                if bars_held >= self._max_bars:
                    reward += self._close_position(_to_float(current.close), bars_held, hit_target=False)

        if self._position is None and action != ACTION_HOLD:
            obs_raw = self._last_obs or self._compute_obs_raw()
            if obs_raw.aggression_sigma >= 2.5:
                self._open_position(action, current, obs_raw)

        self._step_idx += 1
        self._episode_reward += reward

        if self._step_idx >= len(self._all_data) - 1 and self._position is not None:
            last = self._all_data[self._step_idx - 1]
            bars = self._step_idx - self._position.entry_bar
            reward += self._close_position(_to_float(last.close), bars, hit_target=False)
            truncated = True

        obs = self._compute_obs()
        return obs, reward, terminated, truncated, self._info()

    def action_masks(self) -> np.ndarray:
        mask = np.ones(ACTION_DIM, dtype=bool)
        if self._position is not None:
            mask[ACTION_TREND_BUY] = False
            mask[ACTION_TREND_SELL] = False
            mask[ACTION_REVERT_BUY] = False
            mask[ACTION_REVERT_SELL] = False
            if self._position.size_fraction >= 0.7:
                mask[ACTION_SCALE_IN] = False
            if self._position.fighting_flow_count < 2:
                mask[ACTION_SCALE_OUT] = False
            return mask

        if self._last_obs is None:
            return mask
        if self._last_obs.is_in_balance:
            mask[ACTION_TREND_BUY] = False
            mask[ACTION_TREND_SELL] = False
        else:
            mask[ACTION_REVERT_BUY] = False
            mask[ACTION_REVERT_SELL] = False
        mask[ACTION_SCALE_IN] = False
        mask[ACTION_SCALE_OUT] = False
        return mask

    def _compute_obs(self) -> np.ndarray:
        obs_raw = self._compute_obs_raw()
        self._last_obs = obs_raw
        return self._obs_to_array(obs_raw)

    def _compute_obs_raw(self) -> AMTObservation:
        start = max(0, self._step_idx - self._lookback)
        window = self._all_data[start : self._step_idx + 1]
        rows = [self._to_bar_dict(c) for c in window]
        if not rows:
            return self._default_obs()
        amt = self._analyzer.analyze(rows)

        close = _to_float(rows[-1]["close"])
        poc = _to_float(amt.poc)
        if poc <= 0:
            poc = close
            if rows:
                poc = _to_float(rows[-1]["close"])

        prior_poc = self._prior_poc
        poc_migration = "STABLE"
        if prior_poc > 0:
            delta = poc - prior_poc
            if delta > 0:
                poc_migration = "RISING"
            elif delta < 0:
                poc_migration = "FALLING"
        self._prior_poc = poc
        if _to_float(amt.value_area_high) > 0:
            self._prior_vah = _to_float(amt.value_area_high)
        if _to_float(amt.value_area_low) > 0:
            self._prior_val = _to_float(amt.value_area_low)

        lvn = self._nearest_value(_to_float(rows[-1]["close"]), amt.lvns)
        cvd_slope = _to_float(amt.cvd_slope)
        norm_delta = self._norm_delta(rows[-1])
        opening_relation = str(getattr(amt, "opening_type", "")) or str(getattr(amt, "opening_bias", "")) or "NEUTRAL"
        opening_relation = opening_relation.upper().replace(" ", "_")
        if opening_relation == "":
            opening_relation = "NEUTRAL"

        return AMTObservation(
            dist_to_poc=_to_float(rows[-1]["close"]) - poc,
            is_in_balance="BALANC" in str(amt.market_state).upper(),
            delta_divergence=norm_delta - cvd_slope,
            nearest_lvn=lvn,
            cvd_slope=cvd_slope,
            profile_shape=str(getattr(amt, "profile_shape", "D") or "D").upper()[:1],
            poc_migration=poc_migration,
            session=str(getattr(amt, "day_type", "UNKNOWN")),
            opening_relation=opening_relation,
            aggression_sigma=self._aggression_sigma(rows),
            obi=_to_float(amt.aggression),
            norm_delta=norm_delta,
            bid_imbalance=0.0,
            depth_imbalance=0.0,
            spread_pct=0.0,
            pcr_ratio=0.0,
            oi_change=0.0,
            moneyness=0.0,
            iv_rank=0.0,
            session_minute=self._session_minute(rows[-1]["time"]),
            minutes_to_expiry=0.0,
            day_of_week=self._day_of_week(rows[-1]["time"]),
            drive_state="FRESH" if _to_float(amt.drive_number) < 1 else "MATURING" if _to_float(amt.drive_number) < 2 else "DECAYING",
            absorption_side=str(getattr(amt, "absorption_side", "")),
            gap_fill_probability=min(1.0, abs(_to_float(amt.aggression))),
            tf_alignment=str(getattr(amt, "mtf_alignment", "NEUTRAL")),
            opening_type=str(getattr(amt, "opening_type", "")),
        )

    @staticmethod
    def _obs_to_array(obs: AMTObservation) -> np.ndarray:
        shape_map = {"D": 0.0, "P": 1.0, "B": -1.0}
        poc_map = {"RISING": 1.0, "FALLING": -1.0, "STABLE": 0.0}
        session_map = {
            "ASIA": 0.0,
            "LONDON": 1.0,
            "NEW_YORK": 2.0,
            "OVERLAP": 3.0,
            "UNKNOWN": 0.0,
        }
        opening_map = {"IN_BALANCE": 0.0, "OUT_ABOVE": 1.0, "OUT_BELOW": -1.0, "NEUTRAL": 0.0}
        drive_map = {"FRESH": 0.0, "MATURING": 0.33, "DECAYING": 0.66, "EXHAUSTED": 1.0}
        tf_align_map = {
            "ALIGNED_LONG": 1.0,
            "ALIGNED_SHORT": -1.0,
            "CONFLICTED": 0.0,
            "NEUTRAL": 0.0,
        }
        absorption_map = {"SELL_ABSORBED": 1.0, "BUY_ABSORBED": -1.0}

        return np.array(
            [
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
                obs.bid_imbalance,
                obs.depth_imbalance,
                obs.spread_pct,
                obs.pcr_ratio,
                obs.oi_change,
                obs.moneyness,
                obs.iv_rank,
                obs.session_minute,
                obs.minutes_to_expiry,
                obs.day_of_week,
                drive_map.get(obs.drive_state, 0.0),
                absorption_map.get(obs.absorption_side, 0.0),
                obs.gap_fill_probability,
                tf_align_map.get(obs.tf_alignment, 0.0),
                1.0 if obs.opening_type else 0.0,
            ],
            dtype=np.float64,
        )

    def _open_position(self, action: int, candle: OHLC, obs: AMTObservation) -> None:
        if action in (ACTION_TREND_BUY, ACTION_REVERT_BUY):
            side = "LONG"
            sl = _to_float(candle.low) - 2 * self._tick_size
            tp = _to_float(candle.close) * 1.05 if action == ACTION_TREND_BUY else max(
                obs.nearest_lvn if obs.nearest_lvn > 0 else _to_float(candle.close) * 1.02,
                _to_float(candle.close) * 1.01,
            )
        else:
            side = "SHORT"
            sl = _to_float(candle.high) + 2 * self._tick_size
            tp = _to_float(candle.close) * 0.95 if action == ACTION_TREND_SELL else min(
                obs.nearest_lvn if obs.nearest_lvn > 0 else _to_float(candle.close) * 0.98,
                _to_float(candle.close) * 0.99,
            )

        risk_per_unit = abs(_to_float(candle.close) - sl)
        risk_pct = (risk_per_unit / self._equity) * 100 if self._equity > 0 else 100.0
        if risk_pct > self._max_risk_pct * 100:
            return

        self._position = _Position(
            side=side,
            entry_price=_to_float(candle.close),
            stop_loss=sl,
            take_profit=tp,
            entry_bar=self._step_idx,
            aggression_candle=obs,
        )

    def _close_position(self, exit_price: float, bars_held: int, hit_target: bool) -> float:
        if self._position is None:
            return 0.0
        pos = self._position
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
            },
        )
        self._position = None
        return reward

    def _is_fighting_flow(self, pos: _Position) -> bool:
        if self._last_obs is None:
            return False
        obs = self._last_obs
        if pos.side == "LONG" and obs.cvd_slope < 0 and obs.norm_delta < 0:
            return True
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

    @staticmethod
    def _to_bar_dict(candle: OHLC) -> dict[str, float]:
        return {
            "time": str(candle.time),
            "open": _to_float(candle.open),
            "high": _to_float(candle.high),
            "low": _to_float(candle.low),
            "close": _to_float(candle.close),
            "volume": _to_float(candle.volume),
            "vwap": _to_float(getattr(candle, "vwap", 0.0)),
            "taker_buy_volume": _to_float(getattr(candle, "taker_buy_volume", 0.0)),
            "delta": _to_float(getattr(candle, "delta", 0.0)),
        }

    @staticmethod
    def _default_obs() -> AMTObservation:
        return AMTObservation(
            dist_to_poc=0.0,
            is_in_balance=True,
            delta_divergence=0.0,
            nearest_lvn=0.0,
            cvd_slope=0.0,
            profile_shape="D",
            poc_migration="STABLE",
            session="UNKNOWN",
            opening_relation="NEUTRAL",
            aggression_sigma=0.0,
            obi=0.0,
            norm_delta=0.0,
            bid_imbalance=0.0,
            depth_imbalance=0.0,
            spread_pct=0.0,
            pcr_ratio=0.0,
            oi_change=0.0,
            moneyness=0.0,
            iv_rank=0.0,
            session_minute=0.0,
            minutes_to_expiry=0.0,
            day_of_week=0.0,
            drive_state="FRESH",
            absorption_side="",
            gap_fill_probability=0.0,
            tf_alignment="NEUTRAL",
            opening_type="",
        )

    @staticmethod
    def _nearest_value(price: float, values: tuple[float, ...]) -> float:
        if not values:
            return 0.0
        return min(values, key=lambda v: abs(_to_float(v) - price))

    @staticmethod
    def _norm_delta(candle: dict[str, Any]) -> float:
        volume = _to_float(candle.get("volume"))
        if volume <= 0:
            return 0.0
        return _to_float(candle.get("delta")) / volume

    @staticmethod
    def _session_minute(ts: str) -> float:
        parsed = ValentiniAMTEnv._parse_datetime(ts)
        return float(parsed.hour * 60 + parsed.minute)

    @staticmethod
    def _day_of_week(ts: str) -> float:
        return float(ValentiniAMTEnv._parse_datetime(ts).weekday())

    @staticmethod
    def _parse_datetime(ts: str) -> datetime:
        try:
            return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except Exception:
            return datetime.utcnow()

    def _aggression_sigma(self, bars: list) -> float:
        if len(bars) < 20:
            return 0.0
        def _vol(b: object) -> float:
            if isinstance(b, dict):
                return _to_float(b.get("volume", 0.0))
            return _to_float(getattr(b, "volume", 0.0))
        vols = [_vol(b) for b in bars[-20:]]
        mean = sum(vols) / len(vols)
        if mean == 0:
            return 0.0
        variance = sum((v - mean) ** 2 for v in vols) / len(vols)
        std = variance ** 0.5
        if std <= 0:
            return 0.0
        return (_vol(bars[-1]) - mean) / std

