# Gateway API Documentation

## Overview

The Gateway Router exposes **ALL** advanced features built in Sessions 1-8 via REST API endpoints. This provides complete access to:
- ✅ Risk Control (Kill Switch, P&L Exit, Exposure)
- ✅ OMS Advanced (Forever Orders, TWAP, VWAP)
- ✅ Order Book Analytics (Liquidity, Imbalance, Pressure)
- ✅ Broker Gateway Status

**Base URL:** `/api/gateway`

---

## Risk Control Endpoints

### Kill Switch

#### GET `/api/gateway/risk/kill-switch/status`
Get kill switch current status.

**Response:**
```json
{
  "state": "inactive",
  "is_active": false,
  "activation_reason": null,
  "current_pnl": -500.0,
  "order_count": 15
}
```

#### POST `/api/gateway/risk/kill-switch/activate?reason=max_loss_exceeded`
Activate kill switch.

**Query Parameters:**
- `reason` (string): Activation reason
  - `max_loss_exceeded`
  - `max_position_exceeded`
  - `max_order_rate_exceeded`
  - `manual_trigger`
  - `system_error`
  - `risk_breach`

**Response:**
```json
{
  "status": "activated",
  "reason": "max_loss_exceeded"
}
```

#### POST `/api/gateway/risk/kill-switch/deactivate`
Deactivate kill switch (requires authorization).

**Response:**
```json
{
  "status": "deactivated"
}
```

#### POST `/api/gateway/risk/kill-switch/emergency-shutdown?reason=System%20malfunction`
Emergency shutdown with reason.

**Response:**
```json
{
  "status": "shutdown_initiated",
  "reason": "System malfunction"
}
```

---

### P&L Exit Manager

#### GET `/api/gateway/risk/pnl-exit/status`
Get P&L exit status and positions.

**Response:**
```json
{
  "daily_pnl": 2500.0,
  "positions": {
    "RELIANCE": {
      "quantity": 100,
      "entry_price": 2500.0,
      "current_price": 2520.0,
      "unrealized_pnl": 2000.0
    }
  }
}
```

#### POST `/api/gateway/risk/pnl-exit/check`
Check for P&L exits (stop loss, profit target, trailing stop).

**Response:**
```json
{
  "exits": [
    {
      "exit_type": "profit_target",
      "symbol": "RELIANCE",
      "pnl": 2000.0,
      "reason": "Profit target reached for RELIANCE: 2000.0",
      "timestamp": "2024-01-01T10:30:00+00:00"
    }
  ]
}
```

#### POST `/api/gateway/risk/pnl-exit/position?symbol=RELIANCE&quantity=100&price=2500.0&use_trailing_stop=true`
Open position for P&L monitoring.

**Query Parameters:**
- `symbol` (string): Trading symbol
- `quantity` (int): Position quantity
- `price` (float): Entry price
- `use_trailing_stop` (bool): Enable trailing stop

**Response:**
```json
{
  "status": "opened",
  "symbol": "RELIANCE",
  "quantity": 100,
  "entry_price": 2500.0
}
```

---

### Exposure Tracker

#### GET `/api/gateway/risk/exposure/summary`
Get portfolio exposure summary.

**Response:**
```json
{
  "total_exposure": 425000.0,
  "long_exposure": 250000.0,
  "short_exposure": 175000.0,
  "net_exposure": 75000.0,
  "gross_exposure": 425000.0,
  "position_count": 2,
  "margin_utilization": 0.425,
  "sector_breakdown": {
    "ENERGY": 250000.0,
    "IT": 175000.0
  }
}
```

#### POST `/api/gateway/risk/exposure/position?symbol=RELIANCE&quantity=100&price=2500.0&sector=ENERGY`
Add position to exposure tracking.

**Query Parameters:**
- `symbol` (string): Trading symbol
- `quantity` (int): Position quantity (positive=long, negative=short)
- `price` (float): Current price
- `sector` (string, optional): Sector classification

**Response:**
```json
{
  "status": "added",
  "symbol": "RELIANCE",
  "value": 250000.0
}
```

#### GET `/api/gateway/risk/exposure/alerts`
Get exposure limit alerts.

**Response:**
```json
{
  "alerts": [
    "Sector ENERGY concentration 58.82% exceeds limit 30.00%",
    "Position RELIANCE is 58.82% of portfolio (limit: 20.00%)"
  ]
}
```

---

## OMS Advanced Endpoints

### Forever Orders

#### POST `/api/gateway/oms/forever-orders?order_id=forever_1&symbol=RELIANCE&side=BUY&quantity=100&price=2500.0`
Create forever order (persists until cancelled or filled).

**Query Parameters:**
- `order_id` (string): Unique order ID
- `symbol` (string): Trading symbol
- `side` (string): BUY or SELL
- `quantity` (int): Order quantity
- `price` (float): Order price

