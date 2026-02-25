import React, { useState, useEffect } from 'react';
import { ArrowLeft, ChevronLeft, ChevronRight, TrendingUp, TrendingDown, Filter } from 'lucide-react';

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

const EVENT_COLORS: Record<string, string> = {
    SIGNAL_GENERATED: 'text-blue-400 bg-blue-500/10',
    ENTRY_EXECUTED: 'text-emerald-400 bg-emerald-500/10',
    ENTRY_REJECTED: 'text-orange-400 bg-orange-500/10',
    EXIT: 'text-purple-400 bg-purple-500/10',
    OVERSEER_ACTION: 'text-cyan-400 bg-cyan-500/10',
};

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
    const [summary, setSummary] = useState<JournalSummary | null>(null);
    const [entries, setEntries] = useState<JournalEntry[]>([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState<string>('ALL');

    useEffect(() => {
        setLoading(true);
        Promise.all([
            fetch(`/api/ai/journal?date=${date}`).then(r => r.json()),
            fetch(`/api/ai/journal/summary?date=${date}`).then(r => r.json()),
        ]).then(([j, s]) => {
            setEntries(j.entries || []);
            setSummary(s);
        }).catch(console.error).finally(() => setLoading(false));
    }, [date]);

    const shiftDate = (days: number) => {
        const d = new Date(date);
        d.setDate(d.getDate() + days);
        setDate(d.toISOString().slice(0, 10));
    };

    const filtered = filter === 'ALL' ? entries : entries.filter(e => e.event_type === filter);

    return (
        <div className="w-screen h-screen bg-slate-900 text-white flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 bg-slate-900/80 backdrop-blur">
                <div className="flex items-center gap-4">
                    <button onClick={onBack} className="p-2 rounded-lg hover:bg-white/10 transition-colors">
                        <ArrowLeft size={20} />
                    </button>
                    <h1 className="text-lg font-bold tracking-wide">Trade Journal</h1>
                </div>
                <div className="flex items-center gap-2">
                    <button onClick={() => shiftDate(-1)} className="p-1.5 rounded hover:bg-white/10"><ChevronLeft size={18} /></button>
                    <input
                        type="date"
                        value={date}
                        onChange={e => setDate(e.target.value)}
                        className="bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-sm text-white"
                    />
                    <button onClick={() => shiftDate(1)} className="p-1.5 rounded hover:bg-white/10"><ChevronRight size={18} /></button>
                </div>
            </div>

            {/* Summary Cards */}
            {summary && (
                <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3 px-6 py-4">
                    <StatCard label="Signals" value={summary.total_signals} />
                    <StatCard label="Entries" value={summary.total_entries} />
                    <StatCard label="Wins" value={summary.wins} color="text-emerald-400" />
                    <StatCard label="Losses" value={summary.losses} color="text-red-400" />
                    <StatCard label="Win Rate" value={`${(summary.win_rate * 100).toFixed(1)}%`}
                        color={summary.win_rate >= 0.5 ? 'text-emerald-400' : 'text-red-400'} />
                    <StatCard label="Total PnL" value={`Rs ${summary.total_pnl.toFixed(2)}`}
                        color={summary.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'} />
                </div>
            )}

            {/* Filter Bar */}
            <div className="px-6 pb-3 flex items-center gap-2">
                <Filter size={14} className="text-white/40" />
                {['ALL', 'SIGNAL_GENERATED', 'ENTRY_EXECUTED', 'ENTRY_REJECTED', 'EXIT', 'OVERSEER_ACTION'].map(f => (
                    <button key={f} onClick={() => setFilter(f)}
                        className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${filter === f ? 'bg-purple-500/20 text-purple-300' : 'bg-white/5 text-white/40 hover:text-white/70'}`}>
                        {f === 'ALL' ? 'All' : f.replace(/_/g, ' ')}
                    </button>
                ))}
                <span className="ml-auto text-xs text-white/30">{filtered.length} entries</span>
            </div>

            {/* Table */}
            <div className="flex-1 overflow-y-auto px-6 pb-6">
                {loading ? (
                    <div className="flex items-center justify-center h-40 text-white/40">Loading...</div>
                ) : filtered.length === 0 ? (
                    <div className="flex items-center justify-center h-40 text-white/30">No journal entries for {date}</div>
                ) : (
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
                            {filtered.map((e, i) => {
                                const pnlColor = e.pnl > 0 ? 'text-emerald-400' : e.pnl < 0 ? 'text-red-400' : 'text-white/50';
                                const rowBg = i % 2 === 0 ? 'bg-white/[0.02]' : '';
                                return (
                                    <tr key={i} className={`${rowBg} hover:bg-white/5 transition-colors`}>
                                        <td className="py-2 px-2 text-white/60 font-mono text-xs">{formatTime(e.timestamp)}</td>
                                        <td className="py-2 px-2">
                                            <span className={`px-2 py-0.5 rounded text-xs font-medium ${EVENT_COLORS[e.event_type] || 'text-white/50'}`}>
                                                {e.event_type?.replace(/_/g, ' ')}
                                            </span>
                                        </td>
                                        <td className="py-2 px-2 text-white/80 text-xs">{e.symbol || '-'}</td>
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
                                            {e.llm_rationale || e.risk_reject_reason || e.exit_reason || '-'}
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
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
