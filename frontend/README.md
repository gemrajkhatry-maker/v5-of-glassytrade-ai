# TradeX AMT Terminal (frontend)

Greenfield React + TypeScript terminal for the TradeX v4 AMT extension. It
renders live AMT analysis as a chart with overlays (VWAP bands, POC/VAH/VAL,
HVN/LVN, IB, absorption markers), a universe scanner, and a positions/orders
readout — all fed by the backend's read-side `AMTService` projection.

This is a **pure read-side UI**: it renders, it never places orders.

## Run

```bash
# 1. Backend (see repo root / trading README for boot options)
#    The FastAPI app is CORS-open, so the dev server can call it cross-origin.
python -m tradex_trading.interface.fastapi_app   # or however you boot the app

# 2. Frontend dev server
cd frontend
npm install
npm run dev          # http://localhost:5173
```

If the backend is not on `http://localhost:8000`, set `VITE_API_BASE`:

```bash
VITE_API_BASE=https://api.example.com npm run dev
```

## Production build

```bash
cd frontend
npm run build        # tsc strict + vite build -> dist/
```

## Backend contract consumed

| Endpoint | Purpose |
|---|---|
| `GET /history/{instrument_id}?timeframe=&limit=` | candle bars |
| `GET /amt/snapshot/{instrument_id}` | latest AMT snapshot |
| `GET /amt/history/{instrument_id}?limit=` | snapshot history (overlay series) |
| `GET /amt/scanner?limit=` | universe scan ranking |
| `GET /positions`, `GET /orders`, `GET /account` | portfolio readout |
| `WS /ws/amt` | live snapshot stream (auto-reconnect) |

All DTO types live in `src/types.ts` and mirror `sdk/services/amt.py`
(`snapshot_to_dict`) 1:1.

## Structure

```
src/
  main.tsx            entry point
  App.tsx             layout + data orchestration (REST + WS)
  api.ts              REST client + ReconnectingSocket (backoff + replay)
  types.ts            DTO types
  components/
    AMTChart.tsx      lightweight-charts candles + AMT overlays
    ScannerPanel.tsx  universe scan table
    SnapshotPanel.tsx analysis readout
    PositionsPanel.tsx positions / orders
```

## Stack

- Vite 5 + React 18 + TypeScript (strict)
- lightweight-charts v4 (candles, line series, price lines, markers)
- No UI kit, no state library — plain hooks + a typed WS client
