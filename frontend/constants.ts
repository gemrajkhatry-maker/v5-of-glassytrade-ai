
import { ChartConfig } from './types';

export const DEFAULT_CONFIG: ChartConfig = {
  symbol: 'BTCUSDT',
  interval: '5m',
  dataSource: 'BINANCE',
  bullColor: '#10b981', // Emerald 500
  bearColor: '#ef4444', // Red 500
  glassOpacity: 1.0,
  roughness: 0.1, // Smooth glass
  transmission: 0.95, // High transmission
  showGrid: true,
  autoRotate: false,
  showPredictions: true,
  showVolumeProfile: true,
  trend: 'volatile',
};

export const SAMPLE_PROMPTS = [
  "Show me ETH live",
  "Make the chart look like red and blue neon",
  "Simulate a market crash",
  "Turn on auto rotation",
  "Change to 1h timeframe",
];
