"""Vectorized compute primitives — pure Python optimized for per-tick hot path.

MLX GPU acceleration available for batch operations (>500 elements) via
`batch_*` variants.  Per-tick operations use optimized pure Python since
list→mx.array conversion overhead dominates for small arrays (<100 elements).

On M1 Max: pure Python is ~20x faster than MLX for 100-element arrays.
MLX wins at 5000+ elements (training pipelines, batch indicator computation).
"""

from __future__ import annotations
import math

# MLX disabled - Metal GPU initialization crashes on this system
# All computations will use optimized pure Python instead
_HAS_MLX = False
mx = None

def _ensure_mlx():
    """MLX is disabled on this system."""
    return False

# MLX crossover point: only use GPU above this array size
_MLX_MIN_SIZE = 500


# ---------------------------------------------------------------------------
# Per-tick functions (pure Python — fastest for small arrays)
# ---------------------------------------------------------------------------

def gaussian_weights(bucket_centers: list[float], center: float, sigma: float) -> list[float]:
    """Normalized Gaussian weights for volume distribution.  Returns weights summing to 1.0."""
    if not bucket_centers or sigma <= 0:
        n = max(1, len(bucket_centers))
        return [1.0 / n] * n
    inv_2sig2 = -0.5 / (sigma * sigma)
    weights = [math.exp(inv_2sig2 * (bc - center) * (bc - center)) for bc in bucket_centers]
    total = sum(weights)
    if total <= 0:
        n = len(bucket_centers)
        return [1.0 / n] * n
    inv_total = 1.0 / total
    return [w * inv_total for w in weights]


def smooth_array(data: list[float], window: int) -> list[float]:
    """Centered simple moving average smoothing."""
    n = len(data)
    if n == 0 or window <= 1:
        return list(data)
    offset = window // 2
    smoothed = []
    for i in range(n):
        start = max(0, i - offset)
        end = min(n, i + offset + 1)
        total = 0.0
        for j in range(start, end):
            total += data[j]
        smoothed.append(total / (end - start))
    return smoothed


def ema(values: list[float], period: int) -> float:
    """Exponential moving average, returns final value."""
    if not values:
        return 0.0
    k = 2.0 / (period + 1)
    k1 = 1.0 - k
    result = values[0]
    for v in values[1:]:
        result = v * k + result * k1
    return result


def linreg_slope(ys: list[float]) -> float:
    """OLS slope for evenly-spaced y values."""
    n = len(ys)
    if n < 2:
        return 0.0
    x_mean = (n - 1) * 0.5
    y_mean = sum(ys) / n
    num = 0.0
    den = 0.0
    for i in range(n):
        dx = i - x_mean
        num += dx * (ys[i] - y_mean)
        den += dx * dx
    return num / den if den != 0.0 else 0.0


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    """Average True Range over period candles."""
    n = len(highs)
    if n < 2:
        return (highs[0] - lows[0]) if n == 1 else 1.0
    trs = []
    for i in range(1, n):
        h_l = highs[i] - lows[i]
        h_pc = abs(highs[i] - closes[i - 1])
        l_pc = abs(lows[i] - closes[i - 1])
        trs.append(max(h_l, h_pc, l_pc))
    subset = trs[-period:] if len(trs) >= period else trs
    return sum(subset) / len(subset) if subset else 1.0


def candle_overlap_pct(highs: list[float], lows: list[float], period: int = 10) -> float:
    """Mean overlap percentage between consecutive candles."""
    n = len(highs)
    if n < 2:
        return 100.0
    start = max(0, n - period)
    total_pct = 0.0
    count = 0
    for i in range(start + 1, n):
        cur_range = highs[i] - lows[i]
        if cur_range <= 0.0:
            total_pct += 100.0
        else:
            overlap = max(0.0, min(highs[i - 1], highs[i]) - max(lows[i - 1], lows[i]))
            total_pct += (overlap / cur_range) * 100.0
        count += 1
    return total_pct / count if count else 100.0


def weighted_moments(prices: list[float], volumes: list[float]) -> tuple[float, float, float]:
    """Compute weighted skewness, kurtosis (excess), and std.  Returns (skewness, kurtosis, std)."""
    total_vol = sum(volumes)
    if total_vol <= 0:
        return 0.0, 0.0, 0.0
    inv_total = 1.0 / total_vol
    mean = sum(p * v for p, v in zip(prices, volumes)) * inv_total
    m2 = m3 = m4 = 0.0
    for p, v in zip(prices, volumes):
        w = v * inv_total
        d = p - mean
        d2 = d * d
        m2 += w * d2
        m3 += w * d2 * d
        m4 += w * d2 * d2
    std_val = math.sqrt(m2) if m2 > 0 else 0.0
    if std_val < 1e-9:
        return 0.0, 0.0, 0.0
    s3 = std_val * std_val * std_val
    s4 = s3 * std_val
    return m3 / s3, (m4 / s4) - 3.0, std_val


def count_peaks(volumes: list[float], min_prominence: float = 0.25) -> int:
    """Count significant local maxima in volume histogram."""
    if len(volumes) < 5:
        return 1
    max_vol = max(volumes)
    if max_vol <= 0:
        return 0
    threshold = max_vol * min_prominence
    peaks = 0
    for i in range(1, len(volumes) - 1):
        if volumes[i] > volumes[i - 1] and volumes[i] > volumes[i + 1] and volumes[i] >= threshold:
            peaks += 1
    return peaks


