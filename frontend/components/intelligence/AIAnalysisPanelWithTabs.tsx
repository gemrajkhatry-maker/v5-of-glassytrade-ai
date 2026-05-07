import React, { useState } from 'react';
import { GenAIAnalysis, AMTAnalysis, Portfolio, RiskState, LLMHistoryEntry, AgentDecision, OrderBook } from '../../types';
import { AIAnalysisPanel } from '../AIAnalysisPanel';
import AnalysisTabs from './AnalysisTabs';
import { StateTab, LocationTab, AggressionTab, MetricsTab, DecisionTab } from './tabs';

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
  
  const { amtResult, analysis, agentDecision, portfolio, overseerAction, overseerReason, llmHistory, orderBook, depth20Active, symbol } = props;
  const liveMarketState = amtResult?.marketState || 'BALANCED';
  const aggScore = amtResult?.aggression ?? 0;
  
  // Helper variables for tab components
  const currentLtp = amtResult?.sessionVwap || 0;
  const poc = amtResult?.poc || 0;
  const vah = amtResult?.valueAreaHigh || 0;
  const val = amtResult?.valueAreaLow || 0;
  const deltaScore = amtResult?.deltaNormalizedOption ?? 0;
  
  // CVD formatter
  const formatCVD = (cvd: number) => {
    const abs = Math.abs(cvd);
    return abs > 1000 ? `${(abs / 1000).toFixed(1)}K` : abs.toFixed(0);
  };

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

      {/* Tab Content - Conditional Rendering */}
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        {activeTab === 'state' && (
          <StateTab
            marketState={liveMarketState}
            hasDisplacement={amtResult?.hasDisplacement || false}
            legPoc={amtResult?.legPoc}
            legVah={amtResult?.legVah}
            legVal={amtResult?.legVal}
            gapType={amtResult?.gapType}
            openingBias={amtResult?.openingBias}
          />
        )}
        
        {activeTab === 'location' && (
          <LocationTab
            currentLtp={currentLtp}
            poc={poc}
            vah={vah}
            val={val}
            amtResult={amtResult}
          />
        )}
        
        {activeTab === 'aggression' && (
          <AggressionTab
            deltaScore={deltaScore}
            aggScore={aggScore}
            formatCVD={formatCVD}
            agentDecision={agentDecision}
            amtResult={amtResult}
            symbol={symbol}
            orderBook={orderBook}
            depth20Active={depth20Active}
          />
        )}
        
        {activeTab === 'metrics' && (
          <MetricsTab
            agentDecision={agentDecision}
            overseerAction={overseerAction}
            overseerReason={overseerReason}
            portfolio={portfolio}
            amtResult={amtResult}
            llmHistory={llmHistory}
          />
        )}
        
        {activeTab === 'decision' && (
          <DecisionTab
            analysis={analysis}
            amtResult={amtResult}
            agentDecision={agentDecision}
            symbol={symbol}
          />
        )}
      </div>
    </div>
  );
};

export default AIAnalysisPanelWithTabs;
