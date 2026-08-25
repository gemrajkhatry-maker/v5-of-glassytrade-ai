import { AMTAnalysis } from '../types';
import { THREE_A_CONFIG } from '../config';

/**
 * Three-A (Valentini AMT) rule SCORING ONLY — informational traffic lights,
 * computed deterministically from the AMT analysis fields the backend already
 * streams. Pure function — no UI, and NOT a trading verdict.
 *
 *   1. Auction  — market state: BALANCED / IMBALANCED are tradable; DEAD or
 *                 missing blocks (no initiative entries in dead auctions).
 *   2. Area     — price is located at a value level: a session POC plus either
 *                 LVNs or an active LVN play.
 *   3. Action   — order-flow aggression: aggression score >= 2.0, an absorption
 *                 side, strong CVD slope, or aggressive prints.
 *
 * There is no ENTER verdict here on purpose: a 3/3 score describes gate
 * alignment, not engine approval. The UI must derive ENTER/MONITOR/SKIP from
 * the streamed `quantDecision.approved` (see ThreeAIndicator) — never from
 * this score alone. A prior version computed its own ENTER verdict from the
 * score, which let the scanner show ENTER while the engine was flat.
 */
export interface ThreeAScore {
  auction: boolean;
  area: boolean;
  action: boolean;
  score: number;
}

export function computeThreeA(amt: AMTAnalysis | null): ThreeAScore {
  if (!amt) {
    return { auction: false, area: false, action: false, score: 0 };
  }

  const state = (amt.marketState || '').toUpperCase();
  const auction = state === 'BALANCED' || state === 'IMBALANCED';

  const poc = Number(amt.poc ?? 0) > 0;
  const hasLvns = Array.isArray(amt.lvns) && amt.lvns.length > 0;
  const hasLvnPlay = !!amt.lvnPlay;
  const area = poc && (hasLvns || hasLvnPlay);

  const aggression = Number(amt.aggression ?? 0) >= THREE_A_CONFIG.aggressionMin;
  const absorption = !!amt.absorptionSide;
  const cvd = Number(amt.cvdSlope ?? 0) >= THREE_A_CONFIG.cvdSlopeMin;
  const prints = Array.isArray(amt.aggressivePrints) && amt.aggressivePrints.length > 0;
  const action = aggression || absorption || cvd || prints;

  const score = Number(auction) + Number(area) + Number(action);
  return { auction, area, action, score };
}
