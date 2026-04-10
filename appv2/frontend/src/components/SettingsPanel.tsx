import { useState } from 'react'

interface SettingsState {
  liveTrading: boolean
  riskPerTradePct: number
  maxDailyLossPct: number
  maxConsecutiveLosses: number
  symbols: string
  exchange: string
  strikePreference: string
}

interface SettingsPanelProps {
  initialSettings: SettingsState
  onSave: (settings: SettingsState) => void
}

export function SettingsPanel({ initialSettings, onSave }: SettingsPanelProps) {
  const [settings, setSettings] = useState<SettingsState>(initialSettings)
  const [saved, setSaved] = useState(false)

  const handleSave = () => {
    onSave(settings)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="bg-trade-card rounded-lg p-6 max-w-2xl">
      <h2 className="text-lg font-bold text-white mb-4">Trading Settings</h2>

      <div className="space-y-4">
        {/* Live Trading Toggle */}
        <div className="flex items-center justify-between p-3 bg-trade-dark rounded-lg">
          <div>
            <label className="text-white font-medium">Live Trading Mode</label>
            <p className="text-xs text-gray-500">
              Enable to place real orders with Dhan broker
            </p>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={settings.liveTrading}
              onChange={(e) =>
                setSettings({ ...settings, liveTrading: e.target.checked })
              }
              className="sr-only peer"
            />
            <div className="w-11 h-6 bg-gray-600 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-red-600"></div>
          </label>
        </div>

        {/* Risk Parameters */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm text-gray-400 mb-1">
              Risk per Trade (%)
            </label>
            <input
              type="number"
              value={settings.riskPerTradePct}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  riskPerTradePct: parseFloat(e.target.value) || 0,
                })
              }
              className="w-full bg-trade-dark border border-gray-600 rounded px-3 py-2 text-white"
              min="0.1"
              max="5"
              step="0.1"
            />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">
              Max Daily Loss (%)
            </label>
            <input
              type="number"
              value={settings.maxDailyLossPct}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  maxDailyLossPct: parseFloat(e.target.value) || 0,
                })
              }
              className="w-full bg-trade-dark border border-gray-600 rounded px-3 py-2 text-white"
              min="1"
              max="10"
              step="0.5"
            />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">
              Max Consecutive Losses
            </label>
            <input
              type="number"
              value={settings.maxConsecutiveLosses}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  maxConsecutiveLosses: parseInt(e.target.value) || 0,
                })
              }
              className="w-full bg-trade-dark border border-gray-600 rounded px-3 py-2 text-white"
              min="1"
              max="10"
            />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Exchange</label>
            <select
              value={settings.exchange}
              onChange={(e) =>
                setSettings({ ...settings, exchange: e.target.value })
              }
              className="w-full bg-trade-dark border border-gray-600 rounded px-3 py-2 text-white"
            >
              <option value="NSE">NSE (NIFTY, BANKNIFTY)</option>
              <option value="MCX">MCX (CRUDEOIL, GOLD)</option>
            </select>
          </div>
        </div>

        {/* Symbols */}
        <div>
          <label className="block text-sm text-gray-400 mb-1">
            Symbols (comma-separated)
          </label>
          <input
            type="text"
            value={settings.symbols}
            onChange={(e) => setSettings({ ...settings, symbols: e.target.value })}
            className="w-full bg-trade-dark border border-gray-600 rounded px-3 py-2 text-white"
            placeholder="NIFTY,BANKNIFTY,CRUDEOIL"
          />
        </div>

        {/* Strike Preference */}
        <div>
          <label className="block text-sm text-gray-400 mb-1">
            Strike Preference
          </label>
          <div className="flex gap-4">
            {['ATM', 'ITM'].map((pref) => (
              <label key={pref} className="flex items-center gap-2">
                <input
                  type="radio"
                  name="strikePref"
                  value={pref}
                  checked={settings.strikePreference === pref}
                  onChange={() =>
                    setSettings({ ...settings, strikePreference: pref })
                  }
                  className="text-blue-500"
                />
                <span className="text-white">{pref}</span>
                <span className="text-xs text-gray-500">
                  {pref === 'ATM' ? '(Max gamma, scalping)' : '(Delta 0.60-0.75, directional)'}
                </span>
              </label>
            ))}
          </div>
        </div>

        {/* Save Button */}
        <div className="flex items-center gap-4 pt-2">
          <button
            onClick={handleSave}
            className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-2 rounded-lg font-medium transition"
          >
            Save Settings
          </button>
          {saved && (
            <span className="text-trade-green text-sm">✓ Settings saved</span>
          )}
        </div>
      </div>
    </div>
  )
}
