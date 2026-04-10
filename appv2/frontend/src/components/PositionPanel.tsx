import { Position } from '../types'

interface PositionPanelProps {
  positions: Position[]
}

export function PositionPanel({ positions }: PositionPanelProps) {
  const totalPnl = positions.reduce((sum, p) => sum + p.netPnl, 0)

  return (
    <div className="bg-trade-card rounded-lg p-4">
      <div className="flex justify-between items-center mb-3">
        <h2 className="text-md font-semibold text-white">
          Open Positions ({positions.length})
        </h2>
        <span
          className={`text-sm font-bold ${
            totalPnl >= 0 ? 'text-trade-green' : 'text-trade-red'
          }`}
        >
          P&L: ₹{totalPnl.toFixed(2)}
        </span>
      </div>

      {positions.length === 0 ? (
        <div className="text-gray-500 text-sm py-8 text-center">
          No open positions
        </div>
      ) : (
        <div className="space-y-2 max-h-96 overflow-y-auto">
          {positions.map((pos) => (
            <div
              key={pos.tradeId}
              className="bg-trade-dark rounded-lg p-3 border border-gray-700"
            >
              <div className="flex justify-between items-start">
                <div>
                  <span className="font-medium text-white">{pos.symbol}</span>
                  <span
                    className={`ml-2 px-1.5 py-0.5 text-xs rounded ${
                      pos.side === 'BUY'
                        ? 'bg-green-900 text-green-300'
                        : 'bg-red-900 text-red-300'
                    }`}
                  >
                    {pos.side} × {pos.lots}L
                  </span>
                </div>
                <span
                  className={`font-bold ${
                    pos.netPnl >= 0 ? 'text-trade-green' : 'text-trade-red'
                  }`}
                >
                  ₹{pos.netPnl.toFixed(2)}
                </span>
              </div>

              <div className="grid grid-cols-3 gap-2 mt-2 text-xs text-gray-400">
                <div>
                  Entry:{' '}
                  <span className="text-white">{pos.entryPrice.toFixed(2)}</span>
                </div>
                <div>
                  SL:{' '}
                  <span className="text-trade-red">{pos.stopLoss.toFixed(2)}</span>
                </div>
                <div>
                  TP:{' '}
                  <span className="text-trade-green">
                    {pos.takeProfit.toFixed(2)}
                  </span>
                </div>
              </div>

              {pos.trailPrice > 0 && (
                <div className="text-xs text-gray-500 mt-1">
                  Trail: <span className="text-yellow-400">{pos.trailPrice.toFixed(2)}</span>
                </div>
              )}

              <div className="text-xs text-gray-500 mt-1">
                Duration: {pos.durationMinutes.toFixed(0)}m
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
