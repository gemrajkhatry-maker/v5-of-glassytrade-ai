
import { ChartConfig } from './types';

// Time constants
export const IST_OFFSET_SECONDS = 19800; // UTC+5:30 for Indian Standard Time

export const DEFAULT_CONFIG: ChartConfig = {
  symbol: '',
  bullColor: '#00c896', // Institutional green (85% saturation)
  bearColor: '#ff4757', // Institutional red (85% saturation)
  showVolumeProfile: true,
  vpMode: 'combined',
};
