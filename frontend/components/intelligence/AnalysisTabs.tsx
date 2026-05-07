import React, { useState, useMemo } from 'react';
import { Brain, Activity, Crosshair, TrendingUp, MessageSquare } from 'lucide-react';

export interface AnalysisTab {
  id: string;
  label: string;
  icon: React.ReactNode;
  badge?: string;
  color?: string;
}

export interface AnalysisTabsProps {
  activeTab: string;
  onTabChange: (tabId: string) => void;
  tabs?: AnalysisTab[];
  hasAMTData: boolean;
  marketState?: string;
  aggScore?: number;
}

const defaultTabs: AnalysisTab[] = [
  { id: 'state', label: 'State', icon: <Activity className="w-3.5 h-3.5" />, color: 'blue' },
  { id: 'location', label: 'Location', icon: <Crosshair className="w-3.5 h-3.5" />, color: 'purple' },
  { id: 'aggression', label: 'Aggression', icon: <TrendingUp className="w-3.5 h-3.5" />, color: 'orange' },
  { id: 'metrics', label: 'Metrics', icon: <Brain className="w-3.5 h-3.5" />, color: 'cyan' },
  { id: 'decision', label: 'Decision', icon: <MessageSquare className="w-3.5 h-3.5" />, color: 'green' },
];

const AnalysisTabs: React.FC<AnalysisTabsProps> = ({
  activeTab,
  onTabChange,
  tabs = defaultTabs,
  hasAMTData,
  marketState,
  aggScore,
}) => {
  const [hoveredTab, setHoveredTab] = useState<string | null>(null);

  const getColorClasses = (tabId: string, isActive: boolean, isHovered: boolean) => {
    const base = 'flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all duration-200 cursor-pointer';
    
    if (isActive) {
      return `${base} bg-glassy-bg-elevated text-glassy-text-primary border border-glassy-border-default shadow-sm`;
    }
    if (isHovered) {
      return `${base} bg-glassy-bg-elevated/50 text-glassy-text-secondary border border-glassy-border-subtle`;
    }
    return `${base} text-glassy-text-tertiary hover:text-glassy-text-secondary hover:bg-glassy-bg-elevated/30`;
  };

  const getBadge = (tabId: string): string | null => {
    if (!hasAMTData) return null;
    
    switch (tabId) {
      case 'state':
        return marketState || 'BALANCED';
      case 'aggression':
        return aggScore !== undefined ? `${(aggScore * 100).toFixed(0)}%` : null;
      default:
        return null;
    }
  };

  const badgeColor = (badge: string): string => {
    if (badge === 'IMBALANCED') return 'text-orange-400';
    if (badge === 'TRENDING') return 'text-emerald-400';
    if (badge === 'BALANCED') return 'text-blue-400';
    if (badge?.includes('%')) {
      const val = parseInt(badge);
      return val > 70 ? 'text-emerald-400' : val > 40 ? 'text-orange-400' : 'text-slate-400';
    }
    return 'text-glassy-text-tertiary';
  };

  return (
    <div className="flex items-center gap-1 px-1 py-2 bg-glassy-bg-primary/50 border-b border-glassy-border-subtle">
      {tabs.map((tab) => {
        const isActive = activeTab === tab.id;
        const isHovered = hoveredTab === tab.id;
        const badge = getBadge(tab.id);

        return (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            onMouseEnter={() => setHoveredTab(tab.id)}
            onMouseLeave={() => setHoveredTab(null)}
            className={getColorClasses(tab.id, isActive, isHovered)}
          >
            <span className={isActive ? 'text-glassy-ai-primary' : ''}>{tab.icon}</span>
            <span>{tab.label}</span>
            {badge && (
              <span className={`text-[8px] font-mono ${badgeColor(badge)}`}>
                {badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
};

export default AnalysisTabs;
