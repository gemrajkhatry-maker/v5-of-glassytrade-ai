# Senior Architect Implementation Plan

## GlassyTrade AI — Missing Components with Proper DI & Config Architecture

---

## Executive Summary

This plan addresses **10 identified gaps** in the backend implementation while ensuring all new components follow proper **Dependency Injection (DI)** and **Config-Based Architecture** patterns already established in the codebase.

**Current DI Pattern:** ServiceGraph singleton with FastAPI dependency injection
**Current Config Pattern:** Pydantic Settings + YAML market config + constants.py

---

## Architecture Principles

### 1. Dependency Injection (DI)
```
Domain Layer (Pure Logic) ← Port Interfaces (ABC)
                ↓
Infrastructure Layer (Adapters) ← Implements Ports
                ↓
Application Layer (Orchestration) ← Injected via ServiceGraph
                ↓
API Layer (FastAPI) ← DI via get_service_graph()
```

### 2. Config-Based Architecture
```
┌─────────────────────────────────────────────────────────────┐
│  THREE-LEVEL CONFIG HIERARCHY                               │
│                                                             │
│  Level 1: market_config.yaml (per-exchange thresholds)      │
│  Level 2: Settings (env vars, Pydantic validation)          │
│  Level 3: constants.py (domain-level defaults)              │
│                                                             │
│  Rule: No magic numbers in domain code — import from config │
└─────────────────────────────────────────────────────────────┘
```

---

## Gap #1: Delta Volume Profile (P0 — CRITICAL)

### Problem
Current `create_profile()` builds plain volume profiles. Fabio requires **delta-colored profiles** showing buy_delta vs sell_delta per price level.

### Solution: Delta-Aware Volume Profile

#### Step 1.1 — New Port Interface
```python
# backend/app/domain/ports/profile.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass(frozen=True)
class DeltaBucket:
    price: float
    buy_delta: int      # Aggressive buyers (trades at ask)
    sell_delta: int     # Aggressive sellers (trades at bid)
    net_delta: int      # buy_delta - sell_delta
    total_volume: int   # buy_delta + sell_delta

@dataclass(frozen=True)
class DeltaProfile:
    buckets: tuple[DeltaBucket, ...]
    poc: float
    vah: float
    val: float
    high_sell_delta_zones: tuple[float, ...]  # Trapped sellers = LONG entry
    high_buy_delta_zones: tuple[float, ...]   # Trapped buyers = SHORT entry

class DeltaProfilePort(ABC):
    @abstractmethod
    def build(self, ticks: list[dict], start_ts: float, end_ts: float) -> DeltaProfile: ...
    
    @abstractmethod
    def update_incremental(self, tick: dict) -> None: ...
    
    @abstractmethod
    def get_high_delta_zones(self, direction: str, sigma_mult: float) -> list[float]: ...
```

#### Step 1.2 — Infrastructure Adapter
```python
# backend/app/infrastructure/adapters/delta_profile_adapter.py
from app.domain.ports.profile import DeltaProfilePort, DeltaBucket, DeltaProfile

class DeltaProfileAdapter(DeltaProfilePort):
    def __init__(self, bucket_size: float, sigma_mult: float = 2.5):
        self._bucket_size = bucket_size
        self._sigma_mult = sigma_mult
        self._buckets: dict[float, dict] = {}  # price -> {buy, sell, net, total}
    
    def update_incremental(self, tick: dict) -> None:
        """O(1) per tick — incremental bucket update."""
        price = tick["price"]
        bucket = round(price / self._bucket_size) * self._bucket_size
        
        if bucket not in self._buckets:
            self._buckets[bucket] = {"buy": 0, "sell": 0, "net": 0, "total": 0}
        
        ask_vol = tick.get("ask_vol", 0)
        bid_vol = tick.get("bid_vol", 0)
        
        self._buckets[bucket]["buy"] += ask_vol
        self._buckets[bucket]["sell"] += bid_vol
        self._buckets[bucket]["net"] += ask_vol - bid_vol
        self._buckets[bucket]["total"] += ask_vol + bid_vol
    
    def get_high_delta_zones(self, direction: str, sigma_mult: float = 2.5) -> list[float]:
        """Detect high delta zones per Fabio methodology."""
        if not self._buckets:
            return []
        
        net_deltas = [abs(b["net"]) for b in self._buckets.values()]
        mean_abs = sum(net_deltas) / len(net_deltas)
        threshold = mean_abs * sigma_mult
        
        zones = []
        for price, data in self._buckets.items():
            if direction == "LONG" and data["net"] < -threshold:
                zones.append(price)  # High sell delta = trapped sellers
            elif direction == "SHORT" and data["net"] > threshold:
                zones.append(price)  # High buy delta = trapped buyers
        
        return sorted(zones)
```

