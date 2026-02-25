
import React, { useState, useMemo } from 'react';
import ChartScene from './components/ChartScene';
import AIControls from './components/AIControls';
import { AIAnalysisPanel } from './components/AIAnalysisPanel';
import MarketSidebar from './components/MarketSidebar';
import { DEFAULT_CONFIG } from './constants';
import { ChartConfig, ChatMessage, MessageRole, ChartMode } from './types';
import { X, Activity, Loader2, PanelsTopLeft, Sparkles, Brain, BarChart2, Grid, BookOpen } from 'lucide-react';
import { useServerTradingSystem as useTradingSystem } from './hooks/useServerTradingSystem';
import JournalPage from './components/JournalPage';

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
    const [currentPage, setCurrentPage] = useState<'trading' | 'journal'>('trading');

    // 2. Server-driven trading system (all logic on backend)
    const {
        instruments,
        activeSymbol,
        setActiveSymbol,
        activeInstrument,
        activeFootprint,
        connected,
    } = useTradingSystem(config);

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
                    const newSym = result.configUpdates.symbol;
                    if (instruments[newSym]) {
                        setActiveSymbol(newSym);
                    } else {
                        setChatHistory(prev => [...prev, { id: simpleId(), role: MessageRole.SYSTEM, text: `Switched view to ${newSym}, but not currently in scanned universe.` }]);
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

    const effectiveConfig = useMemo<ChartConfig>(() => ({
        ...config,
        symbol: activeInstrument?.symbol || config.symbol,
    }), [config, activeInstrument?.symbol]);

    // --- Rendering ---

    if (currentPage === 'journal') {
        return <JournalPage onBack={() => setCurrentPage('trading')} />;
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
                        predictions={activeInstrument.predictions}
                        config={effectiveConfig}
                        activeSignal={activeInstrument.amtAnalysis?.signal}
                        positions={activeInstrument.portfolio.positions}
                        closedTrades={activeInstrument.portfolio.closedTrades}
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

                            {/* Dual Volume Profile Tabs */}
                            <div className="flex bg-white/5 backdrop-blur rounded-lg border border-white/10 overflow-hidden">
                                {([
                                    { key: 'session', label: '1. Session' },
                                    { key: 'leg', label: '2. Leg' },
                                    { key: 'combined', label: '3. Combined' },
                                    { key: 'off', label: 'Off' },
                                ] as const).map(({ key, label }) => (
                                    <button
                                        key={key}
                                        onClick={() => setConfig(s => ({ ...s, vpMode: key, showVolumeProfile: key !== 'off' }))}
                                        className={`px-3 py-1.5 text-xs font-medium transition-all ${config.vpMode === key
                                            ? key === 'combined' ? 'bg-blue-500/30 text-blue-100 shadow-sm' : 'bg-white/10 text-white'
                                            : 'text-white/40 hover:text-white hover:bg-white/5'
                                        }`}
                                    >
                                        {label}
                                    </button>
                                ))}
                            </div>
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
                    <AIAnalysisPanel
                        analysis={activeInstrument.genAIAnalysis}
                        amtResult={activeInstrument.amtAnalysis}
                        portfolio={activeInstrument.portfolio}
                        riskState={activeInstrument.riskState}
                        agentDecision={activeInstrument.agentDecision}
                        llmHistory={activeInstrument.llmHistory}
                        orderBook={activeInstrument.orderBook}
                        depth20Active={activeInstrument.depth20Active}
                    />
                </div>
            </div>

        </div>
    );
}

export default App;
