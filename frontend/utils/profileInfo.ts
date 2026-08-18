import { AMTAnalysis } from '../types';
import { PROFILE_CONFIG } from '../config';

/**
 * Profile-overlay context helpers — pure functions over the AMT analysis the
 * backend already streams. No new state, no backend changes.
 */

// MCX underlyings (mirrors the backend's DhanMarketDataAdapter set).
const MCX_UNDERLYINGS = new Set([
  'CRUDEOIL', 'GOLD', 'SILVER', 'NATURALGAS', 'GOLDM', 'SILVERM',
  'CRUDEOILM', 'COPPER', 'ZINC', 'ALUMINIUM', 'LEAD', 'NICKEL', 'COTTONCANDY',
]);

// Session hours per exchange — MCX commodities open 09:00, NSE indices 09:15.
const SESSION_HOURS: Record<string, string> = {
  MCX: '09:00-23:30 IST',
  NSE: '09:15-15:30 IST',
};

export type Exchange = 'MCX' | 'NSE';

export function detectExchange(symbol: string): Exchange {
  const head = (symbol || '').split(/\s+/)[0].toUpperCase();
  return MCX_UNDERLYINGS.has(head) ? 'MCX' : 'NSE';
}

export function sessionHoursForExchange(exchange: Exchange): { open: string; close: string; label: string } {
  const label = SESSION_HOURS[exchange];
  const [open, close] = label.split('-');
  return { open, close, label };
}

export type Confluence = 'CONFLUENCE' | 'DIVERGENCE' | 'NEUTRAL' | null;

/** Confluence: |sPoc - lPoc| / sPoc <= 0.1% = CONFLUENCE; >= 0.5% = DIVERGENCE. */
export function computeConfluence(sPoc: number, lPoc: number): Confluence {
  if (!sPoc || !lPoc) return null;
  const diffPct = Math.abs(sPoc - lPoc) / Math.abs(sPoc);
  if (diffPct <= PROFILE_CONFIG.confluenceThreshold) return 'CONFLUENCE';
  if (diffPct >= PROFILE_CONFIG.divergenceThreshold) return 'DIVERGENCE';
  return 'NEUTRAL';
}

export interface ProfileSummary {
  mode: 'session' | 'leg' | 'combined';
  exchange: Exchange;
  hours: string;
  poc: number;
  vah: number;
  val: number;
  confluence: Confluence;
}

/**
 * Builds the display context for the active profile overlay mode. Session uses
 * session POC/VA with fixed session hours; Leg uses the displacement leg
 * levels (orange); Combined shows both plus a confluence/divergence badge.
 */
export function buildProfileSummary(
  amt: AMTAnalysis | null,
  mode: 'session' | 'leg' | 'combined' | 'off',
  symbol: string,
): ProfileSummary | null {
  if (!amt || mode === 'off') return null;
  const exchange = detectExchange(symbol);
  const hours = SESSION_HOURS[exchange];
  if (mode === 'session') {
    return {
      mode, exchange, hours,
      poc: Number(amt.poc ?? 0), vah: Number(amt.valueAreaHigh ?? 0), val: Number(amt.valueAreaLow ?? 0),
      confluence: null,
    };
  }
  if (mode === 'leg') {
    return {
      mode, exchange, hours,
      poc: Number(amt.legPoc ?? 0), vah: Number(amt.legVah ?? 0), val: Number(amt.legVal ?? 0),
      confluence: null,
    };
  }
  return {
    mode, exchange, hours,
    poc: Number(amt.poc ?? 0), vah: Number(amt.valueAreaHigh ?? 0), val: Number(amt.valueAreaLow ?? 0),
    confluence: computeConfluence(Number(amt.poc ?? 0), Number(amt.legPoc ?? 0)),
  };
}
