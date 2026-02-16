
import React, { useState, useMemo } from 'react';
import ChartScene from './components/ChartScene';
import AIControls from './components/AIControls';
import { AIAnalysisPanel } from './components/AIAnalysisPanel';
import ModelAnalysisPanel from './components/ModelAnalysisPanel';
import PredictionPerformancePanel from './components/PredictionPerformancePanel';
import RLTrainingPanel from './components/RLTrainingPanel';
import MarketSidebar from './components/MarketSidebar';
import { normalizeSymbol } from './services/binanceService';
import { DEFAULT_CONFIG } from './constants';
import { ChartConfig, ChatMessage, MessageRole, ChartMode, StrategyStats, TradePosition } from './types';
import { X, Activity, Loader2, PanelsTopLeft, Sparkles, Brain, Eye, EyeOff, BarChart2, Grid } from 'lucide-react';
import { useBinanceData } from './hooks/useBinanceData';
import { useServerTradingSystem as useTradingSystem } from './hooks/useServerTradingSystem';

const simpleId = () => Date.now().toString(36) + Math.random().toString(36).substr(2);

function App() {
    // 1. UI State
    const [config, setConfig] = useState<ChartConfig>(DEFAULT_CONFIG);
    const [chartMode, setChartMode] = useState<ChartMode>('STANDARD');
    const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
    const [isProcessing, setIsProcessing] = useState(false);
    const [showControls, setShowControls] = useState(false);
    const [sidebarOpen, setSidebarOpen] = useState(true);
    const [rightSidebarOpen, setRightSidebarOpen] = useState(true);

    // 2. Infrastructure Layer (Data Fetching)
    const marketData = useBinanceData(config.interval);

    // 3. Application Layer (Business Logic & State)
    const {
        instruments,
        activeSymbol,
        setActiveSymbol,
        activeInstrument,
        activeFootprint
    } = useTradingSystem(config, marketData);

    // --- Handlers ---

    const handleSendMessage = async (text: string) => {
        setChatHistory(prev => [...prev, { id: simpleId(), role: MessageRole.USER, text }]);
        setIsProcessing(true);
        try {
            const res = await fetch('/api/ai/command', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt: text, currentConfig: config }),
            });
            if (!res.ok) throw new Error(`AI API error: ${res.status}`);
            const result = await res.json();
            setChatHistory(prev => [...prev, { id: simpleId(), role: MessageRole.ASSISTANT, text: result.message }]);

            if (result.configUpdates) {
                if (result.configUpdates.symbol) {
                    const newSym = normalizeSymbol(result.configUpdates.symbol);
                    if (instruments[newSym]) {
                        setActiveSymbol(newSym);
                    } else {
                        setChatHistory(prev => [...prev, { id: simpleId(), role: MessageRole.SYSTEM, text: `I switched your view to ${newSym}, but I am not currently trading it in the scanned universe.` }]);
                    }
                }
                setConfig(prev => ({ ...prev, ...result.configUpdates }));
            }
        } catch (e) {
            console.error(e);
            setChatHistory(prev => [...prev, { id: simpleId(), role: MessageRole.ASSISTANT, text: "Error processing command." }]);
        } finally {
            setIsProcessing(false);
        }
    };

    // Memoized derived state — must be before early returns (Rules of Hooks)
    const aiStats = useMemo<StrategyStats>(() => {
        if (!activeInstrument) return { totalTrades: 0, wins: 0, losses: 0, winRate: 0, netProfit: 0, avgProfit: 0, largestWin: 0, largestLoss: 0 };
        const predTrades = activeInstrument.portfolio.closedTrades.filter((t: TradePosition) => t.source === 'PREDICTION');
        const wins = predTrades.filter((t: TradePosition) => t.pnl > 0);
        const losses = predTrades.filter((t: TradePosition) => t.pnl <= 0);
        const netProfit = predTrades.reduce((s: number, t: TradePosition) => s + t.pnl, 0);
        return {
            totalTrades: predTrades.length,
            wins: wins.length,
            losses: losses.length,
            winRate: predTrades.length > 0 ? (wins.length / predTrades.length) * 100 : 0,
            netProfit,
            avgProfit: predTrades.length > 0 ? netProfit / predTrades.length : 0,
            largestWin: wins.reduce((max: number, t: TradePosition) => Math.max(max, t.pnl), 0),
            largestLoss: losses.reduce((min: number, t: TradePosition) => Math.min(min, t.pnl), 0),
        };
    }, [activeInstrument?.portfolio.closedTrades]);

    const amtPortfolio = useMemo(() => {
        if (!activeInstrument) return null;
        return {
            ...activeInstrument.portfolio,
            positions: activeInstrument.portfolio.positions.filter(p => p.source === 'AMT'),
        };
    }, [activeInstrument?.portfolio]);

    const effectiveConfig = useMemo<ChartConfig>(() => ({
        ...config,
        symbol: activeInstrument?.symbol || config.symbol,
    }), [config, activeInstrument?.symbol]);

    // --- Rendering ---

    if (marketData.isScanning) {
        return (
            <div className="w-screen h-screen bg-slate-900 flex flex-col items-center justify-center text-white space-y-4">
                <Loader2 className="w-12 h-12 animate-spin text-purple-500" />
                <div className="text-center">
                    <h2 className="text-xl font-bold">Scanning Market</h2>
                    <p className="text-sm text-white/50">Identifying high-volatility contracts...</p>
                </div>
            </div>
        );
    }

    if (!activeInstrument) return null;

    return (
        <div className="relative w-screen h-screen overflow-hidden bg-slate-900 flex">

            {/* LEFT: Sidebar (Market Scanner) */}
            <div className={`
          absolute left-0 top-0 h-full z-20 transition-all duration-300
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}
      `}>
                <MarketSidebar
                    instruments={instruments}
                    activeSymbol={activeSymbol}
                    onSelect={setActiveSymbol}
                />
            </div>

            {/* CENTER: Main Content */}
            <div className={`
        flex-1 relative h-full transition-all duration-300 flex flex-col
        ${sidebarOpen ? 'ml-64' : 'ml-0'}
        ${rightSidebarOpen ? 'mr-80' : 'mr-0'}
      `}>

                {/* Chart Layer */}
                <div className="absolute inset-0 z-0">
                    {/* Instance 1: Standard Candles */}
                    <ChartScene
                        key={`standard-${activeInstrument.symbol}`}
                        data={activeInstrument.data}
                        predictions={activeInstrument.predictions}
                        config={effectiveConfig}
                        activeSignal={activeInstrument.amtAnalysis?.signal}
                        positions={activeInstrument.portfolio.positions}
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
                        predictions={activeInstrument.predictions}
                        config={effectiveConfig}
                        activeSignal={activeInstrument.amtAnalysis?.signal}
                        positions={activeInstrument.portfolio.positions}
                        amtAnalysis={activeInstrument.amtAnalysis}
                        mode="FOOTPRINT"
                        isHidden={chartMode !== 'FOOTPRINT'}
                        footprintData={activeFootprint.data}
                        cumulativeDeltas={activeFootprint.cumulativeDeltas}
                    />
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

                            {/* CHART MODE TABS */}
                            <div className="flex bg-white/5 backdrop-blur rounded-lg p-1 gap-1 border border-white/10">
                                <button
                                    onClick={() => setChartMode('STANDARD')}
                                    className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${chartMode === 'STANDARD' ? 'bg-purple-500/20 text-purple-200 shadow-sm' : 'text-white/40 hover:text-white hover:bg-white/5'}`}
                                >
                                    <span className="flex items-center gap-1.5">
                                        <BarChart2 size={14} /> Candles
                                    </span>
                                </button>
                                <button
                                    onClick={() => setChartMode('FOOTPRINT')}
                                    className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${chartMode === 'FOOTPRINT' ? 'bg-blue-500/20 text-blue-200 shadow-sm' : 'text-white/40 hover:text-white hover:bg-white/5'}`}
                                >
                                    <span className="flex items-center gap-1.5">
                                        <Grid size={14} /> Footprint
                                    </span>
                                </button>
                            </div>

                            {/* Volume Profile Toggle */}
                            <button
                                onClick={() => setConfig(s => ({ ...s, showVolumeProfile: !s.showVolumeProfile }))}
                                className={`p-2 bg-white/5 backdrop-blur rounded-lg transition-colors border border-white/10 ${config.showVolumeProfile ? 'text-white hover:bg-white/10' : 'text-white/50 hover:text-white hover:bg-white/10'}`}
                                title={config.showVolumeProfile ? "Hide Volume Profile" : "Show Volume Profile"}
                            >
                                {config.showVolumeProfile ? <Eye size={20} /> : <EyeOff size={20} />}
                            </button>
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

                    {/* Bottom Right: Chat Overlay */}
                    <div className="flex justify-end items-end pointer-events-none">
                        <div className={`pointer-events-auto transition-all duration-300 origin-bottom-right ${showControls ? 'opacity-100 scale-100' : 'opacity-0 scale-95 pointer-events-none translate-y-10'}`}>
                            <AIControls
                                onSendMessage={handleSendMessage}
                                isProcessing={isProcessing}
                                history={chatHistory}
                                hasApiKey={true}
                                onSetApiKey={() => { }}
                                onClose={() => setShowControls(false)}
                            />
                        </div>
                    </div>

                </div>
            </div>

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
                    {/* 
                    {config.showPredictions && (
                        <PredictionPerformancePanel
                            stats={aiStats}
                            activeTrade={activeInstrument.portfolio.positions.find(p => p.source === 'PREDICTION')}
                            ghostCandles={activeInstrument.predictions}
                            analysis={activeInstrument.aiAnalysis}
                            weights={activeInstrument.modelWeights}
                            generation={activeInstrument.generation}
                        />
                    )} 
                    */}

                    <AIAnalysisPanel
                        analysis={activeInstrument.genAIAnalysis}
                        amtResult={activeInstrument.amtAnalysis}
                        portfolio={activeInstrument.portfolio}
                        riskState={activeInstrument.riskState}
                        llmHistory={activeInstrument.llmHistory}
                    />

                    {/* 
                    <ModelAnalysisPanel
                        analysis={activeInstrument.amtAnalysis}
                        portfolio={amtPortfolio}
                        show={true}
                    />

                    <RLTrainingPanel
                        liveStatus={(activeInstrument as any).rlStatus ?? null}
                    /> 
                    */}
                </div>
            </div>

        </div>
    );
}

export default App;
