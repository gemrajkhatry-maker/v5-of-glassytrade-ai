import { useState, useEffect } from 'react'
import { SignalPanel } from './components/SignalPanel'
import { PositionPanel } from './components/PositionPanel'
import { RiskPanel } from './components/RiskPanel'
import { VolumeProfileChart } from './components/VolumeProfileChart'
import { CVDChart } from './components/CVDChart'
import { VWAPChart } from './components/VWAPChart'
import { SettingsPanel } from './components/SettingsPanel'
import { TradeJournalView } from './components/TradeJournalView'
import { fetchHealth, fetchSignals, fetchPositions } from './hooks/useWebSocket'
import type { SystemHealth, Signal, Position } from './types'

interface DashboardSettings {
  liveTrading: boolean
  riskPerTradePct: number
  maxDailyLossPct: number
  maxConsecutiveLosses: number
  symbols: string
  exchange: string
  strikePreference: string
}

function App() {
  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [signals, setSignals] = useState<Signal[]>([])
  const [positions, setPositions] = useState<Position[]>([])
  const [activeTab, setActiveTab] = useState<'dashboard' | 'journal'>('dashboard')
  const [loading, setLoading] = useState(true)
  const [showSettings, setShowSettings] = useState(false)
  const [settings, setSettings] = useState<DashboardSettings>({
    liveTrading: false,
    riskPerTradePct: 1.0,
    maxDailyLossPct: 3.0,
    maxConsecutiveLosses: 5,
    symbols: 'NIFTY,BANKNIFTY',
    exchange: 'NSE',
    strikePreference: 'ATM',
  })

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [h, s, p] = await Promise.all([
          fetchHealth(),
          fetchSignals(),
          fetchPositions(),
        ])
        setHealth(h)
        setSignals(s.signals || [])
        setPositions(p.positions || [])
      } catch (err) {
        console.error('Failed to fetch data:', err)
      } finally {
        setLoading(false)
      }
    }

    fetchData()
    const interval = setInterval(fetchData, 5000)
    return () => clearInterval(interval)
  }, [])

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-trade-darker">
        <div className="text-xl text-gray-400">Loading AMT Trading System...</div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-trade-darker">
      {/* Header */}
      <header className="bg-trade-dark border-b border-gray-700 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-bold text-white">AMT Live Trading v2</h1>
          {health && (
            <span
              className={`px-2 py-0.5 text-xs rounded-full ${
                health.status === 'ok'
                  ? 'bg-green-900 text-green-300'
                  : 'bg-red-900 text-red-300'
              }`}
            >
              {health.liveTrading ? '🔴 LIVE' : '🟢 PAPER'}
            </span>
          )}
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-400">
            {health && `Uptime: ${Math.round(health.uptimeSeconds / 60)}m | v${health.version}`}
          </span>
          <div className="flex gap-1">
            <button
              onClick={() => setActiveTab('dashboard')}
              className={`px-3 py-1 rounded text-sm transition ${
                activeTab === 'dashboard'
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
              }`}
            >
              Dashboard
            </button>
            <button
              onClick={() => setActiveTab('journal')}
              className={`px-3 py-1 rounded text-sm transition ${
                activeTab === 'journal'
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
              }`}
            >
              Journal
            </button>
          </div>
          <button
            onClick={() => setShowSettings(!showSettings)}
            className="bg-gray-700 hover:bg-gray-600 text-white px-3 py-1 rounded text-sm transition"
          >
            ⚙️
          </button>
        </div>
      </header>

      {/* Settings Modal */}
      {showSettings && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="max-h-[90vh] overflow-y-auto">
            <SettingsPanel
              initialSettings={settings}
              onSave={(s) => {
                setSettings(s)
                setShowSettings(false)
              }}
            />
          </div>
        </div>
      )}

      {/* Tab Content */}
      {activeTab === 'dashboard' ? (
        <main className="p-4 grid grid-cols-1 xl:grid-cols-4 gap-4">
        {/* Left Column - Charts */}
        <div className="xl:col-span-3 space-y-4">
          {/* VWAP Chart */}
          <VWAPChart data={[]} height={250} width={900} />

          {/* CVD + VP Row */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <CVDChart data={[]} height={150} width={450} />
            <VolumeProfileChart profile={[]} poc={0} vah={0} val={0} currentPrice={0} height={150} width={200} />
          </div>

          {/* Signals + Positions Row */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <SignalPanel signals={signals} />
            <PositionPanel positions={positions} />
          </div>
        </div>

        {/* Right Column - Risk + System Info */}
        <div className="space-y-4">
          <RiskPanel
            dailyPnl={0}
            maxDrawdown={0}
            consecutiveLosses={0}
            circuitBreakerActive={false}
            availableBalance={5000000}
            totalExposure={0}
            maxDailyLoss={150000}
            riskPerTradePct={settings.riskPerTradePct}
          />

          {/* System Info Panel */}
          <div className="bg-trade-card rounded-lg p-4">
            <h2 className="text-md font-semibold text-white mb-3">System Info</h2>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between text-gray-400">
                <span>Status</span>
                <span className="text-white">{health?.status || 'Unknown'}</span>
              </div>
              <div className="flex justify-between text-gray-400">
                <span>Mode</span>
                <span className={health?.liveTrading ? 'text-trade-red' : 'text-trade-green'}>
                  {health?.liveTrading ? 'LIVE' : 'PAPER'}
                </span>
              </div>
              <div className="flex justify-between text-gray-400">
                <span>Version</span>
                <span className="text-white">{health?.version || '-'}</span>
              </div>
              <div className="flex justify-between text-gray-400">
                <span>Exchange</span>
                <span className="text-white">{health ? settings.exchange : '-'}</span>
              </div>
              <div className="flex justify-between text-gray-400">
                <span>Active Signals</span>
                <span className="text-white">{signals.length}</span>
              </div>
              <div className="flex justify-between text-gray-400">
                <span>Open Positions</span>
                <span className="text-white">{positions.length}</span>
              </div>
              <div className="flex justify-between text-gray-400">
                <span>Today's Trades</span>
                <span className="text-white">{trades.length}</span>
              </div>
            </div>
          </div>
        </div>
      </main>
      ) : (
        <main className="p-4 max-w-6xl mx-auto">
          <TradeJournalView trades={trades} />
        </main>
      )}
    </div>
  )
}

export default App
