
import { OHLCData, AIAnalysis, OrderBook, ModelWeights, FactorBreakdown } from '../types';

/**
 * AI PREDICTION ENGINE (QUANT MODEL)
 * 
 * Uses dynamic weights provided by the Learning Engine.
 */

// Pseudo-random number generator seeded by index to ensure stability during re-renders
const seededRandom = (seed: number) => {
    const x = Math.sin(seed++) * 10000;
    return x - Math.floor(x);
};

// Calculate Linear Regression Slope for trend
const calculateTrend = (data: OHLCData[], period: number = 50): { direction: 'UP' | 'DOWN' | 'SIDEWAYS', slope: number } => {
    if (data.length < period) return { direction: 'SIDEWAYS', slope: 0 };
    
    const slice = data.slice(-period);
    const n = slice.length;
    
    let sumX = 0;
    let sumY = 0;
    let sumXY = 0;
    let sumXX = 0;
    
    for (let i = 0; i < n; i++) {
        sumX += i;
        sumY += slice[i].close;
        sumXY += i * slice[i].close;
        sumXX += i * i;
    }
    
    const slope = (n * sumXY - sumX * sumY) / (n * sumXX - sumX * sumX);
    const firstPrice = slice[0].close;
    
    // Normalize slope relative to price
    const relativeSlope = slope / firstPrice;

    if (relativeSlope > 0.0002) return { direction: 'UP', slope };
    if (relativeSlope < -0.0002) return { direction: 'DOWN', slope };
    return { direction: 'SIDEWAYS', slope };
};

