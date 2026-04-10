interface RiskPanelProps {
  dailyPnl: number
  maxDrawdown: number
  consecutiveLosses: number
  circuitBreakerActive: boolean
  availableBalance: number
  totalExposure: number
  maxDailyLoss: number
  riskPerTradePct: number
}

export function RiskPanel({
  dailyPnl,
  maxDrawdown,
  consecutiveLosses,
  circuitBreakerActive,
  availableBalance,
  totalExposure,
  maxDailyLoss,
  riskPerTradePct,
}: RiskPanelProps) {
  const dailyLossPct = maxDailyLoss > 0 ? Math.abs(Math.min(0, dailyPnl)) / maxDailyLoss * 100 : 0

  const getRiskColor = () => {
    if (circuitBreakerActive) return 'text-trade-red'
    if (dailyLossPct > 70) return 'text-trade-yellow'
    if (consecutiveLosses >= 3) return 'text-trade-yellow'
    return 'text-trade-green'
  }

  const getRiskStatus = () => {
    if (circuitBreakerActive) return 'CIRCUIT BREAKER ACTIVE'
    if (dailyLossPct > 80) return 'Approaching daily limit'
    if (consecutiveLosses >= 4) return 'High consecutive losses'
    return 'Normal'
  }

  return (
    <div className="bg-trade-card rounded-lg p-4">
      <div className="flex justify-between items-center mb-3">
        <h2 className="text-md font-semibold text-white">Risk Management</h2>
        <span className={`text-xs font-bold ${getRiskColor()}`}>
          ● {getRiskStatus()}
        </span>
      </div>

      <div className="space-y-3">
        {/* Daily P&L */}
        <div>
          <div className="flex justify-between text-sm text-gray-400">
            <span>Daily P&L</span>
            <span className={dailyPnl >= 0 ? 'text-trade-green' : 'text-trade-red'}>
              ₹{dailyPnl.toFixed(2)}
            </span>
          </div>
          <div className="w-full bg-gray-700 rounded-full h-2 mt-1">
            <div
              className={`h-2 rounded-full ${dailyPnl >= 0 ? 'bg-trade-green' : 'bg-trade-red'}`}
              style={{ width: `${Math.min(100, dailyLossPct)}%` }}
            />
          </div>
          <div className="text-xs text-gray-500 mt-0.5">
            Limit: ₹{maxDailyLoss.toFixed(0)} ({dailyLossPct.toFixed(0)}% used)
          </div>
        </div>

        {/* Available Balance */}
        <div className="flex justify-between text-sm">
          <span className="text-gray-400">Available Balance</span>
          <span className="text-white">₹{availableBalance.toFixed(0)}</span>
        </div>

        {/* Total Exposure */}
        <div className="flex justify-between text-sm">
          <span className="text-gray-400">Total Exposure</span>
          <span className="text-white">₹{totalExposure.toFixed(0)}</span>
        </div>

        {/* Max Drawdown */}
        <div className="flex justify-between text-sm">
          <span className="text-gray-400">Max Drawdown</span>
          <span className="text-trade-red">₹{maxDrawdown.toFixed(2)}</span>
        </div>

        {/* Consecutive Losses */}
        <div className="flex justify-between text-sm">
          <span className="text-gray-400">Consecutive Losses</span>
          <span className={consecutiveLosses >= 3 ? 'text-trade-yellow' : 'text-white'}>
            {consecutiveLosses}
          </span>
        </div>

        {/* Risk per Trade */}
        <div className="flex justify-between text-sm">
          <span className="text-gray-400">Risk per Trade</span>
          <span className="text-white">{riskPerTradePct}%</span>
        </div>
      </div>
    </div>
  )
}