#### Step 1.3 — DI Integration
```python
# backend/app/api/dependencies.py — Add to ServiceGraph
class ServiceGraph:
    def __init__(self) -> None:
        # ... existing code ...
        
        # Delta Profile (NEW)
        from app.infrastructure.adapters.delta_profile_adapter import DeltaProfileAdapter
        self.delta_profile: DeltaProfilePort = DeltaProfileAdapter(
            bucket_size=self._get_bucket_size(),
            sigma_mult=settings.DELTA_ZONE_SIGMA_MULT,
        )
```

#### Step 1.4 — Config Addition
```python
# backend/app/config.py — Add to Settings
DELTA_ZONE_SIGMA_MULT: float = Field(default=2.5, ge=1.0, le=5.0)
DELTA_PROFILE_BUCKETS: int = Field(default=200, ge=50, le=500)
```

---

## Gap #2: NPOC Tracker (P0 — CRITICAL)

### Problem
No tracking of previous session POCs that haven't been revisited.

### Solution: NPOC Tracker Service

#### Step 2.1 — New Port Interface
```python
# backend/app/domain/ports/npoc.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass(frozen=True)
class NPOCRecord:
    price: float
    session_date: str
    underlying: str
    is_filled: bool
    filled_at: str | None

class NPOCPort(ABC):
    @abstractmethod
    def add_session_poc(self, underlying: str, date: str, poc: float) -> None: ...
    
    @abstractmethod
    def check_and_fill(self, underlying: str, current_price: float, tick_size: float) -> None: ...
    
    @abstractmethod
    def get_active_npocs(self, underlying: str, current_price: float, lookback_days: int = 5) -> dict: ...
```

#### Step 2.2 — Domain Service
```python
# backend/app/domain/fabio_ai/services/npoc_tracker.py
from app.domain.ports.npoc import NPOCPort, NPOCRecord

class NPOCTracker(NPOCPort):
    """Tracks naked (unfilled) previous session POCs per Fabio methodology."""
    
    def __init__(self, storage_port):
        self._storage = storage_port
        self._active_npocs: dict[str, list[NPOCRecord]] = {}
    
    def add_session_poc(self, underlying: str, date: str, poc: float) -> None:
        """Called at session close — save POC to storage."""
        record = NPOCRecord(
            price=poc, session_date=date, underlying=underlying,
            is_filled=False, filled_at=None
        )
        if underlying not in self._active_npocs:
            self._active_npocs[underlying] = []
        self._active_npocs[underlying].append(record)
        self._storage.save_npoc(underlying, date, poc)
    
    def check_and_fill(self, underlying: str, current_price: float, tick_size: float) -> None:
        """Mark NPOC as filled when price trades through it."""
        zone = tick_size * 2
        for npoc in self._active_npocs.get(underlying, []):
            if not npoc.is_filled and abs(current_price - npoc.price) <= zone:
                npoc = NPOCRecord(
                    price=npoc.price, session_date=npoc.session_date,
                    underlying=npoc.underlying, is_filled=True,
                    filled_at=datetime.now().isoformat()
                )
    
    def get_active_npocs(self, underlying: str, current_price: float, lookback_days: int = 5) -> dict:
        """Return nearest unfilled NPOCs above and below current price."""
        active = [n for n in self._active_npocs.get(underlying, []) 
                  if not n.is_filled]
        above = [n for n in active if n.price > current_price]
        below = [n for n in active if n.price < current_price]
        
        return {
            "nearest_above": min(above, key=lambda x: x.price) if above else None,
            "nearest_below": max(below, key=lambda x: x.price) if below else None,
            "all_active": active
        }
```

#### Step 2.3 — Storage Schema Addition
```sql
-- Add to database.py _SCHEMA
CREATE TABLE IF NOT EXISTS npoc_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    underlying TEXT NOT NULL,
    session_date TEXT NOT NULL,
    poc_price REAL NOT NULL,
    is_filled INTEGER DEFAULT 0,
    filled_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_npoc_underlying_date ON npoc_records(underlying, session_date);
```

