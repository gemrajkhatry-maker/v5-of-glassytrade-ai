import React, { useState, useEffect } from 'react';
import { ArrowLeft, ChevronLeft, ChevronRight, TrendingUp, TrendingDown, Filter, BarChart3, List } from 'lucide-react';
import { sanitizeRationale } from '../utils/textSanitizer';
import { shortSymbolName, shortSymbol } from '../utils/symbol';

interface JournalSummary {
    date: string;
    total_signals: number;
    total_entries: number;
    total_rejections: number;
    total_exits: number;
    total_pnl: number;
    wins: number;
    losses: number;
    win_rate: number;
    avg_time_in_trade_s: number;
    avg_mfe: number;
    avg_mae: number;
}

interface CompletedTrade {
    symbol: string;
    side: string;
    entry_time: string;
    exit_time: string;
    entry_price: number;
    exit_price: number;
    stop_loss: number;
    take_profit: number;
    pnl: number;
    pnl_pct: number;
    duration_s: number;
    exit_reason: string;
    mfe: number;
    mae: number;
    market_state: string;
    thesis_aggression_trigger?: string;
    thesis_setup_family?: string;
    close_reason?: string;
    llm_rationale: string;
    position_id: string;
}

interface JournalEntry {
    timestamp: string;
    event_type: string;
    symbol: string;
    side: string;
    entry_price: number;
    exit_price: number;
    stop_loss: number;
    take_profit: number;
    pnl: number;
    pnl_pct: number;
    exit_reason: string;
    market_state: string;
    llm_direction: string;
    llm_confidence: string;
    llm_rationale: string;
    poc: number;
    vah: number;
    val: number;
    delta: number;
    cvd_slope: number;
    profile_shape: string;
    session_name: string;
    position_id: string;
    time_in_trade_s: number;
    mfe: number;
    mae: number;
    risk_reject_reason: string;
}

const EXIT_REASON_COLORS: Record<string, string> = {
    STOP_LOSS: 'text-glassy-bear-primary bg-glassy-bear-primary/10',
    TAKE_PROFIT: 'text-glassy-bull-primary bg-glassy-bull-primary/10',
    EXIT_SIGNAL: 'text-glassy-ai-primary bg-glassy-ai-primary/10',
    ADVERSE_EXIT: 'text-glassy-danger bg-glassy-danger/10',
    TRAILING_STOP: 'text-glassy-warning bg-glassy-warning/10',
    TIME_STOP: 'text-glassy-warning bg-glassy-warning/10',
    OVERSEER_EXIT: 'text-glassy-ai-primary bg-glassy-ai-primary/10',
    OVERSEER_PARTIAL: 'text-glassy-ai-primary bg-glassy-ai-primary/10',
    SCRATCH: 'text-glassy-text-disabled bg-glassy-bg-elevated',
    BREAK_EVEN: 'text-glassy-text-disabled bg-glassy-bg-elevated',
    SPREAD_BLOWOUT: 'text-glassy-bear-primary bg-glassy-bear-primary/10',
};

const EVENT_COLORS: Record<string, string> = {
    SIGNAL_GENERATED: 'text-glassy-ai-primary bg-glassy-ai-primary/10',
    ENTRY_EXECUTED: 'text-glassy-bull-primary bg-glassy-bull-primary/10',
    ENTRY_REJECTED: 'text-glassy-warning bg-glassy-warning/10',
    EXIT: 'text-glassy-ai-primary bg-glassy-ai-primary/10',
    OVERSEER_ACTION: 'text-glassy-ai-primary bg-glassy-ai-primary/10',
    BREAK_EVEN_TRIGGERED: 'text-glassy-warning bg-glassy-warning/10',
};

function normalizedExitReason(exitReason: string, pnl: number): string {
    if (!exitReason) return '-';
    if (pnl < 0 && exitReason === 'TAKE_PROFIT') return 'ADVERSE_EXIT';
    return exitReason;
}

function participantLabelFromTrade(trade: CompletedTrade): { text: string; classes: string } | null {
    const setupFamily = (trade.thesis_setup_family || '').toLowerCase();
    if (setupFamily === 'imbalance_continuation') {
        return { text: 'INITIATIVE ↑', classes: 'bg-emerald-400/20 text-emerald-300' };
    }
    if (setupFamily === 'return_to_value') {
        return { text: 'RESPONSIVE ↓', classes: 'bg-blue-400/20 text-blue-300' };
    }

    const trigger = (trade.thesis_aggression_trigger || '').toLowerCase();
    if (trigger.includes('break_') || trigger.includes('cvd') || trigger.includes('expansion') || trigger.includes('initiative')) {
        return { text: 'INITIATIVE ↑', classes: 'bg-emerald-400/20 text-emerald-300' };
    }
    if (trigger.includes('responsive') || trigger.includes('neutral') || trigger.includes('volume_present') || trigger.includes('price_movement')) {
        return { text: 'RESPONSIVE ↓', classes: 'bg-blue-400/20 text-blue-300' };
    }

    return null;
}

