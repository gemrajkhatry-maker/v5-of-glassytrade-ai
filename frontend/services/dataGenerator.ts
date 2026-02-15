
import { OHLCData } from '../types';

export const generateMarketData = (
  days: number = 50,
  startPrice: number = 150,
  trend: 'bullish' | 'bearish' | 'sideways' | 'volatile' = 'sideways'
): OHLCData[] => {
  const data: OHLCData[] = [];
  let currentPrice = startPrice;

  const volatility = trend === 'volatile' ? 0.08 : 0.03;
  let trendBias = 0;

  if (trend === 'bullish') trendBias = 0.005;
  if (trend === 'bearish') trendBias = -0.005;

  for (let i = 0; i < days; i++) {
    const changePercent = (Math.random() - 0.5) * volatility * 2 + trendBias;
    const open = currentPrice;
    const close = open * (1 + changePercent);
    
    // Calculate high/low based on open/close with some wicks
    const maxVal = Math.max(open, close);
    const minVal = Math.min(open, close);
    
    const high = maxVal * (1 + Math.random() * 0.02);
    const low = minVal * (1 - Math.random() * 0.02);

    // Generate random volume (simulating higher volume on big moves)
    const moveSize = Math.abs(close - open) / open;
    const baseVolume = 1000;
    const volume = baseVolume * (1 + moveSize * 50) * (Math.random() * 0.5 + 0.5);

    // Synthetic Order Flow Data
    // In a bullish move, delta tends to be positive (Aggressive Buying)
    const direction = close > open ? 1 : -1;
    const deltaBias = direction * 0.3; // 30% bias
    const randomDeltaFactor = (Math.random() * 2 - 1); // -1 to 1
    const deltaRatio = Math.max(-0.9, Math.min(0.9, deltaBias + (randomDeltaFactor * 0.5)));
    const delta = volume * deltaRatio;
    
    const takerBuyVolume = (volume + delta) / 2;

    // Synthetic VWAP - usually roughly in the middle of the candle body/range
    const typicalPrice = (high + low + close) / 3;
    const vwap = typicalPrice + ((Math.random() - 0.5) * (high - low) * 0.2);

    // Format date
    const date = new Date();
    date.setDate(date.getDate() - (days - i));
    const time = date.toISOString().split('T')[0];

    data.push({
      time,
      open,
      high,
      low,
      close,
      volume,
      vwap,
      takerBuyVolume,
      delta
    });

    currentPrice = close;
  }

  return data;
};