---

## Gap #3: Underlying Profile Separation (P0 — CRITICAL)

### Problem
Option premium profiles are corrupted by theta decay. Must profile underlying spot price.

### Solution: UnderlyingProfileRouter

#### Step 3.1 — New Domain Service
```python
# backend/app/domain/fabio_ai/services/underlying_profile_router.py
class UnderlyingProfileRouter:
    """Routes ticks to the correct UNDERLYING's profile engine.
    
    All volume profiles, LVNs, VAH/VAL are built on underlying price.
    Option contract is used only for: position sizing, expiry selection, OI check.
    """
    
    def __init__(self, profile_factory):
        self._engines: dict[str, IncrementalVolumeProfile] = {}
        self._factory = profile_factory  # Injected factory
    
    def get_engine(self, underlying: str) -> IncrementalVolumeProfile:
        if underlying not in self._engines:
            self._engines[underlying] = self._factory.create(underlying)
        return self._engines[underlying]
    
    def update(self, underlying: str, underlying_price: float, volume: int, delta: float):
        """Update underlying's profile with synthetic tick from option chain data."""
        engine = self.get_engine(underlying)
        # Create synthetic OHLC tick at underlying price
        synthetic_tick = OHLC(
            time=datetime.now().isoformat(),
            open=underlying_price, high=underlying_price,
            low=underlying_price, close=underlying_price,
            volume=float(volume), delta=delta,
            taker_buy_volume=max(0, (volume + delta) / 2),
        )
        engine.update(synthetic_tick)
```

#### Step 3.2 — DI Integration
```python
# ServiceGraph
self.underlying_profile_router = UnderlyingProfileRouter(
    profile_factory=IncrementalProfileFactory(bucket_size=self._get_bucket_size())
)
```

---

## Gap #4: Composite/Multi-Session Profile (P1)

### Solution: CompositeProfile Service
```python
# backend/app/domain/fabio_ai/services/composite_profile.py
class CompositeProfile:
    """Merges last N session profiles for weekly bias."""
    
    def __init__(self, window: int = 5):
        self._window = window
    
    def build(self, session_profiles: list[dict]) -> dict:
        """Merge sessions into composite profile."""
        composite = {}
        for session in session_profiles[-self._window:]:
            for price, vol in session.get("profile", {}).items():
                composite[price] = composite.get(price, 0) + vol
        
        return {
            "profile": composite,
            "weekly_poc": self._calc_poc(composite),
            "weekly_vah": self._calc_vah(composite),
            "weekly_val": self._calc_val(composite),
            "weekly_lvns": find_lvns_from_dict(composite),
        }
    
    def apply_weekly_bias(self, direction: str, current_price: float, composite: dict) -> dict:
        """Filter trade against weekly bias."""
        weekly_poc = composite.get("weekly_poc", 0)
        weekly_bias = "LONG" if weekly_poc > current_price else "SHORT"
        
        if direction != weekly_bias:
            return {"aligned": False, "confidence_reduction": 0.5}
        return {"aligned": True, "confidence_boost": 0.5}
```

---

## Gap #5: OI Pressure Calculation (P1)

### Solution: OI Analyzer Service
```python
# backend/app/domain/fabio_ai/services/oi_analyzer.py
class OIAnalyzer:
    """Calculates OI pressure at strikes."""
    
    def __init__(self, market_data_port):
        self._market_data = market_data_port
    
    def check_oi_pressure(self, symbol: str, strike: float, option_type: str) -> dict:
        """Compare current strike OI vs surrounding strikes."""
        oi_data = self._market_data.get_option_chain(symbol)
        
        current_oi = oi_data.get(strike, {}).get(option_type, {}).get("oi", 0)
        surrounding = [
            oi_data.get(strike + i, {}).get(option_type, {}).get("oi", 0)
            for i in [-200, -100, 100, 200]
        ]
        avg_surrounding = sum(surrounding) / len(surrounding) if surrounding else 1
        
        ratio = current_oi / avg_surrounding if avg_surrounding > 0 else 1.0
        
        if ratio >= 3.0:
            return {"pressure": "HIGH", "ratio": ratio, "signal": "RESISTANCE"}
        elif ratio >= 1.5:
            return {"pressure": "MEDIUM", "ratio": ratio, "signal": "CAUTION"}
        return {"pressure": "LOW", "ratio": ratio, "signal": "CLEAR"}
```