**Response:**
```json
{
  "status": "created",
  "order_id": "forever_1",
  "symbol": "RELIANCE",
  "side": "BUY",
  "quantity": 100,
  "price": 2500.0
}
```

#### GET `/api/gateway/oms/forever-orders?symbol=RELIANCE`
List all active forever orders.

**Query Parameters:**
- `symbol` (string, optional): Filter by symbol

**Response:**
```json
{
  "orders": [
    {
      "order_id": "forever_1",
      "symbol": "RELIANCE",
      "side": "BUY",
      "quantity": 100,
      "price": 2500.0,
      "state": "active",
      "filled_quantity": 0
    }
  ]
}
```

#### DELETE `/api/gateway/oms/forever-orders/forever_1`
Cancel forever order.

**Response:**
```json
{
  "status": "cancelled",
  "order_id": "forever_1"
}
```

---

### Super Orders (TWAP/VWAP)

#### POST `/api/gateway/oms/super-orders/twap?order_id=twap_1&symbol=RELIANCE&side=BUY&total_quantity=1000&duration_minutes=60&slice_interval_seconds=60`
Create TWAP (Time-Weighted Average Price) order.

**Query Parameters:**
- `order_id` (string): Unique order ID
- `symbol` (string): Trading symbol
- `side` (string): BUY or SELL
- `total_quantity` (int): Total quantity to execute
- `duration_minutes` (int): Execution duration
- `slice_interval_seconds` (int, default=60): Time between slices

**Response:**
```json
{
  "status": "created",
  "order_id": "twap_1",
  "order_type": "TWAP",
  "total_quantity": 1000,
  "duration_minutes": 60,
  "slice_quantity": 16
}
```

#### POST `/api/gateway/oms/super-orders/vwap?order_id=vwap_1&symbol=RELIANCE&side=BUY&total_quantity=1000&participation_rate=0.1&max_slice_quantity=500`
Create VWAP (Volume-Weighted Average Price) order.

**Query Parameters:**
- `order_id` (string): Unique order ID
- `symbol` (string): Trading symbol
- `side` (string): BUY or SELL
- `total_quantity` (int): Total quantity to execute
- `participation_rate` (float): 0.0 to 1.0 (e.g., 0.1 = 10% of market volume)
- `max_slice_quantity` (int, optional): Maximum slice size

**Response:**
```json
{
  "status": "created",
  "order_id": "vwap_1",
  "order_type": "VWAP",
  "total_quantity": 1000,
  "participation_rate": 0.1
}
```

#### GET `/api/gateway/oms/super-orders/twap_1/progress`
Get super order execution progress.

**Response:**
```json
{
  "filled": 320,
  "remaining": 680,
  "percent_complete": 32.0
}
```

#### DELETE `/api/gateway/oms/super-orders/twap_1`
Cancel super order.

**Response:**
```json
{
  "status": "cancelled",
  "order_id": "twap_1"
}
```

---

## Order Book Analytics Endpoints

### Order Book

#### GET `/api/gateway/orderbook/RELIANCE`
Get order book snapshot.

**Response:**
```json
{
  "symbol": "RELIANCE",
  "bids": [
    {"price": 2500.0, "quantity": 500, "order_count": 5},
    {"price": 2490.0, "quantity": 300, "order_count": 3}
  ],
  "asks": [
    {"price": 2510.0, "quantity": 400, "order_count": 4},
    {"price": 2520.0, "quantity": 600, "order_count": 6}
  ]
}
```

#### POST `/api/gateway/orderbook/RELIANCE/add-order?order_id=1&price=2500.0&quantity=100&side=BID`
Add order to order book.

**Query Parameters:**
- `order_id` (string): Unique order ID
- `price` (float): Order price
- `quantity` (int): Order quantity
- `side` (string): BID or ASK

**Response:**
```json
{
  "status": "added",
  "symbol": "RELIANCE",
  "order_id": "1"
}
```

---

### Liquidity Metrics

#### GET `/api/gateway/orderbook/RELIANCE/liquidity`
Get liquidity metrics.

**Response:**
```json
{
  "bid_volume": 800,
  "ask_volume": 1000,
  "total_volume": 1800,
  "bid_concentration": 0.625,
  "ask_concentration": 0.4,
  "bid_vwap": 2495.0,
  "ask_vwap": 2515.0,
  "liquidity_imbalance": -0.111
}
```

---

### Imbalance

#### GET `/api/gateway/orderbook/RELIANCE/imbalance`
Get order book imbalance.

**Response:**
```json
{
  "current_imbalance": 0.6,
  "volume_delta": 480,
  "direction": "bid_heavy"
}
```

**Direction Values:**
- `bid_heavy`: More volume on bid side
- `ask_heavy`: More volume on ask side
- `balanced`: Roughly equal

---

### Queue Pressure

