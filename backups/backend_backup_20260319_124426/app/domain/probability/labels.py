"""First-passage label generation for probability model training.

For each bar, looks forward W bars and checks whether price hits
the target excursion (+T%) before the adverse excursion (-S%).
Also captures MFE, MAE, and time-to-hit.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class FirstPassageLabel:
    """Label for a single bar's first-passage outcome."""
    long_hit_target: bool
    long_hit_stop: bool
    short_hit_target: bool
    short_hit_stop: bool
    mfe_long_pct: float   # Max favorable excursion if long
    mae_long_pct: float   # Max adverse excursion if long
    mfe_short_pct: float  # Max favorable excursion if short
    mae_short_pct: float  # Max adverse excursion if short
    time_to_long_hit: int  # Bars until long target or stop (W if neither)
    time_to_short_hit: int


def generate_first_passage_labels(
    df: pd.DataFrame,
    target_pct: float = 0.015,
    stop_pct: float = 0.0075,
    window: int = 6,
) -> pd.DataFrame:
    """Generate first-passage labels for all bars in a DataFrame.

    Parameters
    ----------
    df : DataFrame with at least 'close', 'high', 'low' columns, sorted by time.
    target_pct : favorable excursion threshold (e.g. 0.015 = 1.5%)
    stop_pct : adverse excursion threshold (e.g. 0.0075 = 0.75%)
    window : number of bars to look forward

    Returns
    -------
    DataFrame with additional columns:
        fp_long_target, fp_short_target (binary labels for classification)
        mfe_long_pct, mae_long_pct, mfe_short_pct, mae_short_pct
        time_to_long_hit, time_to_short_hit
    """
    n = len(df)
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values

    fp_long = []
    fp_short = []
    mfe_long_list = []
    mae_long_list = []
    mfe_short_list = []
    mae_short_list = []
    ttl_long = []
    ttl_short = []

    for i in range(n):
        entry = closes[i]
        if entry <= 0:
            fp_long.append(0)
            fp_short.append(0)
            mfe_long_list.append(0.0)
            mae_long_list.append(0.0)
            mfe_short_list.append(0.0)
            mae_short_list.append(0.0)
            ttl_long.append(window)
            ttl_short.append(window)
            continue

        long_target = entry * (1 + target_pct)
        long_stop = entry * (1 - stop_pct)
        short_target = entry * (1 - target_pct)
        short_stop = entry * (1 + stop_pct)

        # Walk forward
        long_hit = 0  # 0=neither, 1=target, -1=stop
        short_hit = 0
        mfe_l = 0.0
        mae_l = 0.0
        mfe_s = 0.0
        mae_s = 0.0
        time_l = window
        time_s = window

        end = min(i + 1 + window, n)
        for j in range(i + 1, end):
            h = highs[j]
            l = lows[j]
            bar_idx = j - i

            # Long MFE/MAE
            if h > entry:
                fav = (h - entry) / entry
                if fav > mfe_l:
                    mfe_l = fav
            if l < entry:
                adv = (entry - l) / entry
                if adv > mae_l:
                    mae_l = adv

            # Short MFE/MAE
            if l < entry:
                fav = (entry - l) / entry
                if fav > mfe_s:
                    mfe_s = fav
            if h > entry:
                adv = (h - entry) / entry
                if adv > mae_s:
                    mae_s = adv

            # Long first-passage
            if long_hit == 0:
                if l <= long_stop:
                    long_hit = -1
                    time_l = bar_idx
                elif h >= long_target:
                    long_hit = 1
                    time_l = bar_idx

            # Short first-passage
            if short_hit == 0:
                if h >= short_stop:
                    short_hit = -1
                    time_s = bar_idx
                elif l <= short_target:
                    short_hit = 1
                    time_s = bar_idx

            # Early exit if both resolved
            if long_hit != 0 and short_hit != 0:
                # Still need to track MFE/MAE for remaining bars
                for k in range(j + 1, end):
                    hk, lk = highs[k], lows[k]
                    if hk > entry:
                        mfe_l = max(mfe_l, (hk - entry) / entry)
                        mae_s = max(mae_s, (hk - entry) / entry)
                    if lk < entry:
                        mae_l = max(mae_l, (entry - lk) / entry)
                        mfe_s = max(mfe_s, (entry - lk) / entry)
                break

        fp_long.append(1 if long_hit == 1 else 0)
        fp_short.append(1 if short_hit == 1 else 0)
        mfe_long_list.append(mfe_l)
        mae_long_list.append(mae_l)
        mfe_short_list.append(mfe_s)
        mae_short_list.append(mae_s)
        ttl_long.append(time_l)
        ttl_short.append(time_s)

    result = df.copy()
    result["fp_long_target"] = fp_long
    result["fp_short_target"] = fp_short
    result["mfe_long_pct"] = mfe_long_list
    result["mae_long_pct"] = mae_long_list
    result["mfe_short_pct"] = mfe_short_list
    result["mae_short_pct"] = mae_short_list
    result["time_to_long_hit"] = ttl_long
    result["time_to_short_hit"] = ttl_short

    return result