---

## Gap #6: Pre-Alert System (P1)

### Solution: AlertManager Service
```python
# backend/app/domain/fabio_ai/services/alert_manager.py
class AlertManager:
    """Manages price alerts for Drive 1 returns."""
    
    def __init__(self, ws_publisher, storage_port):
        self._ws = ws_publisher
        self._storage = storage_port
        self._active_alerts: dict[str, dict] = {}
    
    def set_price_alert(self, symbol: str, price: float, direction: str, 
                        level_type: str, tick_size: float) -> str:
        """Set alert to fire when price returns within 3 ticks of level."""
        alert_id = f"{symbol}_{price}_{level_type}"
        self._active_alerts[alert_id] = {
            "symbol": symbol, "price": price, "direction": direction,
            "level_type": level_type,
            "zone_upper": price + tick_size * 3,
            "zone_lower": price - tick_size * 3,
            "fired": False, "created_at": datetime.now().isoformat()
        }
        return alert_id
    
    def check_alerts(self, symbol: str, current_price: float) -> list[dict]:
        """Check if any alerts should fire."""
        fired = []
        for aid, alert in self._active_alerts.items():
            if alert["symbol"] != symbol or alert["fired"]:
                continue
            if alert["zone_lower"] <= current_price <= alert["zone_upper"]:
                alert["fired"] = True
                fired.append({
                    "type": "PRICE_ALERT", "alert_id": aid,
                    "symbol": symbol, "level_type": alert["level_type"],
                    "level_price": alert["price"], "current_price": current_price,
                    "message": f"Price approaching {alert['level_type']} at {alert['price']}"
                })
        return fired
```

---

## Gap #7: Backtesting Framework (P1)

### Solution: BacktestEngine
```python
# backend/app/application/services/backtest_engine.py
class BacktestEngine:
    """Replay historical ticks through exact same pipeline."""
    
    def __init__(self, service_graph):
        self._graph = service_graph
        self._trades: list[dict] = []
    
    def run(self, tick_data: list[dict], start_date: str, end_date: str) -> dict:
        """Run backtest and return statistical summary."""
        # Reset all state
        session_open = None
        
        for tick in tick_data:
            # Detect session boundary
            if self._is_new_session(tick, session_open):
                self._reset_session_state()
                session_open = tick["time"]
            
            # Run exact same pipeline
            result = self._graph.trading_session.process_tick(
                tick["symbol"], self._tick_to_ohlc(tick), None
            )
            
            if result.get("action") == "TRADE":
                self._record_trade(result, tick)
        
        return self._compute_summary()
    
    def _compute_summary(self) -> dict:
        """Compute statistical summary."""
        if not self._trades:
            return {"error": "No trades generated"}
        
        pnls = [t["pnl"] for t in self._trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        
        return {
            "total_trades": len(self._trades),
            "win_rate": len(wins) / len(self._trades),
            "avg_rr": abs(sum(wins)/len(wins)) / abs(sum(losses)/len(losses)) if losses else 999,
            "total_pnl": round(sum(pnls), 2),
            "max_drawdown": self._calc_max_drawdown(pnls),
            "profit_factor": abs(sum(wins)) / abs(sum(losses)) if losses else 999,
            "second_drive_win_rate": self._calc_drive_win_rate(drive=2),
        }
```

---

## Gap #8: Mid-Trade State Recovery (P1)

### Solution: Enhanced Startup Recovery
```python
# backend/app/application/engine.py — Add to start()
async def start(self) -> None:
    # ... existing code ...
    
    # NEW: Recover open positions from DB
    open_positions = self._graph.storage.load_open_positions()
    for pos_data in open_positions:
        symbol = pos_data["symbol"]
        if symbol not in self._active_symbols:
            self._active_symbols.append(symbol)
        
        # Restore TradeManager state
        self._session_service._trade_manager.register_position(
            position_id=pos_data["id"],
            symbol=symbol,
            side=pos_data["side"],
            entry_price=pos_data["entry_price"],
            stop_loss=pos_data["stop_loss"],
            take_profit=pos_data["take_profit"],
            entry_time=pos_data.get("opened_at"),
        )
    
    if open_positions:
        logger.info("Engine: recovered %d open positions from DB", len(open_positions))
```

---

## Gap #9: MCX Evening Session (P2)

