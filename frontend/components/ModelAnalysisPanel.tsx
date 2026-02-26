
import React from 'react';
import { AMTAnalysis, Portfolio } from '../types';
import GlassPanel from './GlassPanel';
import { BrainCircuit, Scale, TrendingUp, Wallet, Target, Activity, CheckCircle2, Circle } from 'lucide-react';

interface ModelAnalysisPanelProps {
  analysis: AMTAnalysis | null;
  portfolio: Portfolio | null;
  show: boolean;
}

const ModelAnalysisPanel: React.FC<ModelAnalysisPanelProps> = ({ analysis, portfolio, show }) => {
  if (!show || !analysis) return null;

  const isImbalanced = analysis.marketState === 'IMBALANCED';
  
  // Setup Colors
  const stateColor = isImbalanced ? 'text-blue-400' : 'text-purple-400';
  const aggressionColor = analysis.aggression > 0 ? 'text-emerald-400' : analysis.aggression < 0 ? 'text-red-400' : 'text-gray-400';

  // Open PnL Calculation
  const openPnL = portfolio?.positions.reduce((acc, p) => acc + p.pnl, 0) || 0;
  const pnlColor = openPnL >= 0 ? 'text-emerald-400' : 'text-red-400';

  return (
    <GlassPanel className="w-full p-4 backdrop-blur-3xl bg-[#0f172a]/40 border-white/10 shadow-lg">
      
      {/* HEADER */}
      <div className="flex items-center justify-between mb-4 pb-3 border-b border-white/10">
        <div className="flex items-center gap-2">
            <BrainCircuit className="w-4 h-4 text-blue-400" />
            <div>
                <h2 className="font-bold text-xs tracking-wider text-gray-200 uppercase">Fabio Playbook</h2>
                <p className="text-[8px] text-white/40 font-mono">AMT EXECUTION ENGINE</p>
            </div>
        </div>
        <div className="flex items-center gap-2">
            <div className="text-[9px] bg-blue-500/10 border border-blue-500/20 px-2 py-0.5 rounded text-blue-300 font-mono">
                1X LIVE
            </div>
        </div>
      </div>

      <div className="space-y-4">
        
        {/* ACCOUNT SNAPSHOT */}
        {portfolio && (
            <div className="bg-gradient-to-r from-white/5 to-transparent rounded-xl p-3 border border-white/5">
                <div className="flex justify-between items-end mb-1">
                    <div className="flex items-center gap-1.5 text-white/50 text-[10px] uppercase tracking-wider">
                        <Wallet size={10} /> Equity
                    </div>
                    <span className="font-mono font-bold text-white text-xs">
                        ₹{portfolio.equity.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                    </span>
                </div>
                <div className="flex justify-between items-end">
                    <div className="flex items-center gap-1.5 text-white/50 text-[10px] uppercase tracking-wider">
                        <Activity size={10} /> Open PnL
                    </div>
                    <span className={`font-mono font-bold text-xs ${pnlColor}`}>
                        {openPnL >= 0 ? '+' : ''}${openPnL.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </span>
                </div>
            </div>
        )}

        {/* PLAYBOOK STEPS */}
        <div className="space-y-3">
            
            {/* STEP 1: MARKET STATE */}
            <div className="bg-black/20 p-3 rounded-lg border-l-2 border-blue-500/50">
                <div className="flex justify-between items-center mb-2">
                    <span className="text-[10px] text-white/40 uppercase font-bold tracking-widest">01. STATE</span>
                    {isImbalanced ? <TrendingUp size={14} className={stateColor} /> : <Scale size={14} className={stateColor} />}
                </div>
                <div className="flex items-center justify-between">
                    <span className={`font-bold text-xs ${stateColor}`}>
                        {analysis.marketState}
                    </span>
                    <span className="text-[9px] text-white/50 font-mono">
                        {isImbalanced ? 'Trend Mode' : 'Range Mode'}
                    </span>
                </div>
            </div>

            {/* STEP 2: LOCATION (KEY LEVELS) */}
            <div className="bg-black/20 p-3 rounded-lg border-l-2 border-yellow-500/50">
                <div className="flex justify-between items-center mb-2">
                    <span className="text-[10px] text-white/40 uppercase font-bold tracking-widest">02. LOCATION</span>
                    <Target size={14} className="text-yellow-400" />
                </div>
                <div className="grid grid-cols-2 gap-2 text-[10px]">
                    <div>
                        <span className="text-white/30 block">VA High</span>
                        <span className="font-mono text-white/80">{analysis.valueAreaHigh?.toLocaleString() || '---'}</span>
                    </div>
                    <div className="text-right">
                        <span className="text-white/30 block">VA Low</span>
                        <span className="font-mono text-white/80">{analysis.valueAreaLow?.toLocaleString() || '---'}</span>
                    </div>
                    <div className="col-span-2 border-t border-white/5 pt-1 flex justify-between">
                         <span className="text-yellow-400/70 font-bold">POC</span>
                         <span className="font-mono text-yellow-400">{analysis.poc?.toLocaleString() || '---'}</span>
                    </div>
                </div>
            </div>

            {/* STEP 3: AGGRESSION (ORDER FLOW) */}
            <div className={`bg-black/20 p-3 rounded-lg border-l-2 ${analysis.aggression > 0 ? 'border-emerald-500/50' : 'border-red-500/50'}`}>
                <div className="flex justify-between items-center mb-2">
                    <span className="text-[10px] text-white/40 uppercase font-bold tracking-widest">03. AGGRESSION</span>
                    <Activity size={14} className={aggressionColor} />
                </div>
                 <div className="w-full bg-white/10 h-1.5 rounded-full overflow-hidden mb-1">
                     <div 
                        className={`h-full transition-all duration-500 ${analysis.aggression > 0 ? 'bg-emerald-500' : 'bg-red-500'}`} 
                        style={{ width: `${Math.min(100, Math.abs(analysis.aggression) * 100)}%` }} 
                     />
                 </div>
                 <div className="flex justify-between text-[10px] font-mono">
                     <span className="text-white/50">Delta Score</span>
                     <span className={aggressionColor}>{analysis.aggression.toFixed(2)}</span>
                 </div>
            </div>

        </div>

        {/* ACTIVE SIGNAL STATUS */}
        <div className={`mt-2 p-3 rounded-lg border flex items-start gap-3 transition-colors ${analysis.setup ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-white/5 border-white/5'}`}>
             {analysis.setup ? <CheckCircle2 className="text-emerald-400 mt-0.5" size={16} /> : <Circle className="text-white/20 mt-0.5" size={16} />}
             <div>
                 <h3 className={`text-[10px] font-bold uppercase ${analysis.setup ? 'text-white' : 'text-white/40'}`}>
                     {analysis.setup ? `${analysis.setup.replace('_', ' ')} ACTIVE` : 'WAITING FOR SETUP'}
                 </h3>
                 <p className="text-[9px] text-white/50 mt-1 leading-tight">
                     {analysis.setup 
                        ? `Conditions met. Trade executed.`
                        : "Monitoring market state and order flow for high probability entry."}
                 </p>
             </div>
        </div>

      </div>
    </GlassPanel>
  );
};

export default ModelAnalysisPanel;
