import { useState } from 'react'

interface TradeRecord {
  tradeId: string
  symbol: string
  side: string
  entryPrice: number
  exitPrice: number
  pnl: number
  entryTime: number
  exitTime: number
  exitReason: string
  durationMinutes: number
  marketState: string
  setupType: string
}

interface TradeJournalViewProps {
  trades: TradeRecord[]
}

export function TradeJournalView({ trades }: TradeJournalViewProps) {
  const [sortBy, setSortBy] = useState<string>('entryTime')
  const [filter, setFilter] = useState<string>('')

  const filtered = trades
    .filter((t) => !filter || t.symbol.toLowerCase().includes(filter.toLowerCase()))
    .sort((a, b) => {
      if (sortBy === 'entryTime') return b.entryTime - a.entryTime
      if (sortBy === 'pnl') return b.pnl - a.pnl
      if (sortBy === 'duration') return b.durationMinutes - a.durationMinutes
      return 0
    })

  const totalPnl = trades.reduce((sum, t) => sum + t.pnl, 0)
  const wins = trades.filter((t) => t.pnl > 0).length
  const losses = trades.filter((t) => t.pnl <= 0).length
  const winRate = trades.length > 0 ? (wins / trades.length) * 100 : 0

  const exportCSV = () => {
    const headers = ['Trade ID', 'Symbol', 'Side', 'Entry', 'Exit', 'P&L', 'Reason', 'Duration (min)', 'Setup']
    const rows = filtered.map((t) => [
      t.tradeId, t.symbol, t.side, t.entryPrice, t.exitPrice,
      t.pnl.toFixed(2), t.exitReason, t.durationMinutes.toFixed(0), t.setupType,
    ])
    const csv = [headers, ...rows].map((r) => r.join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `trade_journal_${new Date().toISOString().split('T')[0]}.csv`
    a.click()
  }

  return (
    <div className="bg-trade-card rounded-lg p-4">
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-bold text-white">Trade Journal</h2>
        <button
          onClick={exportCSV}
          className="bg-blue-600 hover:bg-blue-700 text-white px-3 py-1 rounded text-sm transition"
        >
          Export CSV
        </button>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <div className="bg-trade-dark rounded p-3 text-center">
          <div className="text-xs text-gray-500">Total Trades</div>
          <div className="text-xl font-bold text-white">{trades.length}</div>
        </div>
        <div className="bg-trade-dark rounded p-3 text-center">
          <div className="text-xs text-gray-500">Win Rate</div>
          <div className={`text-xl font-bold ${winRate >= 50 ? 'text-trade-green' : 'text-trade-red'}`}>
            {winRate.toFixed(1)}%
          </div>
        </div>
        <div className="bg-trade-dark rounded p-3 text-center">
          <div className="text-xs text-gray-500">Total P&L</div>
          <div className={`text-xl font-bold ${totalPnl >= 0 ? 'text-trade-green' : 'text-trade-red'}`}>
            ₹{totalPnl.toFixed(2)}
          </div>
        </div>
        <div className="bg-trade-dark rounded p-3 text-center">
          <div className="text-xs text-gray-500">W / L</div>
          <div className="text-xl font-bold text-white">
            <span className="text-trade-green">{wins}</span>
            {' / '}
            <span className="text-trade-red">{losses}</span>
          </div>
        </div>
      </div>

      {/* Filter */}
      <div className="mb-3">
        <input
          type="text"
          placeholder="Filter by symbol..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="w-full bg-trade-dark border border-gray-600 rounded px-3 py-2 text-white text-sm"
        />
      </div>

      {/* Sort Controls */}
      <div className="flex gap-2 mb-3 text-xs text-gray-400">
        <span>Sort:</span>
        {['entryTime', 'pnl', 'duration'].map((s) => (
          <button
            key={s}
            onClick={() => setSortBy(s)}
            className={`px-2 py-0.5 rounded ${
              sortBy === s ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-400'
            }`}
          >
            {s === 'entryTime' ? 'Date' : s === 'pnl' ? 'P&L' : 'Duration'}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-400 border-b border-gray-700">
              <th className="text-left py-2 px-2">Date</th>
              <th className="text-left py-2 px-2">Symbol</th>
              <th className="text-left py-2 px-2">Side</th>
              <th className="text-right py-2 px-2">Entry</th>
              <th className="text-right py-2 px-2">Exit</th>
              <th className="text-right py-2 px-2">P&L</th>
              <th className="text-left py-2 px-2">Reason</th>
              <th className="text-right py-2 px-2">Duration</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={8} className="text-center py-8 text-gray-500">
                  No trades yet
                </td>
              </tr>
            ) : (
              filtered.map((t) => (
                <tr key={t.tradeId} className="border-b border-gray-800 hover:bg-trade-dark">
                  <td className="py-2 px-2 text-gray-400">
                    {new Date(t.entryTime * 1000).toLocaleDateString()}
                  </td>
                  <td className="py-2 px-2 text-white font-medium">{t.symbol}</td>
                  <td className="py-2 px-2">
                    <span
                      className={`px-1.5 py-0.5 text-xs rounded ${
                        t.side === 'BUY'
                          ? 'bg-green-900 text-green-300'
                          : 'bg-red-900 text-red-300'
                      }`}
                    >
                      {t.side}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-right text-gray-300">
                    {t.entryPrice.toFixed(2)}
                  </td>
                  <td className="py-2 px-2 text-right text-gray-300">
                    {t.exitPrice.toFixed(2)}
                  </td>
                  <td className={`py-2 px-2 text-right font-bold ${
                    t.pnl >= 0 ? 'text-trade-green' : 'text-trade-red'
                  }`}>
                    ₹{t.pnl.toFixed(2)}
                  </td>
                  <td className="py-2 px-2 text-gray-400 text-xs">{t.exitReason}</td>
                  <td className="py-2 px-2 text-right text-gray-400">
                    {t.durationMinutes.toFixed(0)}m
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
