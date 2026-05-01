
import { ChartConfig } from './types';

// Time constants
export const IST_OFFSET_SECONDS = 19800; // UTC+5:30 for Indian Standard Time

// Chart constants
export const DEFAULT_BAR_SPACING = {
  STANDARD: 6,
  FOOTPRINT: 160,
  RANGE: 40,
  MIN_STANDARD: 2,
  MIN_FOOTPRINT: 100,
  MIN_RANGE: 20,
};

export const DEFAULT_CONFIG: ChartConfig = {
  symbol: '',
  interval: '5m',
  dataSource: 'DHAN',
  bullColor: '#10b981', // Emerald 500
  bearColor: '#ef4444', // Red 500
  glassOpacity: 1.0,
  roughness: 0.1, // Smooth glass
  transmission: 0.95, // High transmission
  showGrid: true,
  autoRotate: false,
  showPredictions: true,
  showVolumeProfile: true,
  vpMode: 'combined',
  trend: 'volatile',
};

export const SAMPLE_PROMPTS = [
  "Show me nifty",
  "Set interval 15m",
  "Hide volume profile",
  "Bull color cyan",
  "Show predictions",
];
