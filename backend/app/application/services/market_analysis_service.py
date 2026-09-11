from quant.amt.market.half_trend import compute_half_trend_series


class MarketAnalysisService:
    """Application boundary for backend market analysis queries."""

    @staticmethod
    def halftrend(candles):
        return compute_half_trend_series(candles)
