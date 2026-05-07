import React from 'react';
import { Activity, Layers } from 'lucide-react';

interface AggressionTabProps {
  deltaScore: number;
  aggScore: number;
  formatCVD: (cvd: number) => string;
  agentDecision?: {
    probability: number;
  } | null;
  amtResult: {
    ofi?: number;
    cvdSlope?: number;
    cvdDivergence?: string;
    deltaNormalizedOption?: number;
    breakDirection?: string;
    sessionVwap?: number;
    valueAreaHigh?: number;
    valueAreaLow?: number;
    balanceRatio?: number;
    profileShape?: string;
    profileType?: string;
  };
  symbol?: string;
  orderBook?: {
    bids?: Array<{ price: number }>;
    asks?: Array<{ price: number }>;
  } | null;
  depth20Active?: boolean;
}

/**
 * AggressionTab displays volume aggression and market metrics:
 * - Delta Score with progress bar
 * - OFI (Order Flow Imbalance)
 * - CVD Slope with sparkline
 * - Aggression divergence detection
 * - Balance ratio (price location in value area)
 * - Profile shape and market structure
 */
const AggressionTab: React.FC<AggressionTabProps> = ({
  deltaScore,
  aggScore,
  formatCVD,
  agentDecision,
  amtResult,
  symbol,
  orderBook,
  depth20Active,
}) => {
  return (
    <div className="flex flex-col gap-4">
      {/* Delta Score Section */}
      <div className="flex flex-col gap-2">
        <div className="flex justify-between items-center text-[10px] text-glassy-text-tertiary uppercase tracking-widest">
          <span>Volume Aggression</span>
          <Activity className="w-3 h-3 hover:text-glassy-text-secondary transition-colors" />
        </div>
        <div className="p-3 rounded-md bg-glassy-bg-elevated/50 border border-glassy-border-subtle">
          <div className="flex justify-between items-end mb-2">
            <div className="flex flex-col">
              <span className="text-[10px] text-glassy-text-secondary mb-0.5">Delta Score <span className="text-[8px] text-glassy-text-disabled">(norm)</span></span>
              <span className={`text-[9px] font-bold tracking-wider ${Math.abs(deltaScore) > 0.05 && aggScore > 0.1 ? (deltaScore > 0 ? 'text-glassy-bull-primary' : 'text-glassy-bear-primary') : 'text-glassy-text-disabled'}`}>
                {Math.abs(deltaScore) > 0.05 && aggScore > 0.1 ? (deltaScore > 0 ? '[BULLS IN CONTROL]' : '[BEARS IN CONTROL]') : '[DELTA NEUTRAL / NEGLIGIBLE]'}
              </span>
            </div>
            <div className="flex flex-col items-end gap-0.5">
              <span className={`text-xs font-mono font-bold tabular-nums ${deltaScore > 0 ? 'text-glassy-bull-primary' : deltaScore < 0 ? 'text-glassy-bear-primary' : 'text-glassy-text-disabled'}`}>
                {deltaScore > 0 ? '+' : ''}{deltaScore.toFixed(2)}
              </span>
              {agentDecision && (() => {
                const isDeltaNeutral = Math.abs(deltaScore) < 0.05;
                const deltaConfidence = isDeltaNeutral ? 50 : Math.min(100, Math.abs(deltaScore) * 100);
                const confColor = isDeltaNeutral 
                  ? 'text-glassy-warning' 
                  : agentDecision.probability >= 0.6 
                    ? 'text-glassy-bull-primary' 
                    : agentDecision.probability > 0.45 
                      ? 'text-glassy-warning' 
                      : agentDecision.probability > 0 
                        ? 'text-glassy-bear-primary' 
                        : 'text-glassy-text-disabled';
                
                return (
                  <span className={`text-[9px] font-mono font-bold tabular-nums ${confColor}`}>
                    {isDeltaNeutral ? '~50%' : `${deltaConfidence.toFixed(1)}%`}
                  </span>
                );
              })()}
            </div>
          </div>
          {/* Progress Bar */}
          <div className="h-1 bg-glassy-text-disabled/20 rounded-full overflow-hidden flex relative">
            <div className="absolute top-0 left-1/2 w-px h-full bg-glassy-text-disabled/30 z-10" />
            <div className={`h-full absolute transition-all duration-500 rounded-full`} style={{
              width: `${Math.min(Math.abs(deltaScore) * 50, 50)}%`,
              left: deltaScore > 0 ? '50%' : `${50 - Math.min(Math.abs(deltaScore) * 50, 50)}%`,
              backgroundColor: deltaScore > 0 ? '#00c896' : '#ff4757'
            }}></div>
          </div>
          {/* Aggression indicator */}
          <div className="flex justify-between text-[9px] mt-1.5 pt-1 border-t border-glassy-border-subtle">
            <span className="text-glassy-text-tertiary">Aggression</span>
            <span className={`font-mono font-bold tabular-nums ${aggScore > 0 ? 'text-glassy-bull-primary' : aggScore < 0 ? 'text-glassy-bear-primary' : 'text-glassy-text-disabled'}`}>
              {aggScore.toFixed(2)}{deltaScore < -0.05 ? ' (Bearish)' : deltaScore > 0.05 ? ' (Bullish)' : ''}
            </span>
          </div>
        </div>
      </div>

      {/* Market Metrics Section */}
      <div className="flex flex-col gap-2">
        <div className="flex justify-between items-center text-[10px] text-glassy-text-tertiary uppercase tracking-widest">
          <span>Market Metrics</span>
        </div>
        <div className="p-3 rounded-md bg-glassy-bg-elevated/50 border border-glassy-border-subtle space-y-2">
          {/* OFI Bar */}
          <div>
            <div className="flex justify-between mb-1">
              <span className="text-[10px] text-glassy-text-tertiary">OFI <span className="text-[8px] text-glassy-text-disabled">(norm)</span></span>
              <div className="flex items-center gap-1.5">
                <span className={`text-[10px] ${(amtResult?.ofi ?? 0) > 0 ? 'text-glassy-bull-primary' : (amtResult?.ofi ?? 0) < 0 ? 'text-glassy-bear-primary' : 'text-glassy-text-disabled'}`}>
                  {(amtResult?.ofi ?? 0) > 0 ? '╱╲↗' : (amtResult?.ofi ?? 0) < 0 ? '╲╱↘' : '—'}
                </span>
                <span className={`text-[10px] font-mono font-bold tabular-nums ${(amtResult?.ofi ?? 0) > 0 ? 'text-glassy-bull-primary' : (amtResult?.ofi ?? 0) < 0 ? 'text-glassy-bear-primary' : 'text-glassy-text-disabled'}`}>
                  {(amtResult?.ofi ?? 0) > 0 ? '+' : ''}{(amtResult?.ofi ?? 0).toFixed(3)}
                </span>
              </div>
            </div>
            <div className="h-1.5 bg-glassy-text-disabled/20 rounded-full overflow-hidden relative">
              <div className="absolute top-0 left-1/2 w-px h-full bg-glassy-text-disabled/30" />
              {(amtResult?.ofi ?? 0) !== 0 && (
                <div className="absolute top-0 h-full rounded-full transition-all duration-300" style={{
                  left: (amtResult?.ofi ?? 0) > 0 ? '50%' : `${50 + (amtResult?.ofi ?? 0) * 50}%`,
                  width: `${Math.min(Math.abs(amtResult?.ofi ?? 0) * 50, 50)}%`,
                  backgroundColor: (amtResult?.ofi ?? 0) > 0 ? '#00c896' : '#ff4757',
                  opacity: 0.7,
                }} />
              )}
            </div>
          </div>

          {/* CVD Slope Bar */}
          <div>
            <div className="flex justify-between mb-1">
              <span className="text-[10px] text-glassy-text-tertiary">CVD Slope</span>
              <div className="flex items-center gap-1.5">
                <span className={`text-[10px] ${(amtResult?.cvdSlope ?? 0) > 0 ? 'text-glassy-bull-primary' : (amtResult?.cvdSlope ?? 0) < 0 ? 'text-glassy-bear-primary' : 'text-glassy-text-disabled'}`}>
                  {(amtResult?.cvdSlope ?? 0) > 0 ? '╱╲↗' : (amtResult?.cvdSlope ?? 0) < 0 ? '╲╱↘' : '—'}
                </span>
                <span className={`text-[10px] font-mono font-bold tabular-nums ${(amtResult?.cvdSlope ?? 0) > 0 ? 'text-glassy-bull-primary' : (amtResult?.cvdSlope ?? 0) < 0 ? 'text-glassy-bear-primary' : 'text-glassy-text-disabled'}`}>
                  {(amtResult?.cvdSlope ?? 0) > 0 ? '+' : ''}{formatCVD(amtResult?.cvdSlope ?? 0)}
                  {amtResult?.cvdDivergence ? ` (${amtResult.cvdDivergence.replace('_DIV', '')})` : ''}
                  {(amtResult?.cvdSlope ?? 0) > 0.01 ? ' BULLISH' : (amtResult?.cvdSlope ?? 0) < -0.01 ? ' BEARISH' : ' FLAT'}
                </span>
              </div>
            </div>
            <div className="h-1.5 bg-glassy-text-disabled/20 rounded-full overflow-hidden relative">
              <div className="absolute top-0 left-1/2 w-px h-full bg-glassy-text-disabled/30" />
              {(() => {
                const cvd = amtResult?.cvdSlope ?? 0;
                const norm = Math.min(Math.abs(cvd) / 100, 1);
                return cvd !== 0 ? (
                  <div className="absolute top-0 h-full rounded-full transition-all duration-300" style={{
                    left: cvd > 0 ? '50%' : `${50 - norm * 50}%`,
                    width: `${norm * 50}%`,
                    backgroundColor: cvd > 0 ? '#4ade80' : '#f87171',
                    opacity: 0.7,
                  }} />
                ) : null;
              })()}
            </div>
          </div>

          {/* Balance / Price Location */}
          <div>
            <div className="flex justify-between mb-1">
              <span className="text-[10px] text-white/40">Balance</span>
              {(() => {
                const ltp = amtResult?.sessionVwap ?? 0;
                const vah = amtResult?.valueAreaHigh ?? 0;
                const val = amtResult?.valueAreaLow ?? 0;
                const ratio = (amtResult?.balanceRatio ?? 0) * 100;
                if (ltp > 0 && vah > 0 && ltp > vah) {
                  return <span className="text-[10px] font-mono font-bold text-orange-400">0% in VA (Above ↑)</span>;
                } else if (ltp > 0 && val > 0 && ltp < val) {
                  return <span className="text-[10px] font-mono font-bold text-red-400">0% in VA (Below ↓)</span>;
                } else if (ratio >= 50 && ratio <= 70) {
                  return <span className="text-[10px] font-mono font-bold text-yellow-400">{ratio.toFixed(0)}% in VA (TRANSITIONING)</span>;
                } else {
                  return <span className="text-[10px] font-mono font-bold text-blue-300">{ratio.toFixed(0)}% in VA</span>;
                }
              })()}
            </div>
            <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
              <div className="h-full rounded-full transition-all duration-300" style={{
                width: `${(amtResult?.balanceRatio ?? 0) * 100}%`,
                backgroundColor: '#60a5fa',
                opacity: 0.6,
              }} />
            </div>
          </div>

          {/* Profile Shape + Spread + Depth row */}
          <div className="flex justify-between items-center pt-1 border-t border-white/5">
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-white/40">Shape</span>
              <span className={`text-[10px] font-mono font-bold px-1.5 py-0.5 rounded ${amtResult?.profileShape === 'B' ? 'bg-purple-500/20 text-purple-400' :
                amtResult?.profileShape === 'P' ? 'bg-red-500/20 text-red-400' :
                amtResult?.profileShape === 'b' ? 'bg-green-500/20 text-green-400' :
                'bg-white/10 text-white/40'
                }`}>
                {amtResult?.profileShape === 'B' ? 'B Bimodal' :
                amtResult?.profileShape === 'P' ? 'P Top-heavy' :
                amtResult?.profileShape === 'b' ? 'b Bottom-heavy' :
                amtResult?.profileShape === 'D' ? 'D Balanced' : '—'}
              </span>
              <span className="text-[8px] text-white/30">
                ({amtResult?.profileType || 'Session'})
              </span>
            </div>
            <div className="flex items-center gap-2">
              {(() => {
                const bestBid = orderBook?.bids?.[0]?.price ?? 0;
                const bestAsk = orderBook?.asks?.[0]?.price ?? 0;
                const mid = (bestBid + bestAsk) / 2;
                const spreadBps = mid > 0 ? ((bestAsk - bestBid) / mid * 10000) : 0;
                return bestBid > 0 ? (
                  <span className={`text-[10px] font-mono ${spreadBps <= 5 ? 'text-green-400' : spreadBps <= 15 ? 'text-yellow-400' : 'text-red-400'}`}>
                    {spreadBps.toFixed(1)} bps
                  </span>
                ) : <span className="text-[10px] text-white/20">—</span>;
              })()}
              <span title="Order Book Depth" className={`text-[9px] font-mono px-1 py-0.5 rounded ${depth20Active ? 'bg-green-500/20 text-green-400' : 'bg-white/5 text-white/20'}`}>
                {depth20Active ? 'Depth-20' : 'Depth-5'}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AggressionTab;
