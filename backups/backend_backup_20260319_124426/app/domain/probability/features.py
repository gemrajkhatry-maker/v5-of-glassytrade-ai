"""Feature extraction for the first-passage probability model.

The active production model contract is a 42-feature schema defined by
``FEATURE_NAMES``. Some additional runtime diagnostics can be computed, but
they must not silently enter the model vector unless the trained artifacts are
rebuilt and the schema version is promoted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.domain.trading.models.enums import MarketStateCodec, ProfileShapeCodec

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, AMTResult, OrderBook

PROBABILITY_FEATURE_SCHEMA_VERSION = "fp-42-v1"

# Canonical feature order — must match training artifacts and inference.
FEATURE_NAMES: tuple[str, ...] = (
    # Group A — Price Microstructure (12)
    "close_vs_poc_pct",
    "close_vs_vah_pct",
    "close_vs_val_pct",
    "close_vs_vwap_pct",
    "atr_5",
    "atr_20",
    "atr_ratio",
    "bar_range_pct",
    "body_pct",
    "upper_wick_ratio",
    "lower_wick_ratio",
    "close_position_in_range",
    # Group B — Order Flow (8)
    "delta_normalized",
    "cvd_slope",
    "cvd_divergence_flag",
    "aggression",
    "volume_vs_ema20",
    "delta_acceleration",
    "cumulative_delta_3bar",
    "aggressive_print_imbalance",
    # Group C — Volume Profile Structure (6)
    "profile_shape_encoded",
    "balance_ratio",
    "va_width_pct",
    "market_state_encoded",
    "hvn_count",
    "nearest_lvn_distance_pct",
    # Group D — Order Book (6)
    "bid_ask_spread_bps",
    "book_imbalance_l1",
    "book_imbalance_l5",
    # "book_imbalance_l20",  # L20 depth imbalance — NOT in trained model (diagnostic only)
    "bid_depth_total",
    "ask_depth_total",
    "book_pressure_ratio",
    # Group E — Temporal (4)
    "minutes_since_open",
    "session_flag",
    "day_of_week",
    "bars_since_last_displacement",
    # Group F — Options-Specific (6)
    "oi_change_pct",
    "option_type_flag",
    "underlying_return_5bar",
    "moneyness_pct",
    "dte_normalized",
    "oi_volume_ratio",
)



def extract_features(
    data: list[OHLC],
    amt_result: AMTResult,
    tick: OHLC,
    order_book: "OrderBook | None" = None,
    *,
    option_type_flag: float = 0.0,
    moneyness_pct: float = 0.0,
    dte_normalized: float = 0.0,
    oi: float = 0.0,
    prev_oi: float = 0.0,
    is_mcx: bool = False,
) -> dict[str, float]:
    """Extract active model features plus any runtime-only diagnostic extras.

    All values are floats. Missing data defaults to 0.0.
    Options-specific params (option_type_flag, moneyness_pct, etc.)
    are passed from the trading session when trading options.
    """
    close = tick.close
    if close <= 0:
        return {name: 0.0 for name in FEATURE_NAMES}

    f: dict[str, float] = {}

    # --- Group A: Price Microstructure ---
    f["close_vs_poc_pct"] = (close - amt_result.poc) / close if amt_result.poc > 0 else 0.0
    f["close_vs_vah_pct"] = (close - amt_result.value_area_high) / close if amt_result.value_area_high > 0 else 0.0
    f["close_vs_val_pct"] = (close - amt_result.value_area_low) / close if amt_result.value_area_low > 0 else 0.0
    vwap = amt_result.session_vwap if amt_result.session_vwap > 0 else (tick.vwap if tick.vwap > 0 else 0)
    f["close_vs_vwap_pct"] = (close - vwap) / close if vwap > 0 else 0.0

    atr_5 = _atr(data, 5)
    atr_20 = _atr(data, 20)
    f["atr_5"] = atr_5
    f["atr_20"] = atr_20
    f["atr_ratio"] = atr_5 / atr_20 if atr_20 > 0 else 1.0

    bar_range = tick.high - tick.low
    f["bar_range_pct"] = bar_range / close if close > 0 else 0.0
    f["body_pct"] = abs(tick.close - tick.open) / close
    if bar_range > 0:
        f["upper_wick_ratio"] = (tick.high - max(tick.open, tick.close)) / bar_range
        f["lower_wick_ratio"] = (min(tick.open, tick.close) - tick.low) / bar_range
        f["close_position_in_range"] = (tick.close - tick.low) / bar_range
    else:
        f["upper_wick_ratio"] = 0.0
        f["lower_wick_ratio"] = 0.0
        f["close_position_in_range"] = 0.5

    # --- Group B: Order Flow ---
    f["delta_normalized"] = tick.delta / tick.volume if tick.volume > 0 else 0.0
    f["cvd_slope"] = amt_result.cvd_slope
    div = amt_result.cvd_divergence
    f["cvd_divergence_flag"] = 1.0 if div == "BULLISH_DIV" else (-1.0 if div == "BEARISH_DIV" else 0.0)
    f["aggression"] = amt_result.aggression

    # Volume vs EMA(20)
    if len(data) >= 20:
        alpha = 2.0 / 21
        ema = data[-20].volume
        for d in data[-19:]:
            ema = alpha * d.volume + (1 - alpha) * ema
        f["volume_vs_ema20"] = tick.volume / ema if ema > 0 else 1.0
    else:
        f["volume_vs_ema20"] = 1.0

    # Delta acceleration (current - previous)
    f["delta_acceleration"] = (tick.delta - data[-2].delta) if len(data) >= 2 else 0.0

    # Cumulative delta last 3 bars
    last3 = data[-3:] if len(data) >= 3 else data
    f["cumulative_delta_3bar"] = sum(d.delta for d in last3)

    # Aggressive print imbalance over last 5 bars
    buy_agg = sum(1 for ap in amt_result.aggressive_prints if ap.side == "BUY")
    sell_agg = sum(1 for ap in amt_result.aggressive_prints if ap.side == "SELL")
    total_agg = buy_agg + sell_agg
    f["aggressive_print_imbalance"] = (buy_agg - sell_agg) / total_agg if total_agg > 0 else 0.0

    # --- Group C: Volume Profile Structure ---
    f["profile_shape_encoded"] = ProfileShapeCodec.encode(str(amt_result.profile_shape))
    f["balance_ratio"] = amt_result.balance_ratio
    va_width = amt_result.value_area_high - amt_result.value_area_low
    f["va_width_pct"] = va_width / close if close > 0 else 0.0
    f["market_state_encoded"] = MarketStateCodec.encode(amt_result.market_state)
    f["hvn_count"] = float(len(amt_result.hvns))
    
    if amt_result.lvns:
        nearest_lvn_dist = min(abs(close - lvn) for lvn in amt_result.lvns)
        f["nearest_lvn_distance_pct"] = nearest_lvn_dist / close
    else:
        f["nearest_lvn_distance_pct"] = 0.0

    # --- Group D: Order Book ---
    if order_book and order_book.bids and order_book.asks:
        best_bid = order_book.bids[0].price
        best_ask = order_book.asks[0].price
        mid = (best_bid + best_ask) / 2
        f["bid_ask_spread_bps"] = (best_ask - best_bid) / mid * 10000 if mid > 0 else 0.0

        bid_q1 = order_book.bids[0].quantity
        ask_q1 = order_book.asks[0].quantity
        total_q1 = bid_q1 + ask_q1
        f["book_imbalance_l1"] = (bid_q1 - ask_q1) / total_q1 if total_q1 > 0 else 0.0

        bid_q5 = sum(l.quantity for l in order_book.bids[:5])
        ask_q5 = sum(l.quantity for l in order_book.asks[:5])
        total_q5 = bid_q5 + ask_q5
        f["book_imbalance_l5"] = (bid_q5 - ask_q5) / total_q5 if total_q5 > 0 else 0.0

        bid_q20 = sum(l.quantity for l in order_book.bids[:20])
        ask_q20 = sum(l.quantity for l in order_book.asks[:20])

        f["bid_depth_total"] = bid_q20
        f["ask_depth_total"] = ask_q20
        f["book_pressure_ratio"] = bid_q20 / ask_q20 if ask_q20 > 0 else 1.0
        
        # L20 order book imbalance (depth20 for NSE)
        total_q20 = bid_q20 + ask_q20
        f["book_imbalance_l20"] = (bid_q20 - ask_q20) / total_q20 if total_q20 > 0 else 0.0
    else:
        f["bid_ask_spread_bps"] = 0.0
        f["book_imbalance_l1"] = 0.0
        f["book_imbalance_l5"] = 0.0
        f["book_imbalance_l20"] = 0.0  # L20 depth imbalance
        f["bid_depth_total"] = 0.0
        f["ask_depth_total"] = 0.0
        f["book_pressure_ratio"] = 1.0

    # --- Group E: Temporal ---
    f["minutes_since_open"] = _minutes_since_open(tick.time, is_mcx)
    f["session_flag"] = _session_flag(tick.time, is_mcx)
    f["day_of_week"] = _day_of_week(tick.time)
    f["bars_since_last_displacement"] = _bars_since_displacement(data, amt_result)

    # --- Group F: Options-Specific ---
    oi_change = oi - prev_oi
    f["oi_change_pct"] = (oi_change / prev_oi * 100) if prev_oi > 0 else 0.0
    f["option_type_flag"] = option_type_flag
    
    # Calculate underlying_return_5bar from data array as a proxy
    if len(data) >= 5:
        past_close = data[-5].close
        ur_5 = (close - past_close) / past_close if past_close > 0 else 0.0
    else:
        ur_5 = 0.0
    f["underlying_return_5bar"] = float(ur_5)
    
    f["moneyness_pct"] = moneyness_pct
    f["dte_normalized"] = dte_normalized
    f["oi_volume_ratio"] = oi / tick.volume if tick.volume > 0 and oi > 0 else 0.0

    return f


# ---------------------------------------------------------------------------
# Feature extraction for batch training (from DataFrame row + rolling data)
# ---------------------------------------------------------------------------

def extract_features_from_row(
    row: dict,
    data_window: list[OHLC] | None = None,
    is_mcx: bool = False,
) -> dict[str, float]:
    """Extract features from a labeled DataFrame row (training pipeline).

    Used by train_first_passage.py where we don't have live AMTResult objects
    but have pre-computed indicator columns in the parquet files.
    """
    close = float(row.get("close", 0))
    if close <= 0:
        return {name: 0.0 for name in FEATURE_NAMES}

    f: dict[str, float] = {}

    poc = float(row.get("poc", 0))
    vah = float(row.get("vah", 0))
    val = float(row.get("val", 0))
    vwap = float(row.get("session_vwap", 0))
    delta = float(row.get("delta", 0))
    volume = float(row.get("volume", 0))

    f["close_vs_poc_pct"] = (close - poc) / close if poc > 0 else 0.0
    f["close_vs_vah_pct"] = (close - vah) / close if vah > 0 else 0.0
    f["close_vs_val_pct"] = (close - val) / close if val > 0 else 0.0
    f["close_vs_vwap_pct"] = (close - vwap) / close if vwap > 0 else 0.0

    # ATR from data_window if available, else approximate from row
    if data_window and len(data_window) >= 20:
        f["atr_5"] = _atr(data_window, 5)
        f["atr_20"] = _atr(data_window, 20)
    else:
        bar_range = float(row.get("high", 0)) - float(row.get("low", 0))
        f["atr_5"] = bar_range  # crude single-bar proxy
        f["atr_20"] = bar_range
    f["atr_ratio"] = f["atr_5"] / f["atr_20"] if f["atr_20"] > 0 else 1.0

    high = float(row.get("high", close))
    low = float(row.get("low", close))
    opn = float(row.get("open", close))
    bar_range = high - low
    f["bar_range_pct"] = bar_range / close if close > 0 else 0.0
    f["body_pct"] = abs(close - opn) / close if close > 0 else 0.0
    if bar_range > 0:
        f["upper_wick_ratio"] = (high - max(opn, close)) / bar_range
        f["lower_wick_ratio"] = (min(opn, close) - low) / bar_range
        f["close_position_in_range"] = (close - low) / bar_range
    else:
        f["upper_wick_ratio"] = 0.0
        f["lower_wick_ratio"] = 0.0
        f["close_position_in_range"] = 0.5

    # Order flow
    f["delta_normalized"] = delta / volume if volume > 0 else 0.0
    f["cvd_slope"] = float(row.get("cvd_slope", 0))
    div = str(row.get("cvd_divergence", ""))
    f["cvd_divergence_flag"] = 1.0 if div == "BULLISH_DIV" else (-1.0 if div == "BEARISH_DIV" else 0.0)
    f["aggression"] = float(row.get("aggression", 0))
    f["volume_vs_ema20"] = 1.0  # no rolling EMA in batch row
    f["delta_acceleration"] = 0.0
    f["cumulative_delta_3bar"] = delta * 3  # crude proxy
    f["aggressive_print_imbalance"] = 0.0  # not available in row

    # Volume profile
    f["profile_shape_encoded"] = ProfileShapeCodec.encode(str(row.get("profile_shape", "D")))
    f["balance_ratio"] = float(row.get("balance_ratio", 0))
    va_width = vah - val
    f["va_width_pct"] = va_width / close if close > 0 else 0.0
    f["market_state_encoded"] = MarketStateCodec.encode(row.get("market_state", ""))
    hvns_str = str(row.get("hvns", ""))
    f["hvn_count"] = float(len([x for x in hvns_str.split(",") if x.strip()])) if hvns_str else 0.0
    lvns_str = str(row.get("lvns", ""))
    if lvns_str:
        lvn_vals = [float(x) for x in lvns_str.split(",") if x.strip()]
        if lvn_vals:
            f["nearest_lvn_distance_pct"] = min(abs(close - lv) for lv in lvn_vals) / close
        else:
            f["nearest_lvn_distance_pct"] = 0.0
    else:
        f["nearest_lvn_distance_pct"] = 0.0

    # Order book — not available in historical training
    f["bid_ask_spread_bps"] = 0.0
    f["book_imbalance_l1"] = 0.0
    f["book_imbalance_l5"] = 0.0
    f["bid_depth_total"] = 0.0
    f["ask_depth_total"] = 0.0
    f["book_pressure_ratio"] = 1.0

    # Temporal
    ts = str(row.get("timestamp", ""))
    f["minutes_since_open"] = _minutes_since_open(ts, is_mcx)
    f["session_flag"] = _session_flag(ts, is_mcx)
    f["day_of_week"] = _day_of_week(ts)
    f["bars_since_last_displacement"] = float(row.get("bars_since_displacement", 0))

    # Options-specific
    f["oi_change_pct"] = float(row.get("oi_change_pct", 0))
    f["option_type_flag"] = float(row.get("option_type_flag", 0))
    f["underlying_return_5bar"] = float(row.get("underlying_return_5bar", 0))
    f["moneyness_pct"] = float(row.get("moneyness_pct", 0))
    f["dte_normalized"] = 0.0  # not available in historical parquets
    f["oi_volume_ratio"] = float(row.get("oi_volume_ratio", 0))

    return f


def active_model_features(features: dict[str, float]) -> dict[str, float]:
    """Return only the active schema features used by the trained models."""
    return {name: float(features.get(name, 0.0)) for name in FEATURE_NAMES}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atr(data: "list[OHLC]", period: int) -> float:
    if len(data) < period:
        return 0.0
    return sum(d.high - d.low for d in data[-period:]) / period


def _parse_time(time_str: str):
    """Parse ISO time string to hour/minute. Returns (hour, minute, weekday) or None."""
    from datetime import datetime
    try:
        if "T" in time_str:
            dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(time_str[:19], "%Y-%m-%d %H:%M:%S")
        return dt.hour, dt.minute, dt.weekday()
    except Exception:
        return None


def _minutes_since_open(time_str: str, is_mcx: bool = False) -> float:
    """Minutes since market open. NSE=09:15, MCX=09:00 IST."""
    parsed = _parse_time(time_str)
    if not parsed:
        return 0.0
    hour, minute, _ = parsed
    if is_mcx:
        return max(0.0, (hour - 9) * 60 + minute)
    return max(0.0, (hour - 9) * 60 + (minute - 15))


def _session_flag(time_str: str, is_mcx: bool = False) -> float:
    """NSE/MCX session flags based on market structure."""
    parsed = _parse_time(time_str)
    if not parsed:
        return 0.0
    hour, minute, _ = parsed
    total_min = hour * 60 + minute
    
    if is_mcx:
        # MCX sessions: 0=morning(09-14), 1=midday(14-17), 2=ny(17-23:30)
        if total_min < 840:    # < 14:00
            return 0.0
        elif total_min < 1020: # < 17:00
            return 1.0
        else:
            return 2.0
    else:
        # NSE session: 0=opening(9:15-10:00), 1=morning(10-12), 2=midday(12-14), 3=closing(14-15:30)
        if total_min < 600:    # before 10:00
            return 0.0
        elif total_min < 720:  # 10:00-12:00
            return 1.0
        elif total_min < 840:  # 12:00-14:00
            return 2.0
        else:
            return 3.0


def _day_of_week(time_str: str) -> float:
    parsed = _parse_time(time_str)
    if not parsed:
        return 0.0
    return float(parsed[2])


def _bars_since_displacement(data: "list[OHLC]", amt_result: "AMTResult") -> float:
    """Count bars since last displacement. Returns 0 if currently displaced."""
    if amt_result.has_displacement:
        return 0.0
    # Heuristic: no displacement tracking in history, return high value
    return 20.0