#### GET `/api/gateway/orderbook/RELIANCE/pressure`
Get queue pressure metrics.

**Response:**
```json
{
  "pressure_score": 65.5,
  "bid_depth": 800,
  "ask_depth": 420,
  "depletion_rate": -0.15,
  "is_replenishing": false,
  "trend": "decreasing"
}
```

**Pressure Score:**
- 0-30: Ask pressure (selling pressure)
- 30-70: Balanced
- 70-100: Bid pressure (buying pressure)

**Trend Values:**
- `increasing`: Pressure building
- `decreasing`: Pressure easing
- `stable`: No significant change

---

## Broker Gateway Status

### GET `/api/gateway/status`
Get broker gateway operational status.

**Response:**
```json
{
  "status": "operational",
  "features": {
    "risk_control": true,
    "oms_advanced": true,
    "orderbook_analytics": true,
    "replay_infrastructure": false,
    "observability": true
  }
}
```

### GET `/api/gateway/features`
List all available features.

**Response:**
```json
{
  "risk_control": {
    "kill_switch": true,
    "pnl_exit": true,
    "exposure_tracking": true
  },
  "oms_advanced": {
    "forever_orders": true,
    "twap": true,
    "vwap": true
  },
  "orderbook_analytics": {
    "liquidity": true,
    "imbalance": true,
    "queue_pressure": true,
    "execution_pressure": true
  },
  "observability": {
    "tracing": true,
    "metrics": true,
    "alerts": true
  }
}
```

---

## Usage Examples

### Python (requests)

```python
import requests

BASE_URL = "http://localhost:8000/api/gateway"

# Activate kill switch
response = requests.post(
    f"{BASE_URL}/risk/kill-switch/activate",
    params={"reason": "max_loss_exceeded"}
)

# Create TWAP order
response = requests.post(
    f"{BASE_URL}/oms/super-orders/twap",
    params={
        "order_id": "twap_1",
        "symbol": "RELIANCE",
        "side": "BUY",
        "total_quantity": 1000,
        "duration_minutes": 60
    }
)

# Get order book analytics
response = requests.get(f"{BASE_URL}/orderbook/RELIANCE/liquidity")
liquidity = response.json()
print(f"Bid volume: {liquidity['bid_volume']}")
```

### cURL

```bash
# Check kill switch status
curl http://localhost:8000/api/gateway/risk/kill-switch/status

# Create forever order
curl -X POST "http://localhost:8000/api/gateway/oms/forever-orders?order_id=forever_1&symbol=RELIANCE&side=BUY&quantity=100&price=2500.0"

# Get pressure metrics
curl http://localhost:8000/api/gateway/orderbook/RELIANCE/pressure
```

### JavaScript (fetch)

```javascript
const BASE_URL = "http://localhost:8000/api/gateway";

// Get exposure summary
const response = await fetch(`${BASE_URL}/risk/exposure/summary`);
const exposure = await response.json();
console.log(`Net exposure: ${exposure.net_exposure}`);

// Cancel super order
await fetch(`${BASE_URL}/oms/super-orders/twap_1`, {
  method: "DELETE"
});
```

---

## Error Responses

### 400 Bad Request
```json
{
  "detail": "Order forever_1 already exists"
}
```

### 404 Not Found
```json
{
  "detail": "Order book not found"
}
```

### 500 Internal Server Error
```json
{
  "detail": "Internal server error"
}
```

---

## Testing

Once backend is running, test endpoints:

```bash
# Health check
curl http://localhost:8000/api/gateway/status

# List features
curl http://localhost:8000/api/gateway/features

# Test kill switch
curl -X POST "http://localhost:8000/api/gateway/risk/kill-switch/activate?reason=manual_trigger"

# Test order book
curl -X POST "http://localhost:8000/api/gateway/orderbook/RELIANCE/add-order?order_id=1&price=2500.0&quantity=100&side=BID"
curl http://localhost:8000/api/gateway/orderbook/RELIANCE/liquidity
```

---

## Architecture

All endpoints use lazy initialization - services are created on first request and reused as singletons. This ensures:
- Fast startup (no pre-initialization)
- Shared state across requests
- Production-ready singleton pattern

**Services Initialized:**
- `KillSwitchEngine` - Risk control
- `PnLExitManager` - P&L monitoring
- `ExposureTracker` - Portfolio exposure
- `ForeverOrderEngine` - Persistent orders
- `SuperOrderEngine` - TWAP/VWAP execution
- `OrderBookAPI` - Order book analytics

---

## Next Steps

1. **WebSocket Streams** - Real-time updates for pressure, imbalance, alerts
2. **Replay API** - Expose replay infrastructure endpoints
3. **Observability API** - Tracing and metrics endpoints
4. **Admin Dashboard** - System management UI
5. **Authentication** - JWT protection for sensitive endpoints
