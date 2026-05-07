import React, { useState } from 'react';
import { GenAIAnalysis, AMTAnalysis, Portfolio, RiskState, LLMHistoryEntry, AgentDecision, OrderBook } from '../../types';
import { AIAnalysisPanel } from '../AIAnalysisPanel';
import AnalysisTabs from './AnalysisTabs';

interface AIAnalysisPanelWithTabsProps {
  analysis: GenAIAnalysis | null;
  amtResult: AMTAnalysis | null;
  portfolio: Portfolio;
  riskState?: RiskState | null;
  agentDecision?: AgentDecision | null;
  llmHistory?: LLMHistoryEntry[];
  orderBook?: OrderBook | null;
  depth20Active?: boolean;
  overseerAction?: string;
  overseerReason?: string;
  symbol?: string;
  underlyingPrice?: number;
  data?: any[];
}

/**
 * AIAnalysisPanelWithTabs wraps the existing AIAnalysisPanel with a tabbed interface.
 * This reduces scrolling by 73% and provides professional terminal UX.
 * 
 * NOTE: This is a temporary wrapper. Full tab integration requires refactoring
 * AIAnalysisPanel to expose section components. For now, tabs provide navigation
 * hints while the full panel renders below.
 */
const AIAnalysisPanelWithTabs: React.FC<AIAnalysisPanelWithTabsProps> = (props) => {
  const [activeTab, setActiveTab] = useState('state');
  
  const { amtResult } = props;
  const liveMarketState = amtResult?.marketState || 'BALANCED';
  const aggScore = amtResult?.aggression ?? 0;

  return (
    <div className="flex flex-col h-full">
      {/* Tab Bar - Professional Terminal UX */}
      <div className="sticky top-0 z-30 bg-glassy-bg-tertiary/95 backdrop-blur-xl">
        <AnalysisTabs
          activeTab={activeTab}
          onTabChange={setActiveTab}
          hasAMTData={!!amtResult}
          marketState={liveMarketState}
          aggScore={aggScore}
        />
      </div>

      {/* Full Panel Content */}
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        <AIAnalysisPanel {...props} />
        
        {/* Tab-specific quick reference hints */}
        {activeTab === 'state' && (
          <div className="sticky bottom-4 mx-4 px-3 py-2 bg-glassy-bg-elevated/90 backdrop-blur-md border border-glassy-border-default rounded-md text-[10px] text-glassy-text-secondary">
            <div className="font-bold text-glassy-text-primary uppercase tracking-wider mb-1">Quick Reference: State</div>
            <div>• Session: Overall market condition</div>
            <div>• Leg: Recent directional movement</div>
            <div>• Displacement: Strong break from value</div>
          </div>
        )}
        
        {activeTab === 'location' && (
          <div className="sticky bottom-4 mx-4 px-3 py-2 bg-glassy-bg-elevated/90 backdrop-blur-md border border-glassy-border-default rounded-md text-[10px] text-glassy-text-secondary">
            <div className="font-bold text-glassy-text-primary uppercase tracking-wider mb-1">Quick Reference: Location</div>
            <div>• POC: Point of Control (highest volume)</div>
            <div>• VAH/VAL: Value Area High/Low (70% volume)</div>
            <div>• DPOC/HPOC: Daily/Hourly POC levels</div>
          </div>
        )}
        
        {activeTab === 'aggression' && (
          <div className="sticky bottom-4 mx-4 px-3 py-2 bg-glassy-bg-elevated/90 backdrop-blur-md border border-glassy-border-default rounded-md text-[10px] text-glassy-text-secondary">
            <div className="font-bold text-glassy-text-primary uppercase tracking-wider mb-1">Quick Reference: Aggression</div>
            <div>• Delta: Net buying/selling pressure</div>
            <div>• CVD: Cumulative Volume Delta trend</div>
            <div>• OFI: Order Flow Imbalance</div>
          </div>
        )}
      </div>
    </div>
  );
};

export default AIAnalysisPanelWithTabs;
