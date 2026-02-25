
import { ChartConfig } from './types';

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
