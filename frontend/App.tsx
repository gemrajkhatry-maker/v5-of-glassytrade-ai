import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import ChartScene from './components/ChartScene';
import { AIAnalysisPanel } from './components/AIAnalysisPanel';
import MarketSidebar from './components/MarketSidebar';
import ErrorBoundary from './components/ErrorBoundary';
import { DEFAULT_CONFIG } from './constants';
import { ChartConfig } from './types';
import { X, Activity, Loader2, PanelsTopLeft, Brain, BarChart2, BookOpen, Eye } from 'lucide-react';
import { useServerTradingSystem as useTradingSystem } from './hooks/useServerTradingSystem';
import JournalPage from './components/JournalPage';
import ModelStateBanner from './components/ModelStateBanner';
import { useKeyboardNavigation, getDefaultTradingHotkeys } from './hooks/useKeyboardNavigation';
import { useUIStore, selectChartMode, selectSidebarOpen, selectRightSidebarOpen, selectVpMode, selectShowHalfTrend, selectShowHARSI } from './stores/ui';

const simpleId = () => Date.now().toString(36) + Math.random().toString(36).substr(2);

function App() {
    // 1. UI State - Using Zustand for persistence
    const [config, setConfig] = useState<ChartConfig>(DEFAULT_CONFIG);
    const chartMode = useUIStore(selectChartMode);
    const setChartMode = useUIStore(s => s.setChartMode);
    const sidebarOpen = useUIStore(selectSidebarOpen);
    const setSidebarOpen = useUIStore(s => s.setSidebarOpen);
    const rightSidebarOpen = useUIStore(selectRightSidebarOpen);
    const setRightSidebarOpen = useUIStore(s => s.setRightSidebarOpen);
    const currentPage = useUIStore(s => s.currentPage);
    const setCurrentPage = useUIStore(s => s.setCurrentPage);
    const vpMode = useUIStore(selectVpMode) as 'session' | 'leg' | 'combined' | 'off';
    const setVpMode = useUIStore(s => s.setVpMode);
    const showHalfTrend = useUIStore(selectShowHalfTrend);
    const setHalfTrendVisible = useUIStore(s => s.setHalfTrendVisible);
    const showHARSI = useUIStore(selectShowHARSI);
    const setHARSIVisible = useUIStore(s => s.setHARSIVisible);
    const [timeframe, setTimeframe] = useState<'1m' | '5m' | 'split'>('5m');
    const currentSymbolIndex = useRef(0);

    // 2. Server-driven trading system (all logic on backend)
    const {
        instruments,
        activeSymbol,
        setActiveSymbol,
        activeInstrument,
        connected,
        connectionStatus,
        tickBus,
        isHalted,
        haltReason,
    } = useTradingSystem(config);

    // Symbols for Tab/Shift+Tab navigation, derived from the live WS instrument
    // state (the legacy instruments store is unused and was removed).
    const allSymbols = useMemo(() => Object.keys(instruments), [Object.keys(instruments).join(',')]);

    // 3. Keyboard Navigation
    const handleNextSymbol = useCallback(() => {
        if (allSymbols.length === 0) return;
        currentSymbolIndex.current = (currentSymbolIndex.current + 1) % allSymbols.length;
        setActiveSymbol(allSymbols[currentSymbolIndex.current]);
    }, [allSymbols, setActiveSymbol]);

    const handlePrevSymbol = useCallback(() => {
        if (allSymbols.length === 0) return;
        currentSymbolIndex.current = (currentSymbolIndex.current - 1 + allSymbols.length) % allSymbols.length;
        setActiveSymbol(allSymbols[currentSymbolIndex.current]);
    }, [allSymbols, setActiveSymbol]);

    const handleSaveWorkspace = useCallback(() => {
        // Workspace auto-saves via Zustand persist middleware
        console.log('[Keyboard] Workspace saved to localStorage');
    }, []);

    const handleOpenJournal = useCallback(() => {
        setCurrentPage('journal');
    }, [setCurrentPage]);

    // Setup keyboard hotkeys
    useKeyboardNavigation(getDefaultTradingHotkeys({
        onChartModeChange: setChartMode,
        onVpModeChange: setVpMode,
        onToggleSidebar: () => useUIStore.getState().toggleSidebar(),
        onToggleRightSidebar: () => useUIStore.getState().toggleRightSidebar(),
        onNextSymbol: handleNextSymbol,
        onPrevSymbol: handlePrevSymbol,
        onSaveWorkspace: handleSaveWorkspace,
        onOpenJournal: handleOpenJournal,
    }));

    // --- Handlers ---

    /** Stable callback for symbol selection, avoids re-renders of MarketSidebar */
    const handleSymbolSelect = useCallback((symbol: string) => {
        setActiveSymbol(symbol);
    }, [setActiveSymbol]);

    const effectiveConfig = useMemo<ChartConfig>(() => ({
        ...config,
        interval: timeframe === '1m' ? '1m' : '5m',
        vpMode: vpMode || config.vpMode,
        showVolumeProfile: vpMode !== 'off',
        showHalfTrend,
        showHARSI,
        symbol: activeInstrument?.symbol || config.symbol,
    }), [config, vpMode, showHalfTrend, showHARSI, activeInstrument?.symbol, timeframe]);

    // --- Rendering ---

    if (currentPage === 'journal') {
        return <ErrorBoundary name="Journal"><JournalPage onBack={() => setCurrentPage('trading')} /></ErrorBoundary>;
    }

    if (!activeInstrument) {
        return (
            <div className="w-screen h-screen bg-glassy-bg-primary flex flex-col items-center justify-center text-glassy-text-primary space-y-4">
                <Loader2 className="w-12 h-12 animate-spin text-glassy-ai-primary" />
                <div className="text-center max-w-md px-4">
                    <h2 className="text-xl font-bold">Connecting to Backend</h2>
                    <p className="text-sm text-glassy-text-secondary mt-2">
                        {connectionStatus ||
                            'Loading server config and symbols. Ensure the API is running (see Vite proxy / PORT).'}
                    </p>
                </div>
            </div>
        );
    }

    return (
        <div className="relative w-screen h-screen overflow-hidden bg-glassy-bg-primary flex">

            {/* Connection status banner */}
            {!connected && (
                <div className="absolute top-0 left-0 right-0 z-50 bg-glassy-danger/90 text-glassy-text-primary text-xs text-center py-1 px-4">
                    {connectionStatus || 'Disconnected from server'}
                </div>
            )}

            {/* LEFT: Sidebar (Market Scanner) */}
            <div className={`
          absolute left-0 top-0 h-full z-20 transition-transform duration-300
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}
      `}>
                <ErrorBoundary name="Sidebar">
                    <MarketSidebar
                        instruments={instruments}
                        activeSymbol={activeSymbol}
                        onSelect={handleSymbolSelect}
                        isHalted={isHalted}
                        haltReason={haltReason}
                    />
                </ErrorBoundary>
            </div>

            {/* CENTER: Main Content */}
            <div className={`
        flex-1 relative h-full transition-transform duration-300 flex flex-col
        ${sidebarOpen ? 'ml-[280px]' : 'ml-0'}
        ${rightSidebarOpen ? 'mr-[320px]' : 'mr-0'}
      `}>

                {/* Chart Layer */}
                <div className="absolute inset-0 z-0">
                    <ErrorBoundary name="Chart">
                        {timeframe === 'split' ? (
                            <div className="grid grid-cols-2 gap-2 w-full h-full p-2 pt-14">
                                {/* Left: 5m Macro View */}
                                <div className="relative w-full h-full rounded-lg overflow-hidden border border-white/10 bg-[#0c0d0f]">
                                    <div className="absolute top-2 left-2 z-10 bg-black/70 backdrop-blur-md px-2 py-0.5 rounded border border-white/10 text-[9px] font-mono font-bold text-slate-300 pointer-events-none">
                                        5m MACRO · Volume Profile &amp; VWAP
                                    </div>
                                    <ChartScene
                                        key={`${activeInstrument.symbol}-5m-split`}
                                        data={activeInstrument.data}
                                        tickBus={tickBus}
                                        symbol={activeInstrument.symbol}
                                        config={{ ...effectiveConfig, interval: '5m', showVolumeProfile: true }}
                                        positions={activeInstrument.portfolio.positions}
                                        closedTrades={activeInstrument.portfolio.closedTrades}
                                        quantDecision={activeInstrument.quantDecisionAnalysis}
                                        decisionHistory={activeInstrument.llmHistory}
                                        agentDecision={activeInstrument.agentDecision}
                                        layaDecision={activeInstrument.layaDecision}
                                        amtAnalysis={activeInstrument.amtAnalysis}
                                        halfTrendSeries={activeInstrument.halfTrendSeries}
                                        mode={chartMode}
                                        portfolio={activeInstrument.portfolio}
                                    />
                                </div>
                                {/* Right: 1m Micro View */}
                                <div className="relative w-full h-full rounded-lg overflow-hidden border border-emerald-500/20 bg-[#0c0d0f]">
                                    <div className="absolute top-2 left-2 z-10 bg-black/70 backdrop-blur-md px-2 py-0.5 rounded border border-emerald-500/30 text-[9px] font-mono font-bold text-emerald-400 pointer-events-none">
                                        1m MICRO · Trigger &amp; Order Flow
                                    </div>
                                    <ChartScene
                                        key={`${activeInstrument.symbol}-1m-split`}
                                        data={activeInstrument.data}
                                        tickBus={tickBus}
                                        symbol={activeInstrument.symbol}
                                        config={{ ...effectiveConfig, interval: '1m', showVolumeProfile: false }}
                                        positions={activeInstrument.portfolio.positions}
                                        closedTrades={activeInstrument.portfolio.closedTrades}
                                        quantDecision={activeInstrument.quantDecisionAnalysis}
                                        decisionHistory={activeInstrument.llmHistory}
                                        agentDecision={activeInstrument.agentDecision}
                                        layaDecision={activeInstrument.layaDecision}
                                        amtAnalysis={activeInstrument.amtAnalysis}
                                        halfTrendSeries={activeInstrument.halfTrendSeries}
                                        mode={chartMode}
                                        portfolio={activeInstrument.portfolio}
                                    />
                                </div>
                            </div>
                        ) : (
                            <ChartScene
                                key={`${activeInstrument.symbol}-${effectiveConfig.interval}`}
                                data={activeInstrument.data}
                                tickBus={tickBus}
                                symbol={activeInstrument.symbol}
                                config={effectiveConfig}
                                positions={activeInstrument.portfolio.positions}
                                closedTrades={activeInstrument.portfolio.closedTrades}
                                quantDecision={activeInstrument.quantDecisionAnalysis}
                                decisionHistory={activeInstrument.llmHistory}
                                agentDecision={activeInstrument.agentDecision}
                                layaDecision={activeInstrument.layaDecision}
                                amtAnalysis={activeInstrument.amtAnalysis}
                                halfTrendSeries={activeInstrument.halfTrendSeries}
                                mode={chartMode}
                                portfolio={activeInstrument.portfolio}
                            />
                        )}
                    </ErrorBoundary>
                </div>

                {/* Overlay UI Layer */}
                <div className="absolute inset-0 z-10 flex flex-col pointer-events-none">

                    {/* Primary model state — compact status strip */}
                    <div className="shrink-0 px-3 pt-3 pointer-events-auto flex justify-start">
                        <ModelStateBanner
                            amtResult={activeInstrument.amtAnalysis}
                            agentDecision={activeInstrument.agentDecision}
                            auction={activeInstrument.auctionAnalysis}
                            quantDecision={activeInstrument.quantDecisionAnalysis}
                            symbol={activeInstrument.symbol}
                        />
                    </div>

                    <div className="flex-1 flex flex-col justify-between p-3 pointer-events-none min-h-0">

                    {/* Top Bar Area */}
                    <div className="flex justify-between items-start pointer-events-none w-full">
                        {/* Left Toggle (Scanner) & Chart Controls */}
                        <div className="flex flex-col gap-1.5 items-start max-w-[min(100%,52rem)] pointer-events-auto">
                            <div className="flex items-start gap-1.5 flex-wrap">
                            {!sidebarOpen && (
                                <button onClick={() => setSidebarOpen(true)} className="p-2 bg-glassy-bg-elevated/50 backdrop-blur rounded-sm text-glassy-text-primary hover:bg-glassy-bg-hover transition-colors">
                                    <Activity size={20} />
                                </button>
                            )}

                            {/* Chart view */}
                            <div className="flex flex-col gap-1">
                                <span className="text-[9px] font-bold uppercase tracking-widest text-glassy-text-tertiary pl-1">Chart view</span>
                                <div className="flex bg-glassy-bg-tertiary backdrop-blur-md rounded-sm p-1 gap-1 border border-glassy-border-default">
                                <button
                                    onClick={() => setChartMode('STANDARD')}
                                    className={`px-3 py-1.5 rounded-sm text-xs font-bold transition-all ${chartMode === 'STANDARD' ? 'bg-glassy-bg-active text-glassy-text-primary' : 'text-glassy-text-tertiary hover:text-glassy-text-secondary hover:bg-glassy-bg-hover'}`}
                                >
                                    <span className="flex items-center gap-1.5">
                                        <BarChart2 size={14} /> Candles
                                    </span>
                                </button>
                                </div>
                            </div>

                            {/* Timeframe view */}
                            <div className="flex flex-col gap-1">
                                <span className="text-[9px] font-bold uppercase tracking-widest text-glassy-text-tertiary pl-1">Timeframe</span>
                                <div className="flex bg-glassy-bg-tertiary backdrop-blur-md rounded-sm p-1 gap-1 border border-glassy-border-default">
                                {([
                                    { key: '1m', label: '1m' },
                                    { key: '5m', label: '5m' },
                                    { key: 'split', label: '1m | 5m Split' },
                                ] as const).map(({ key, label }) => (
                                    <button
                                        key={key}
                                        onClick={() => setTimeframe(key)}
                                        className={`px-3 py-1.5 rounded-sm text-xs font-bold transition-all ${timeframe === key
                                            ? 'bg-glassy-ai-primary/20 text-glassy-ai-primary border border-glassy-ai-primary/40'
                                            : 'text-glassy-text-tertiary hover:text-glassy-text-secondary hover:bg-glassy-bg-hover'
                                            }`}
                                    >
                                        {label}
                                    </button>
                                ))}
                                </div>
                            </div>

                            {/* Volume profile overlay */}
                            <div className="flex flex-col gap-1">
                                <span className="text-[9px] font-bold uppercase tracking-widest text-glassy-text-tertiary pl-1">Profile overlay</span>
                                <div className="flex bg-glassy-bg-tertiary backdrop-blur-md rounded-sm p-1 gap-1 border border-glassy-border-default">
                                {([
                                    { key: 'session', label: 'Session' },
                                    { key: 'leg', label: 'Leg' },
                                    { key: 'combined', label: 'Combined' },
                                    { key: 'off', label: 'Off' },
                                ] as const).map(({ key, label }) => (
                                    <button
                                        key={key}
                                        onClick={() => {
                                            setVpMode(key);
                                            setConfig(s => ({ ...s, vpMode: key, showVolumeProfile: key !== 'off' }));
                                        }}
                                        className={`px-3 py-1.5 rounded-sm text-xs font-bold transition-all ${vpMode === key
                                            ? 'bg-glassy-neutral-cool/20 text-glassy-neutral-cool border border-glassy-neutral-cool/30'
                                            : 'text-glassy-text-tertiary hover:text-glassy-text-secondary hover:bg-glassy-bg-hover'
                                            }`}
                                    >
                                        {label}
                                    </button>
                                ))}
                                </div>
                            </div>

                            {/* HalfTrend overlay */}
                            <div className="flex flex-col gap-1">
                                <span className="text-[9px] font-bold uppercase tracking-widest text-glassy-text-tertiary pl-1">HalfTrend</span>
                                <div className="flex bg-glassy-bg-tertiary backdrop-blur-md rounded-sm p-1 gap-1 border border-glassy-border-default">
                                {([
                                    { on: true, label: 'On' },
                                    { on: false, label: 'Off' },
                                ] as const).map(({ on, label }) => (
                                    <button
                                        key={label}
                                        onClick={() => {
                                            setHalfTrendVisible(on);
                                            setConfig(s => ({ ...s, showHalfTrend: on }));
                                        }}
                                        className={`px-3 py-1.5 rounded-sm text-xs font-bold transition-all ${showHalfTrend === on
                                            ? 'bg-glassy-ai-primary/20 text-glassy-ai-primary border border-glassy-ai-primary/40'
                                            : 'text-glassy-text-tertiary hover:text-glassy-text-secondary hover:bg-glassy-bg-hover'
                                            }`}
                                    >
                                        {label}
                                    </button>
                                ))}
                                </div>
                            </div>

                            {/* HARSI Oscillator Subplot */}
                            <div className="flex flex-col gap-1">
                                <span className="text-[9px] font-bold uppercase tracking-widest text-purple-400 pl-1">HARSI</span>
                                <div className="flex bg-glassy-bg-tertiary backdrop-blur-md rounded-sm p-1 gap-1 border border-glassy-border-default">
                                {([
                                    { on: true, label: 'On' },
                                    { on: false, label: 'Off' },
                                ] as const).map(({ on, label }) => (
                                    <button
                                        key={label}
                                        onClick={() => {
                                            setHARSIVisible(on);
                                            setConfig(s => ({ ...s, showHARSI: on }));
                                        }}
                                        className={`px-3 py-1.5 rounded-sm text-xs font-bold transition-all ${showHARSI === on
                                            ? 'bg-purple-500/20 text-purple-400 border border-purple-500/40'
                                            : 'text-glassy-text-tertiary hover:text-glassy-text-secondary hover:bg-glassy-bg-hover'
                                            }`}
                                    >
                                        {label}
                                    </button>
                                ))}
                                </div>
                            </div>
                            </div>
                        </div>

                        {/* Right Toggle (Analysis) + Chat Toggle */}
                        <div className="flex items-start gap-1.5">
                            {!rightSidebarOpen && (
                                <button onClick={() => setRightSidebarOpen(true)} className="p-2 bg-glassy-bg-elevated/50 backdrop-blur rounded-sm text-glassy-text-primary hover:bg-glassy-bg-hover transition-colors">
                                    <PanelsTopLeft size={20} className="rotate-180" />
                                </button>
                            )}
                        </div>
                    </div>

                    </div>

                </div>
            </div>

            {/* Bottom Right: Journal Button */}
            <button
                onClick={() => setCurrentPage('journal')}
                className="absolute bottom-6 right-6 z-30 p-3 bg-glassy-ai-primary hover:bg-glassy-ai-secondary rounded-sm transition-all hover:scale-105"
                title="Trade Journal"
            >
                <BookOpen size={20} className="text-glassy-bg-primary" />
            </button>

            {/* RIGHT: Sidebar (Analysis & AI) */}
            <div className={`
          absolute right-0 top-0 h-full w-[320px] z-20 transition-transform duration-300
          bg-glassy-bg-secondary/80 backdrop-blur-md border-l border-glassy-border-default flex flex-col
          ${rightSidebarOpen ? 'translate-x-0' : 'translate-x-full'}
      `}>
                {/* Header */}
                <div className="p-4 border-b border-glassy-border-default flex justify-between items-center">
                    <div className="flex items-center gap-2 text-glassy-text-primary">
                        <Brain size={18} className="text-glassy-ai-primary" />
                        <span className="text-xs font-bold tracking-widest uppercase">Intelligence</span>
                    </div>
                    <button
                        onClick={() => setRightSidebarOpen(false)}
                        className="text-glassy-text-secondary hover:text-glassy-text-primary transition-colors"
                    >
                        <X size={16} />
                    </button>
                </div>

                {/* Content Scroll */}
                <div className="flex-1 overflow-y-auto p-4 space-y-4">
                    <ErrorBoundary name="Analysis">
                        <AIAnalysisPanel
                            amtResult={activeInstrument.amtAnalysis}
                            portfolio={activeInstrument.portfolio}
                            riskState={activeInstrument.riskState}
                            agentDecision={activeInstrument.agentDecision}
                            layaDecision={activeInstrument.layaDecision || activeInstrument.agentDecision?.laya}
                            llmHistory={activeInstrument.llmHistory}
                            orderBook={activeInstrument.orderBook}
                            overseerAction={activeInstrument.overseerAction}
                            overseerReason={activeInstrument.overseerReason}
                            quantDecision={activeInstrument.quantDecisionAnalysis}
                            auction={activeInstrument.auctionAnalysis}
                            symbol={activeSymbol}
                            data={activeInstrument.data}
                        />
                    </ErrorBoundary>
                </div>
            </div>

        </div>
    );
}

export default App;