### Solution: Session-Aware Config
```yaml
# market_config.yaml — Add evening session config
MCX:
  sessions:
    morning:
      open: "09:00"
      close: "17:00"
      warmup_minutes: 15
      aggression_sigma: 2.0
    evening:
      open: "17:00"
      close: "23:30"
      warmup_minutes: 10
      aggression_sigma: 2.5  # Higher threshold for lower liquidity
```

---

## Gap #10: Option Chain Scanner Wiring (P2)

### Solution: Enhanced Scanner Integration
```python
# backend/app/domain/fabio_ai/services/scanner_orchestrator.py
class ScannerOrchestrator:
    """Orchestrates option scanning with 5-min rebalance."""
    
    def __init__(self, scanner_service, subscription_manager, config):
        self._scanner = scanner_service
        self._sub_mgr = subscription_manager
        self._config = config
        self._rebalance_interval = config.get("rebalance_interval_sec", 300)
    
    async def rebalance_loop(self):
        """Every 5 minutes: re-scan all underlyings."""
        while True:
            await asyncio.sleep(self._rebalance_interval)
            try:
                new_contracts = self._scanner.scan_top_n(
                    n=self._config["top_n"],
                    underlyings=self._config["underlyings"],
                )
                await self._sub_mgr.rebalance(new_contracts)
            except Exception as e:
                logger.error("Scanner rebalance failed", exc_info=True)
```

---

## Implementation Order

```
Phase 1 (P0 — Week 1):
├── Gap #1: Delta Volume Profile
├── Gap #2: NPOC Tracker
└── Gap #3: Underlying Profile Separation

Phase 2 (P1 — Week 2):
├── Gap #4: Composite Profile
├── Gap #5: OI Pressure
├── Gap #6: Pre-Alert System
├── Gap #7: Backtesting Framework
└── Gap #8: Mid-Trade Recovery

Phase 3 (P2 — Week 3):
├── Gap #9: MCX Evening Session
└── Gap #10: Scanner Wiring
```

---

## Config Changes Required

### config.py Additions
```python
# New settings to add
DELTA_ZONE_SIGMA_MULT: float = Field(default=2.5, ge=1.0, le=5.0)
DELTA_PROFILE_BUCKETS: int = Field(default=200, ge=50, le=500)
NPOC_LOOKBACK_DAYS: int = Field(default=5, ge=1, le=30)
COMPOSITE_SESSION_WINDOW: int = Field(default=5, ge=1, le=10)
ALERT_PROXIMITY_TICKS: int = Field(default=3, ge=1, le=10)
REBALANCE_INTERVAL_SEC: int = Field(default=300, ge=60, le=900)
```

### market_config.yaml Additions
```yaml
MCX:
  delta_zone_sigma_mult: 2.5
  composite_window: 5
  npoc_lookback_days: 5
  sessions:
    morning: { open: "09:00", close: "17:00", aggression_sigma: 2.0 }
    evening: { open: "17:00", close: "23:30", aggression_sigma: 2.5 }
```

---

## Verification Checklist

```
□ All new services implement domain port interfaces (ABC)
□ No direct instantiation in domain layer — all via DI
□ All thresholds imported from config/constants — no magic numbers
□ All new ports added to ServiceGraph
□ All new adapters registered in dependencies.py
□ Storage schema migrations applied
□ Unit tests for each new service
□ Integration tests for end-to-end flow
□ Backtest validation passes
```

---

## Summary

| Gap | Priority | Effort | DI Pattern | Config Source |
|-----|----------|--------|------------|---------------|
| Delta Profile | P0 | 3 days | Port + Adapter | constants.py |
| NPOC Tracker | P0 | 2 days | Port + Service | settings.py |
| Underlying Profile | P0 | 2 days | Router + Factory | market_config.yaml |
| Composite Profile | P1 | 1 day | Domain Service | settings.py |
| OI Pressure | P1 | 1 day | Port + Adapter | market_config.yaml |
| Alert Manager | P1 | 2 days | Domain Service | constants.py |
| Backtesting | P1 | 3 days | Application Service | settings.py |
| Mid-Trade Recovery | P1 | 1 day | Engine Enhancement | — |
| MCX Evening | P2 | 1 day | Config Extension | market_config.yaml |
| Scanner Wiring | P2 | 2 days | Orchestrator | market_config.yaml |

**Total Estimated Effort: 18 days (3 developers × 2 weeks)**