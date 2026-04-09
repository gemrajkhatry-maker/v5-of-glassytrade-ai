
import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import ChartScene from './components/ChartScene';
import { LiveOpportunityCard } from './components/ai';
import { AIAnalysisPanel } from './components/AIAnalysisPanel';
import MarketSidebar from './components/MarketSidebar';
import ErrorBoundary from './components/ErrorBoundary';
import { DEFAULT_CONFIG } from './constants';
import { ChartConfig, ChartMode, AgentDecision } from './types';
import { X, Activity, Loader2, PanelsTopLeft, Sparkles, Brain, BarChart2, Grid, BookOpen, Eye, TrendingUp } from 'lucide-react';
import { useServerTradingSystem as useTradingSystem } from './hooks/useServerTradingSystem';
import JournalPage from './components/JournalPage';

const simpleId = () => Date.now().toString(36) + Math.random().toString(36).substr(2);

function App() {
    // 1. UI State
    const [config, setConfig] = useState<ChartConfig>(DEFAULT_CONFIG);
    const [chartMode, setChartMode] = useState<ChartMode>('STANDARD');
    const [showControls, setShowControls] = useState(false);
    const [sidebarOpen, setSidebarOpen] = useState(true);
    const [rightSidebarOpen, setRightSidebarOpen] = useState(true);
    const [currentPage, setCurrentPage] = useState<'trading' | 'journal'>('trading');
    // Draggable overseer box
    const [overseerPos, setOverseerPos] = useState({ x: -1, y: 16 }); // -1 = auto right
    const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null);
    const overseerBoxRef = useRef<HTMLDivElement>(null);
    // Track active drag listeners for cleanup on unmount
    const dragCleanupRef = useRef<(() => void) | null>(null);
    const onOverseerMouseDown = useCallback((e: React.MouseEvent) => {
        e.preventDefault();
        const box = overseerBoxRef.current;
        if (!box) return;
        const rect = box.getBoundingClientRect();
        const parentRect = box.parentElement?.getBoundingClientRect();
        if (!parentRect) return;
        const curX = rect.left - parentRect.left;
        const curY = rect.top - parentRect.top;
        dragRef.current = { startX: e.clientX, startY: e.clientY, origX: curX, origY: curY };
        const onMove = (ev: MouseEvent) => {
            if (!dragRef.current) return;
            setOverseerPos({
                x: dragRef.current.origX + (ev.clientX - dragRef.current.startX),
                y: dragRef.current.origY + (ev.clientY - dragRef.current.startY),
            });
        };
        const cleanup = () => {
            dragRef.current = null;
            window.removeEventListener('mousemove', onMove);
            window.removeEventListener('mouseup', cleanup);
            dragCleanupRef.current = null;
        };
        dragCleanupRef.current = cleanup;
        window.addEventListener('mousemove', onMove);
        window.addEventListener('mouseup', cleanup);
    }, []);
    // Clean up drag listeners on unmount to prevent memory leaks
    useEffect(() => {
        return () => { dragCleanupRef.current?.(); };
    }, []);

    // 2. Server-driven trading system (all logic on backend)
    const {
        instruments,
        activeSymbol,
        setActiveSymbol,
        activeInstrument,
        activeFootprint,
        connected,
        connectionStatus,
        tickBus,
    } = useTradingSystem(config);

    // --- Handlers ---

    /** Stable callback for symbol selection, avoids re-renders of MarketSidebar */
    const handleSymbolSelect = useCallback((symbol: string) => {
        setActiveSymbol(symbol);
    }, [setActiveSymbol]);

    // Find the best live opportunity across all scanned instruments
    const bestOpportunity = useMemo(() => {
        let best: { symbol: string, agentDecision: AgentDecision, ltp: number } | null = null;
        Object.entries(instruments).forEach(([sym, data]) => {
            const dec = data.agentDecision;
            if (dec && dec.timing === 'ENTER_NOW') {
                if (!best || dec.probability > best.agentDecision.probability) {
                    const ltp = data.data && data.data.length > 0 ? data.data[data.data.length - 1].close : 0;
                    best = { symbol: sym, agentDecision: dec, ltp };
                }
            }
        });
        return best;
    }, [instruments]);

    const effectiveConfig = useMemo<ChartConfig>(() => ({
        ...config,
        symbol: activeInstrument?.symbol || config.symbol,
    }), [config, activeInstrument?.symbol]);

    // --- Rendering ---

    if (currentPage === 'journal') {
        return <ErrorBoundary name="Journal"><JournalPage onBack={() => setCurrentPage('trading')} /></ErrorBoundary>;
    }

    if (!activeInstrument) {
        return (
            <div className="w-screen h-screen bg-slate-900 flex flex-col items-center justify-center text-white space-y-4">
                <Loader2 className="w-12 h-12 animate-spin text-purple-500" />
                <div className="text-center">
                    <h2 className="text-xl font-bold">Connecting to Backend</h2>
                    <p className="text-sm text-white/50">Waiting for market data stream...</p>
                </div>
            </div>
        );
    }

    return (
        <div className="relative w-screen h-screen overflow-hidden bg-slate-900 flex">

            {/* Connection status banner */}
            {!connected && (
                <div className="absolute top-0 left-0 right-0 z-50 bg-red-900/90 text-red-200 text-xs text-center py-1 px-4">
                    {connectionStatus || 'Disconnected from server'}
                </div>
            )}

            {/* LEFT: Sidebar (Market Scanner) */}
            <div className={`
          absolute left-0 top-0 h-full z-20 transition-all duration-300
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}
      `}>
                <ErrorBoundary name="Sidebar">
                    <MarketSidebar
                        instruments={instruments}
                        activeSymbol={activeSymbol}
                        onSelect={handleSymbolSelect}
                    />
                </ErrorBoundary>
            </div>

            {/* CENTER: Main Content */}
            <div className={`
        flex-1 relative h-full transition-all duration-300 flex flex-col
        ${sidebarOpen ? 'ml-[360px]' : 'ml-0'}
        ${rightSidebarOpen ? 'mr-80' : 'mr-0'}
      `}>

                {/* Chart Layer */}
                <div className="absolute inset-0 z-0">
                    <ErrorBoundary name="Chart">
                        {/* Instance 1: Standard Candles */}
                        <ChartScene
                            key={`standard-${activeInstrument.symbol}`}
                            data={activeInstrument.data} // Used for initial mount/history
                            tickBus={tickBus}            // Realtime data feed without React renders
                            symbol={activeInstrument.symbol}
                            predictions={activeInstrument.predictions}
                            config={effectiveConfig}
                            positions={activeInstrument.portfolio.positions}
                            closedTrades={activeInstrument.portfolio.closedTrades}
                            amtAnalysis={activeInstrument.amtAnalysis}
                            mode="STANDARD"
                            isHidden={chartMode !== 'STANDARD'}
                            footprintData={null}
                            cumulativeDeltas={[]}
                        />
                        {/* Instance 2: Footprint */}
                        <ChartScene
                            key={`footprint-${activeInstrument.symbol}`}
                            data={activeInstrument.data}
                            tickBus={tickBus}
                            symbol={activeInstrument.symbol}
                            predictions={activeInstrument.predictions}
                            config={effectiveConfig}
                            positions={activeInstrument.portfolio.positions}
                            closedTrades={activeInstrument.portfolio.closedTrades}
                            amtAnalysis={activeInstrument.amtAnalysis}
                            mode="FOOTPRINT"
                            isHidden={chartMode !== 'FOOTPRINT'}
                            footprintData={activeFootprint.data}
                            cumulativeDeltas={activeFootprint.cumulativeDeltas}
                        />
                        {/* Instance 3: Range Bars */}
                        <ChartScene
                            key={`range-${activeInstrument.symbol}`}
                            data={activeInstrument.data}
                            tickBus={tickBus}
                            symbol={activeInstrument.symbol}
                            predictions={activeInstrument.predictions}
                            config={effectiveConfig}
                            positions={activeInstrument.portfolio.positions}
                            closedTrades={activeInstrument.portfolio.closedTrades}
                            amtAnalysis={activeInstrument.amtAnalysis}
                            mode="RANGE"
                            isHidden={chartMode !== 'RANGE'}
                            footprintData={null}
                            cumulativeDeltas={[]}
                            rangeBarData={activeInstrument.rangeBars ?? null}
                        />
                    </ErrorBoundary>
                </div>

                {/* Overlay UI Layer */}
                <div className="absolute inset-0 z-10 pointer-events-none p-4 flex flex-col justify-between">

                    {/* Top Bar Area */}
                    <div className="flex justify-between items-start pointer-events-auto">
                        {/* Left Toggle (Scanner) & Chart Controls */}
                        <div className="flex items-start gap-2">
                            {!sidebarOpen && (
                                <button onClick={() => setSidebarOpen(true)} className="p-2 bg-white/5 backdrop-blur rounded-lg text-white hover:bg-white/10 transition-colors">
                                    <Activity size={20} />
                                </button>
                            )}

                            {/* CHART MODE TABS (Pills) */}
                            <div className="flex bg-white/10 backdrop-blur-md rounded-full p-1 gap-1 shadow-inner border border-white/10">
                                <button
                                    onClick={() => setChartMode('STANDARD')}
                                    className={`px-3 py-1.5 rounded-full text-xs font-bold transition-all ${chartMode === 'STANDARD' ? 'bg-white text-black shadow-md' : 'text-white/40 hover:text-white hover:bg-white/5'}`}
                                >
                                    <span className="flex items-center gap-1.5">
                                        <BarChart2 size={14} /> Candles
                                    </span>
                                </button>
                                <button
                                    onClick={() => setChartMode('FOOTPRINT')}
                                    className={`px-3 py-1.5 rounded-full text-xs font-bold transition-all ${chartMode === 'FOOTPRINT' ? 'bg-white text-black shadow-md' : 'text-white/40 hover:text-white hover:bg-white/5'}`}
                                >
                                    <span className="flex items-center gap-1.5">
                                        <Grid size={14} /> Footprint
                                    </span>
                                </button>
                                <button
                                    onClick={() => setChartMode('RANGE')}
                                    className={`px-3 py-1.5 rounded-full text-xs font-bold transition-all ${chartMode === 'RANGE' ? 'bg-white text-black shadow-md' : 'text-white/40 hover:text-white hover:bg-white/5'}`}
                                >
                                    <span className="flex items-center gap-1.5">
                                        <TrendingUp size={14} /> Range
                                    </span>
                                </button>
                            </div>

                            {/* Dual Volume Profile Tabs (Pills) */}
                            <div className="flex bg-white/10 backdrop-blur-md rounded-full p-1 gap-1 shadow-inner border border-white/10 ml-2">
                                {([
                                    { key: 'session', label: 'Session' },
                                    { key: 'leg', label: 'Leg' },
                                    { key: 'combined', label: 'Combined' },
                                    { key: 'off', label: 'Off' },
                                ] as const).map(({ key, label }) => (
                                    <button
                                        key={key}
                                        onClick={() => setConfig(s => ({ ...s, vpMode: key, showVolumeProfile: key !== 'off' }))}
                                        className={`px-3 py-1.5 rounded-full text-xs font-bold transition-all ${config.vpMode === key
                                            ? 'bg-blue-500 text-white shadow-md shadow-blue-500/20'
                                            : 'text-white/40 hover:text-white hover:bg-white/5'
                                            }`}
                                    >
                                        {label}
                                    </button>
                                ))}
                            </div>
                            
                            {/* Breadcrumb Info Mode */}
                            <div className="flex items-center bg-black/40 backdrop-blur rounded-full px-3 py-1.5 text-[10px] font-bold tracking-wider text-white/50 border border-white/10 ml-2">
                                {chartMode === 'STANDARD' ? 'Standard Candles' : chartMode === 'FOOTPRINT' ? 'Footprint' : 'Range'} 
                                <span className="mx-2 text-white/20">→</span> 
                                {config.vpMode === 'off' ? 'No Profile' :
                                 config.vpMode === 'session' ? 'Session Profile' :
                                 config.vpMode === 'leg' ? 'Leg Profile' : 'Combined Profile'}
                            </div>
                        </div>

                        {/* Top Bar Status Pin */}
                        <div className="absolute top-14 left-0 right-0 pointer-events-none flex justify-center">
                            {(() => {
                                const genAI = activeInstrument.genAIAnalysis;
                                const amtResult = activeInstrument.amtAnalysis;
                                const isDead = genAI?.rationale?.includes('DEAD') || genAI?.rawOutput?.includes('QUANT_DEAD_MARKET');
                                const volMsg = amtResult?.aggression && amtResult.aggression < 0.2 ? 'Vol < 5% avg' : 'Vol OK';
                                
                                return (
                                    <div className="pointer-events-auto flex items-center bg-[#0f172a]/95 backdrop-blur-xl border border-white/10 rounded-lg shadow-2xl overflow-hidden">
                                        <div className="px-4 py-2 border-r border-white/10 flex items-center gap-2">
                                            <Brain className="w-3.5 h-3.5 text-blue-400" />
                                            <span className="text-[10px] font-bold text-white/80 uppercase tracking-widest">
                                                MODEL: {genAI?.direction && genAI.direction !== 'FLAT' ? `ENTRY (${genAI.direction})` : isDead ? 'SLEEPING' : 'MONITORING'}
                                            </span>
                                        </div>
                                        <div className={`px-4 py-2 border-r border-white/10 flex items-center gap-2 font-mono text-[10px] font-bold ${isDead ? 'bg-red-500/20 text-red-400' : 'bg-green-500/10 text-emerald-400'}`}>
                                            {isDead ? (
                                                 <><div className="w-1.5 h-1.5 bg-red-500 rounded-full" /> <span>DEAD MARKET</span></>
                                            ) : (
                                                 <><div className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse" /> <span>LIVE SCANNING</span></>
                                            )}
                                        </div>
                                        <div className={`px-4 py-2 font-mono text-[10px] ${amtResult?.aggression && amtResult.aggression < 0.2 ? 'text-white/40' : 'text-blue-300'}`}>
                                            {volMsg}
                                        </div>
                                    </div>
                                );
                            })()}
                        </div>

                        {/* Right Toggle (Analysis) + Chat Toggle */}
                        <div className="flex items-start gap-3">
                            <button onClick={() => setShowControls(!showControls)} className="h-10 w-10 bg-white/5 backdrop-blur-xl border border-white/10 rounded-xl text-white flex items-center justify-center hover:bg-white/10 transition-colors">
                                {showControls ? <X size={18} /> : <Sparkles size={18} className="text-purple-400" />}
                            </button>
                            {!rightSidebarOpen && (
                                <button onClick={() => setRightSidebarOpen(true)} className="p-2 bg-white/5 backdrop-blur rounded-lg text-white hover:bg-white/10 transition-colors">
                                    <PanelsTopLeft size={20} className="rotate-180" />
                                </button>
                            )}
                        </div>
                    </div>

                    {/* Removed obsolete AI Floating Overlays */}

                    {/* Bottom Right: Live Opportunity Panel */}
                    <div className="flex justify-end items-end pointer-events-none">
                        <div className={`pointer-events-auto transition-all duration-300 origin-bottom-right ${showControls ? 'opacity-100 scale-100' : 'opacity-0 scale-95 pointer-events-none translate-y-10'}`}>
                            <LiveOpportunityCard 
                                symbol={bestOpportunity?.symbol || null}
                                agentDecision={bestOpportunity?.agentDecision || null}
                                ltp={bestOpportunity?.ltp || 0}
                                onSelect={(sym) => { setActiveSymbol(sym); setShowControls(false); }}
                                onClose={() => setShowControls(false)}
                            />
                        </div>
                    </div>

                </div>
            </div>

            {/* Bottom Right: Journal Button */}
            <button
                onClick={() => setCurrentPage('journal')}
                className="absolute bottom-6 right-6 z-30 p-3 bg-purple-600 hover:bg-purple-500 rounded-full shadow-lg shadow-purple-500/25 transition-all hover:scale-105"
                title="Trade Journal"
            >
                <BookOpen size={20} className="text-white" />
            </button>

            {/* RIGHT: Sidebar (Analysis & AI) */}
            <div className={`
          absolute right-0 top-0 h-full w-80 z-20 transition-all duration-300
          bg-slate-900/50 backdrop-blur-md border-l border-white/10 flex flex-col
          ${rightSidebarOpen ? 'translate-x-0' : 'translate-x-full'}
      `}>
                {/* Header */}
                <div className="p-4 border-b border-white/10 flex justify-between items-center">
                    <div className="flex items-center gap-2 text-white/80">
                        <Brain size={18} className="text-purple-400" />
                        <span className="text-xs font-bold tracking-widest uppercase">Intelligence</span>
                    </div>
                    <button
                        onClick={() => setRightSidebarOpen(false)}
                        className="text-white/40 hover:text-white transition-colors"
                    >
                        <X size={16} />
                    </button>
                </div>

                {/* Content Scroll */}
                <div className="flex-1 overflow-y-auto p-4 space-y-4">
                    <ErrorBoundary name="Analysis">
                        <AIAnalysisPanel
                            analysis={activeInstrument.genAIAnalysis}
                            amtResult={activeInstrument.amtAnalysis}
                            portfolio={activeInstrument.portfolio}
                            riskState={activeInstrument.riskState}
                            agentDecision={activeInstrument.agentDecision}
                            llmHistory={activeInstrument.llmHistory}
                            orderBook={activeInstrument.orderBook}
                            depth20Active={activeInstrument.depth20Active}
                            overseerAction={activeInstrument.overseerAction}
                            overseerReason={activeInstrument.overseerReason}
                        />
                    </ErrorBoundary>
                </div>
            </div>

        </div>
    );
}

export default App;