export const predictAIModel = (
  data: OHLCData[], 
  weights: ModelWeights, // Accept dynamic weights
  count: number = 10,
  orderBook: OrderBook | null = null
): { predictions: OHLCData[], analysis: AIAnalysis } => {
  
  // Default fallbacks if data is missing
  if (data.length < 50) {
      return {
          predictions: [],
          analysis: {
              sentiment: 'NEUTRAL',
              confidence: 0,
              longTermTrend: 'SIDEWAYS',
              volatilityScore: 0,
              quantScore: 0,
              projectedPrice: 0,
              reasoning: ['Insufficient Data'],
              factorBreakdown: { trend: 0, momentum: 0, delta: 0, orderBook: 0, volatility: 0 }
          }
      };
  }

  const currentPrice = data[data.length - 1].close;
  const lastTime = new Date(data[data.length - 1].time).getTime();
  const timeStep = 5 * 60 * 1000; // 5 minutes

  // 1. QUANT ANALYSIS INPUTS
  const trend = calculateTrend(data, 50);
  const volatility = data.slice(-10).reduce((sum, d) => sum + (d.high - d.low), 0) / 10;
  
  const momentumPeriod = 14;
  const momData = data.slice(-momentumPeriod);
  const gains = momData.filter(d => d.close > d.open).length;
  const deltaSum = momData.reduce((sum, d) => sum + d.delta, 0);
  
  // 2. SCORING with Dynamic Weights
  // Base Score range: -100 to 100
  // Weights sum to approx 1.0. We multiply factor scores (normalized -100 to 100) by weight.

  const breakdown: FactorBreakdown = {
      trend: 0,
      momentum: 0,
      delta: 0,
      orderBook: 0,
      volatility: 0
  };

  // A. Trend Component
  if (trend.direction === 'UP') breakdown.trend = 100 * weights.trend;
  if (trend.direction === 'DOWN') breakdown.trend = -100 * weights.trend;

  // B. Momentum Component
  const rsiProxy = (gains / momentumPeriod) * 100; // 0 to 100
  // Normalize to -100 to 100 range
  const momScore = (rsiProxy - 50) * 2; 
  breakdown.momentum = momScore * weights.momentum;

  // C. Delta Component
  // Normalize delta relative to volume
  const avgVol = momData.reduce((s,d) => s + d.volume, 0) / momentumPeriod;
  const deltaRatio = avgVol > 0 ? (deltaSum / avgVol) : 0; // rough -1 to 1 estimate over period
  const clampedDelta = Math.max(-1, Math.min(1, deltaRatio));
  breakdown.delta = clampedDelta * 100 * weights.delta;

  // D. L2 Order Book Imbalance
  if (orderBook) {
      const bids = orderBook.bids.reduce((a, b) => a + b.quantity, 0);
      const asks = orderBook.asks.reduce((a, b) => a + b.quantity, 0);
      const total = bids + asks;
      if (total > 0) {
          const imbalance = (bids - asks) / total; // -1 to 1
          breakdown.orderBook = imbalance * 100 * weights.orderBook;
      }
  }

  // Calculate Final Score
  let quantScore = breakdown.trend + breakdown.momentum + breakdown.delta + breakdown.orderBook;
  quantScore = Math.max(-100, Math.min(100, quantScore));

  // Determine Sentiment & Confidence
  let sentiment: 'BULLISH' | 'BEARISH' | 'NEUTRAL' = 'NEUTRAL';
  let confidence = Math.abs(quantScore);

  // Confidence booster from Volatility (if low vol, higher confidence in trend? or opposite? depends on model)
  // Let's say if Volatility is "stable", we boost confidence slightly
  // This is a simplified mechanic
  
  if (quantScore > 20) sentiment = 'BULLISH';
  else if (quantScore < -20) sentiment = 'BEARISH';
  else {
      sentiment = 'NEUTRAL';
      confidence = 100 - confidence; // High confidence in chopping/neutral
  }

  // --- GHOST CANDLE GENERATION ---
  
  const predictions: OHLCData[] = [];
  let prevClose = currentPrice;
  const baseSeed = data.length * 55; // Unique seed per data update

  // Target Price projection based on Quant Score
  // If score is 100, we project a 2% move (arbitrary scaling)
  const percentMove = (quantScore / 100) * 0.02;
  const projectedPrice = currentPrice * (1 + percentMove);

  for (let i = 1; i <= count; i++) {
      const progress = i / count;
      // Use cubic ease out for projection curve
      const factor = 1 - Math.pow(1 - progress, 3);
      const baselinePrice = currentPrice + (projectedPrice - currentPrice) * factor;

      const noiseSeed = baseSeed + i;
      // Add random walk noise scaled by volatility
      const noise = (seededRandom(noiseSeed) - 0.5) * volatility * 1.2;
      
      const nextClose = baselinePrice + noise;
      const open = prevClose;
      
      const bodyMax = Math.max(open, nextClose);
      const bodyMin = Math.min(open, nextClose);
      
      const rawHigh = bodyMax + (seededRandom(noiseSeed + 100) * volatility * 0.5);
      const rawLow = bodyMin - (seededRandom(noiseSeed + 200) * volatility * 0.5);

      const high = Math.max(rawHigh, bodyMax);
      const low = Math.min(rawLow, bodyMin);
      
      const volume = 1000;
      const vwap = (high + low + nextClose) / 3;
      const direction = nextClose > open ? 1 : -1;
      const takerBuyVolume = volume * (0.5 + (direction * 0.1));
      const delta = (2 * takerBuyVolume) - volume;

      predictions.push({
          time: new Date(lastTime + (i * timeStep)).toISOString(),
          open, 
          high, 
          low,   
          close: nextClose, 
          volume,
          vwap,
          takerBuyVolume,
          delta
      });
      prevClose = nextClose;
  }

  const reasoning = [
      `Quant Score: ${quantScore.toFixed(0)}`,
      `Trend Weight: ${(weights.trend * 100).toFixed(0)}%`,
      `Order Flow Weight: ${(weights.delta * 100).toFixed(0)}%`,
      `Sentiment: ${sentiment} (${confidence.toFixed(0)}%)`
  ];

  return {
    predictions,
    analysis: {
        sentiment,
        confidence,
        longTermTrend: trend.direction,
        volatilityScore: volatility,
        quantScore,
        projectedPrice,
        reasoning,
        factorBreakdown: breakdown
    }
  };
};