function formatTime(ts: string): string {
    try {
        const d = new Date(ts);
        return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    } catch { return ts; }
}

function formatDuration(s: number): string {
    if (!s) return '-';
    const m = Math.floor(s / 60);
    const sec = Math.round(s % 60);
    return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
}

export default function JournalPage({ onBack }: { onBack: () => void }) {
    const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
    const [tab, setTab] = useState<'trades' | 'events'>('trades');
    const [summary, setSummary] = useState<JournalSummary | null>(null);
    const [trades, setTrades] = useState<CompletedTrade[]>([]);
    const [entries, setEntries] = useState<JournalEntry[]>([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState<string>('ALL');
    const [hideFlat, setHideFlat] = useState(true);

    useEffect(() => {
        setLoading(true);
        Promise.all([
            fetch(`/api/ai/journal/trades?date=${date}`).then(r => r.ok ? r.json() : { trades: [] }),
            fetch(`/api/ai/journal?date=${date}`).then(r => r.ok ? r.json() : { entries: [] }),
            fetch(`/api/ai/journal/summary?date=${date}`).then(r => r.ok ? r.json() : null),
        ]).then(([t, j, s]) => {
            setTrades(t.trades || []);
            setEntries(j.entries || []);
            setSummary(s);
        }).catch(console.error).finally(() => setLoading(false));
    }, [date]);

    const shiftDate = (days: number) => {
        const d = new Date(date);
        d.setDate(d.getDate() + days);
        setDate(d.toISOString().slice(0, 10));
    };

    const filteredEvents = (filter === 'ALL' ? entries : entries.filter(e => e.event_type === filter))
        .filter(e => !hideFlat || !(e.event_type === 'SIGNAL_GENERATED' && (!e.llm_direction || e.llm_direction === 'FLAT')));

    return (
        <div className="w-screen h-screen bg-glassy-bg-primary text-glassy-text-primary flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-glassy-border-default bg-glassy-bg-secondary/80 backdrop-blur">
                <div className="flex items-center gap-4">
                    <button onClick={onBack} className="p-2 rounded-md hover:bg-glassy-bg-hover transition-colors">
                        <ArrowLeft size={20} />
                    </button>
                    <h1 className="text-lg font-bold tracking-wide">Trade Journal</h1>
                </div>
                <div className="flex items-center gap-2">
                    <button onClick={() => shiftDate(-1)} className="p-1.5 rounded-md hover:bg-glassy-bg-hover"><ChevronLeft size={18} /></button>
                    <input
                        type="date"
                        value={date}
                        onChange={e => setDate(e.target.value)}
                        className="bg-glassy-bg-elevated border border-glassy-border-default rounded-md px-3 py-1.5 text-sm text-glassy-text-primary outline-none focus:border-glassy-border-prominent"
                    />
                    <button onClick={() => shiftDate(1)} className="p-1.5 rounded-md hover:bg-glassy-bg-hover"><ChevronRight size={18} /></button>
                </div>
            </div>

            {/* Summary Cards */}
            {summary && (
                <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3 px-6 py-4">
                    <StatCard label="Signals" value={summary.total_signals} />
                    <StatCard label="Entries" value={summary.total_entries} />
                    <StatCard label="Rejections" value={summary.total_rejections} color="text-orange-400" />
                    <StatCard label="Exits" value={summary.total_exits} />
                    <StatCard label="Wins" value={summary.wins} color="text-emerald-400" />
                    <StatCard label="Losses" value={summary.losses} color="text-red-400" />
                    <StatCard label="Win Rate" value={`${summary.win_rate.toFixed(1)}%`}
                        color={summary.win_rate >= 50 ? 'text-emerald-400' : 'text-red-400'} />
                    <StatCard label="Total PnL" value={`₹${summary.total_pnl.toFixed(2)}`}
                        color={summary.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'} />
                </div>
            )}

            {/* Tab Bar */}
            <div className="px-6 pb-3 flex items-center gap-4 border-b border-white/5">
                <div className="flex gap-1 bg-white/5 rounded-lg p-0.5">
                    <button onClick={() => setTab('trades')}
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${tab === 'trades' ? 'bg-purple-500/20 text-purple-300' : 'text-white/40 hover:text-white/70'}`}>
                        <BarChart3 size={13} /> Trades
                    </button>
                    <button onClick={() => setTab('events')}
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${tab === 'events' ? 'bg-purple-500/20 text-purple-300' : 'text-white/40 hover:text-white/70'}`}>
                        <List size={13} /> All Events
                    </button>
                </div>

                {tab === 'events' && (
                    <>
                        <div className="flex items-center gap-2">
                            <Filter size={14} className="text-white/40" />
                            {['ALL', 'SIGNAL_GENERATED', 'ENTRY_EXECUTED', 'ENTRY_REJECTED', 'EXIT', 'BREAK_EVEN_TRIGGERED', 'OVERSEER_ACTION'].map(f => (
                                <button key={f} onClick={() => setFilter(f)}
                                    className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${filter === f ? 'bg-purple-500/20 text-purple-300' : 'bg-white/5 text-white/40 hover:text-white/70'}`}>
                                    {f === 'ALL' ? 'All' : f.replace(/_/g, ' ')}
                                </button>
                            ))}
                        </div>
                        <label className="flex items-center gap-1.5 text-xs text-white/40 ml-auto cursor-pointer">
                            <input type="checkbox" checked={hideFlat} onChange={e => setHideFlat(e.target.checked)}
                                className="rounded border-white/20" />
                            Hide FLAT signals
                        </label>
                    </>
                )}

                <span className="ml-auto text-xs text-white/30">
                    {tab === 'trades' ? `${trades.length} trades` : `${filteredEvents.length} events`}
                </span>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto px-6 pb-6">
                {loading ? (
                    <div className="flex items-center justify-center h-40 text-white/40">Loading...</div>
                ) : tab === 'trades' ? (
                    <TradesTable trades={trades} />
                ) : (
                    <EventsTable entries={filteredEvents} />
                )}
            </div>
        </div>
    );
}

function TradesTable({ trades }: { trades: CompletedTrade[] }) {
    if (trades.length === 0) {
        return <div className="flex items-center justify-center h-40 text-white/30">No completed trades for this date</div>;
    }

    return (
        <table className="w-full text-sm">
            <thead className="sticky top-0 bg-slate-900">
                <tr className="text-white/40 text-xs uppercase tracking-wider border-b border-white/10">
                    <th className="text-left py-2 px-2">Entry</th>
                    <th className="text-left py-2 px-2">Exit</th>
                    <th className="text-left py-2 px-2">Symbol</th>
                    <th className="text-left py-2 px-2">Side</th>
                    <th className="text-right py-2 px-2">Entry ₹</th>
                    <th className="text-right py-2 px-2">Exit ₹</th>
                    <th className="text-right py-2 px-2">PnL</th>
                    <th className="text-right py-2 px-2">PnL%</th>
                    <th className="text-left py-2 px-2">Duration</th>
                    <th className="text-left py-2 px-2">Exit Reason</th>
                    <th className="text-right py-2 px-2">MFE</th>
                    <th className="text-right py-2 px-2">MAE</th>
                    <th className="text-left py-2 px-2">Market</th>
                </tr>
            </thead>
            <tbody>
                {trades.map((t, i) => {
                    const pnlColor = t.pnl > 0 ? 'text-emerald-400' : t.pnl < 0 ? 'text-red-400' : 'text-white/50';
                    const rowBg = i % 2 === 0 ? 'bg-white/[0.02]' : '';
                    const resolvedReason = normalizedExitReason(t.exit_reason, t.pnl);
                    const reasonColor = EXIT_REASON_COLORS[resolvedReason] || 'text-white/50 bg-white/5';
                    return (
                        <tr key={t.position_id || i} className={`${rowBg} hover:bg-white/5 transition-colors`}>
                            <td className="py-2 px-2 text-white/60 font-mono text-xs">{formatTime(t.entry_time)}</td>
                            <td className="py-2 px-2 text-white/60 font-mono text-xs">{formatTime(t.exit_time)}</td>
                            <td className="py-2 px-2 text-white/80 text-xs">{shortSymbolName(t.symbol)}</td>
                            <td className="py-2 px-2">
                                <span className={`flex items-center gap-1 text-xs ${t.side === 'LONG' ? 'text-emerald-400' : 'text-red-400'}`}>
                                    {t.side === 'LONG' ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
                                    {t.side}
                                </span>
                                {(() => {
                                    const participant = participantLabelFromTrade(t);
                                    if (!participant) return null;
                                    return (
                                        <span className={`inline-flex mt-1 px-1 py-0.5 rounded text-[8px] ${participant.classes}`}>
                                            {participant.text}
                                        </span>
                                    );
                                })()}
                            </td>
                            <td className="py-2 px-2 text-right font-mono text-xs text-white/70">
                                {t.entry_price ? t.entry_price.toFixed(2) : '-'}
                            </td>
                            <td className="py-2 px-2 text-right font-mono text-xs text-white/70">
                                {t.exit_price ? t.exit_price.toFixed(2) : '-'}
                            </td>
                            <td className={`py-2 px-2 text-right font-mono text-xs font-bold ${pnlColor}`}>
                                {t.pnl ? (t.pnl > 0 ? '+' : '') + t.pnl.toFixed(2) : '-'}
                            </td>
                            <td className={`py-2 px-2 text-right font-mono text-xs ${pnlColor}`}>
                                {t.pnl_pct ? (t.pnl_pct > 0 ? '+' : '') + t.pnl_pct.toFixed(2) + '%' : '-'}
                            </td>
                            <td className="py-2 px-2 text-xs text-white/50">{formatDuration(t.duration_s)}</td>
                            <td className="py-2 px-2">
                                <span className={`px-2 py-0.5 rounded text-xs font-medium ${reasonColor}`}>
                                    {(resolvedReason || '').replace(/_/g, ' ') || '-'}
                                </span>
                            </td>
                            <td className="py-2 px-2 text-right font-mono text-xs text-emerald-400/60">
                                {t.mfe ? t.mfe.toFixed(2) : '-'}
                            </td>
                            <td className="py-2 px-2 text-right font-mono text-xs text-red-400/60">
                                {t.mae ? t.mae.toFixed(2) : '-'}
                            </td>
                            <td className="py-2 px-2 text-xs text-white/40">{t.market_state || '-'}</td>
                        </tr>
                    );
                })}
            </tbody>
        </table>
    );
}

function EventsTable({ entries }: { entries: JournalEntry[] }) {
    if (entries.length === 0) {
        return <div className="flex items-center justify-center h-40 text-white/30">No journal entries</div>;
    }

    return (
        <table className="w-full text-sm">
            <thead className="sticky top-0 bg-slate-900">
                <tr className="text-white/40 text-xs uppercase tracking-wider border-b border-white/10">
                    <th className="text-left py-2 px-2">Time</th>
                    <th className="text-left py-2 px-2">Event</th>
                    <th className="text-left py-2 px-2">Symbol</th>
                    <th className="text-left py-2 px-2">Side</th>
                    <th className="text-right py-2 px-2">Price</th>
                    <th className="text-right py-2 px-2">PnL</th>
                    <th className="text-left py-2 px-2">Duration</th>
                    <th className="text-left py-2 px-2">Market</th>
                    <th className="text-left py-2 px-2">Rationale</th>
                </tr>
            </thead>
            <tbody>
                {entries.map((e, i) => {
                    const pnlColor = e.pnl > 0 ? 'text-emerald-400' : e.pnl < 0 ? 'text-red-400' : 'text-white/50';
                    const rowBg = i % 2 === 0 ? 'bg-white/[0.02]' : '';
                    return (
                        <tr key={i} className={`${rowBg} hover:bg-white/5 transition-colors`}>
                            <td className="py-2 px-2 text-white/60 font-mono text-xs">{formatTime(e.timestamp)}</td>
                            <td className="py-2 px-2">
                                <span className={`px-2 py-0.5 rounded text-xs font-medium ${EVENT_COLORS[e.event_type] || 'text-white/50'}`}>
                                    {e.event_type === 'BREAK_EVEN_TRIGGERED' ? 'BE MOVE' : e.event_type?.replace(/_/g, ' ')}
                                </span>
                            </td>
                            <td className="py-2 px-2 text-white/80 text-xs">{shortSymbolName(e.symbol) || '-'}</td>
                            <td className="py-2 px-2">
                                {e.side ? (
                                    <span className={`flex items-center gap-1 text-xs ${e.side === 'LONG' ? 'text-emerald-400' : 'text-red-400'}`}>
                                        {e.side === 'LONG' ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
                                        {e.side}
                                    </span>
                                ) : <span className="text-white/30 text-xs">{e.llm_direction || '-'}</span>}
                            </td>
                            <td className="py-2 px-2 text-right font-mono text-xs text-white/70">
                                {e.entry_price ? e.entry_price.toFixed(2) : e.exit_price ? e.exit_price.toFixed(2) : '-'}
                            </td>
                            <td className={`py-2 px-2 text-right font-mono text-xs ${pnlColor}`}>
                                {e.pnl ? e.pnl.toFixed(2) : '-'}
                            </td>
                            <td className="py-2 px-2 text-xs text-white/50">{formatDuration(e.time_in_trade_s)}</td>
                            <td className="py-2 px-2 text-xs text-white/40">{e.market_state || '-'}</td>
                            <td className="py-2 px-2 text-xs text-white/50 max-w-xs truncate">
                                {sanitizeRationale(e.llm_rationale) || e.risk_reject_reason || e.exit_reason || '-'}
                            </td>
                        </tr>
                    );
                })}
            </tbody>
        </table>
    );
}

function StatCard({ label, value, color }: { label: string; value: string | number; color?: string }) {
    return (
        <div className="bg-white/5 border border-white/10 rounded-lg px-4 py-3">
            <div className="text-xs text-white/40 mb-1">{label}</div>
            <div className={`text-lg font-bold ${color || 'text-white'}`}>{value}</div>
        </div>
    );
}