def aggression_sigma(candle_volume: float, volumes: list[float], ema_period: int = 20) -> float:
    """Z-score of candle volume vs EMA-based dynamic threshold."""
    if len(volumes) < 10 or candle_volume == 0:
        return 0.0
    alpha = 2.0 / (ema_period + 1)
    alpha1 = 1.0 - alpha
    ema_val = volumes[0]
    for v in volumes[1:]:
        ema_val = alpha * v + alpha1 * ema_val
    # Seed variance with population variance of first N values to avoid warm-up bias
    seed_n = min(10, len(volumes))
    seed_mean = sum(volumes[:seed_n]) / seed_n
    ema_var = sum((v - seed_mean) ** 2 for v in volumes[:seed_n]) / seed_n
    ema_run = volumes[0]
    for v in volumes[1:]:
        residual = v - ema_run
        ema_var = alpha * (residual * residual) + alpha1 * ema_var
        ema_run = alpha * v + alpha1 * ema_run
    std_val = math.sqrt(ema_var) if ema_var > 0 else 1.0
    # Floor: std must be at least 10% of EMA mean to prevent inflated z-scores
    min_std = abs(ema_val) * 0.10
    std_val = max(std_val, min_std) if min_std > 0 else max(std_val, 1.0)
    return (candle_volume - ema_val) / std_val if std_val > 0 else 0.0


def divergence_detect(prices: list[float], cvds: list[float]) -> tuple[str, float]:
    """Detect price-vs-CVD divergence.  Returns (type, z_score)."""
    w = len(prices)
    if w < 4 or len(cvds) < w:
        return "NONE", 0.0
    half = w // 2
    p1_max = max(prices[:half])
    p2_max = max(prices[half:])
    c1_max = max(cvds[:half])
    c2_max = max(cvds[half:])
    p1_min = min(prices[:half])
    p2_min = min(prices[half:])
    c1_min = min(cvds[:half])
    c2_min = min(cvds[half:])
    mean_p = sum(prices) / w
    price_std = math.sqrt(sum((p - mean_p) ** 2 for p in prices) / w)
    if price_std == 0:
        price_std = 1.0
    if p2_max > p1_max and c2_max < c1_max:
        return "BEARISH_DIV", abs(p2_max - p1_max) / price_std
    if p2_min < p1_min and c2_min > c1_min:
        return "BULLISH_DIV", abs(p2_min - p1_min) / price_std
    return "NONE", 0.0


def std(values: list[float]) -> float:
    """Population standard deviation."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / n)


# ---------------------------------------------------------------------------
# Batch functions (MLX GPU — for training pipelines with large arrays)
# ---------------------------------------------------------------------------

def batch_gaussian_weights(bucket_centers: list[float], center: float, sigma: float) -> list[float]:
    """MLX GPU Gaussian weights — use for arrays > 500 elements."""
    _ensure_mlx()
    if not _HAS_MLX or len(bucket_centers) < _MLX_MIN_SIZE:
        return gaussian_weights(bucket_centers, center, sigma)
    c = mx.array(bucket_centers, dtype=mx.float32)
    z = (c - center) / sigma
    w = mx.exp(-0.5 * z * z)
    total = mx.sum(w)
    if total.item() <= 0:
        n = len(bucket_centers)
        return [1.0 / n] * n
    return (w / total).tolist()


def batch_weighted_moments(prices: list[float], volumes: list[float]) -> tuple[float, float, float]:
    """MLX GPU weighted moments — use for arrays > 500 elements."""
    _ensure_mlx()
    if not _HAS_MLX or len(prices) < _MLX_MIN_SIZE:
        return weighted_moments(prices, volumes)
    p = mx.array(prices, dtype=mx.float32)
    v = mx.array(volumes, dtype=mx.float32)
    total = mx.sum(v)
    if total.item() <= 0:
        return 0.0, 0.0, 0.0
    w = v / total
    mean = mx.sum(p * w)
    d = p - mean
    d2 = d * d
    m2 = mx.sum(w * d2)
    m3 = mx.sum(w * d2 * d)
    m4 = mx.sum(w * d2 * d2)
    std_val = float(mx.sqrt(mx.maximum(m2, mx.array(0.0))).item())
    if std_val < 1e-9:
        return 0.0, 0.0, 0.0
    s3 = std_val ** 3
    s4 = std_val ** 4
    return float(m3.item()) / s3, float(m4.item()) / s4 - 3.0, std_val


def batch_linreg_slope(ys: list[float]) -> float:
    """MLX GPU linreg — use for arrays > 500 elements."""
    _ensure_mlx()
    if not _HAS_MLX or len(ys) < _MLX_MIN_SIZE:
        return linreg_slope(ys)
    n = len(ys)
    y = mx.array(ys, dtype=mx.float32)
    x = mx.arange(n, dtype=mx.float32)
    x_mean = (n - 1) * 0.5
    y_mean = mx.mean(y)
    dx = x - x_mean
    dy = y - y_mean
    num = mx.sum(dx * dy)
    den = mx.sum(dx * dx)
    if den.item() == 0.0:
        return 0.0
    return (num / den).item()


def batch_atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    """MLX GPU ATR — use for arrays > 500 elements."""
    _ensure_mlx()
    if not _HAS_MLX or len(highs) < _MLX_MIN_SIZE:
        return atr(highs, lows, closes, period)
    h = mx.array(highs[1:], dtype=mx.float32)
    l = mx.array(lows[1:], dtype=mx.float32)
    prev_c = mx.array(closes[:-1], dtype=mx.float32)
    tr = mx.maximum(h - l, mx.maximum(mx.abs(h - prev_c), mx.abs(l - prev_c)))
    subset = tr[-period:] if len(tr) >= period else tr
    result = mx.mean(subset).item()
    return result if result > 0 else 1.0
