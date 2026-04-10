interface SignalPanelProps {
  signals: Array<{
    symbol: string
    direction: 'LONG' | 'SHORT'
    entryPrice: number
    stopLoss: number
    takeProfit: number
    confidence: number
    marketState: string
    sessionPhase: string
    riskRewardRatio: number
    ageSeconds: number
    isExpired: boolean
    optionType?: string
  }>
}

export function SignalPanel({ signals }: SignalPanelProps) {
  const activeSignals = signals.filter((s) => !s.isExpired)

  return (
    <div className="bg-trade-card rounded-lg p-4">
      <h2 className="text-md font-semibold text-white mb-3">
        Active Signals ({activeSignals.length})
      </h2>

      {activeSignals.length === 0 ? (
        <div className="text-gray-500 text-sm py-8 text-center">
          No active signals — waiting for AMT setup
        </div>
      ) : (
        <div className="space-y-2 max-h-96 overflow-y-auto">
          {activeSignals.map((sig, i) => (
            <div
              key={i}
              className="bg-trade-dark rounded-lg p-3 border-l-4 border-l-blue-500"
            >
              <div className="flex justify-between items-start">
                <div>
                  <span className="font-medium text-white">{sig.symbol}</span>
                  {sig.optionType && (
                    <span className="ml-2 text-xs text-gray-400">
                      {sig.optionType}
                    </span>
                  )}
                </div>
                <span
                  className={`px-2 py-0.5 text-xs font-bold rounded ${
                    sig.direction === 'LONG'
                      ? 'bg-green-900 text-green-300'
                      : 'bg-red-900 text-red-300'
                  }`}
                >
                  {sig.direction}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-2 mt-2 text-xs text-gray-400">
                <div>
                  Entry: <span className="text-white">{sig.entryPrice.toFixed(2)}</span>
                </div>
                <div>
                  SL: <span className="text-trade-red">{sig.stopLoss.toFixed(2)}</span>
                </div>
                <div>
                  TP: <span className="text-trade-green">{sig.takeProfit.toFixed(2)}</span>
                </div>
                <div>
                  R:R:{' '}
                  <span className="text-white">{sig.riskRewardRatio.toFixed(1)}</span>
                </div>
              </div>

              <div className="flex justify-between items-center mt-2 text-xs text-gray-500">
                <span>
                  {sig.marketState} | {sig.sessionPhase}
                </span>
                <div className="flex items-center gap-2">
                  <div className="w-16 bg-gray-700 rounded-full h-1.5">
                    <div
                      className="bg-blue-500 h-1.5 rounded-full"
                      style={{ width: `${sig.confidence * 100}%` }}
                    />
                  </div>
                  <span>{(sig.confidence * 100).toFixed(0)}%</span>
                  <span>{Math.round(sig.ageSeconds / 60)}m ago</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
