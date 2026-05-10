# Dhan Broker API Mapping

## Brokers vs BrokersV2 API Differences

The CLI uses the `brokers/` infrastructure (not `brokersv2/`), which has different method signatures.

### Method Name Mapping

| Old (Wrong) | New (Correct) | Notes |
|-------------|---------------|-------|
| `broker.get_quote()` | `broker.quote()` | Returns Quote object |
| `broker.get_option_chain()` | `broker.option_chain()` | Returns OptionChain object |
| `broker.historical(start_date=..., end_date=...)` | `broker.historical(from_date=..., to_date=...)` | Returns DataFrame |

### Return Types

#### Quote Object
```python
quote = broker.quote("CRUDEOIL")

# Attributes (use getattr for safety):
quote.ltp          # Last traded price
quote.bid_price    # Bid price
quote.ask_price    # Ask price
quote.bid_qty      # Bid quantity
quote.ask_qty      # Ask quantity
quote.volume       # Volume
quote.high         # High price
quote.low          # Low price
quote.prev_close   # Previous close
```

**Usage in CLI:**
```python
# ✅ Correct
ltp = getattr(quote, 'ltp', 0)

# ❌ Wrong (old code)
ltp = quote.get('last_price', 0)
```

#### OptionChain Object
```python
chain = broker.option_chain("NIFTY")

# Attributes:
chain.calls      # List of call options
chain.puts       # List of put options
chain.spot_price # Spot price of underlying
```

**Individual Option Attributes:**
```python
for call in chain.calls:
    call.strike    # Strike price
    call.ltp       # Last traded price
    call.bid       # Bid price
    call.ask       # Ask price
    call.volume    # Volume
    call.oi        # Open interest
```

**Usage in CLI:**
```python
# ✅ Correct - Convert to list of dicts
chain = []
for call in chain_obj.calls:
    chain.append({
        "option_type": "CE",
        "strike": getattr(call, 'strike', 0),
        "ltp": getattr(call, 'ltp', 0),
        # ... etc
    })

# ❌ Wrong (old code)
for option in chain[:30]:
    strike = option.get('strike', 0)
```

#### Historical DataFrame
```python
df = broker.historical(
    symbol="CRUDEOIL",
    from_date="2024-01-01",  # ✅ from_date (not start_date)
    to_date="2024-01-31",    # ✅ to_date (not end_date)
    interval="5m"
)

# Returns pandas DataFrame with columns:
# open, high, low, close, volume
```

**Usage in CLI:**
```python
# ✅ Correct
df = broker.historical(
    symbol=symbol,
    from_date=start_date.strftime("%Y-%m-%d"),
    to_date=end_date.strftime("%Y-%m-%d"),
    interval="5m"
)

# ❌ Wrong (old code)
df = broker.historical(
    symbol=symbol,
    start_date=...,  # Wrong parameter name!
    end_date=...,    # Wrong parameter name!
    interval="5m"
)
```

## CLI Implementation Pattern

### Data Access Pattern

```python
# 1. Get broker instance
broker = DhanBrokerCLI.get_broker()

# 2. Call method (synchronous)
quote = broker.quote(symbol)

# 3. Access attributes safely
ltp = getattr(quote, 'ltp', 0)
```

### Options Chain Pattern

```python
# Fetch chain
chain_obj = broker.option_chain(underlying)

# Convert to list of dicts for analytics
chain = []
for call in chain_obj.calls:
    chain.append({
        "option_type": "CE",
        "strike": getattr(call, 'strike', 0),
        "ltp": getattr(call, 'ltp', 0),
        "price": getattr(call, 'ltp', 0),  # For OI analytics
        "oi": getattr(call, 'oi', 0),
        "volume": getattr(call, 'volume', 0)
    })
for put in chain_obj.puts:
    chain.append({
        "option_type": "PE",
        "strike": getattr(put, 'strike', 0),
        "ltp": getattr(put, 'ltp', 0),
        "price": getattr(put, 'ltp', 0),
        "oi": getattr(put, 'oi', 0),
        "volume": getattr(put, 'volume', 0)
    })
```

### Historical Data Pattern

```python
# Fetch DataFrame
df = broker.historical(
    symbol=symbol,
    from_date=start_date.strftime("%Y-%m-%d"),
    to_date=end_date.strftime("%Y-%m-%d"),
    interval="5m"
)

# Convert to trades for VWAP
trades = []
for idx, row in df.iterrows():
    trades.append({
        "timestamp": idx,
        "price": row["close"],
        "volume": int(row["volume"])
    })

# Calculate VWAP
vwap = calculate_session_vwap(symbol, trades)
```

## Common Errors Fixed

### Error 1: `get_quote()` doesn't exist
```
✗ Error: 'DhanFacade' object has no attribute 'get_quote'
```
**Fix:** Use `broker.quote()` instead

### Error 2: `start_date` parameter
```
✗ Error: DhanFacade.historical() got an unexpected keyword argument 'start_date'
```
**Fix:** Use `from_date` instead of `start_date`

### Error 3: Dict access on objects
```
✗ Error: 'Quote' object has no attribute 'get'
```
**Fix:** Use `getattr(quote, 'ltp', 0)` instead of `quote.get('last_price', 0)`

### Error 4: OptionChain iteration
```
✗ Error: object of type 'OptionChain' has no len()
```
**Fix:** Check `len(chain.calls)` and iterate `chain.calls` and `chain.puts` separately

## Source Files

- DhanFacade: `brokers/broker/dhan/application/facade.py`
- Quote/OptionChain: `brokers/broker/entities.py`
- CLI: `brokersv2/cli/main.py`

## Testing

All analytics modules still pass:
```bash
python -m pytest brokersv2/tests/analytics/ -q
# 144 passed
```

CLI imports successfully:
```bash
cd brokersv2 && python -c "from cli.main import *; print('✓ Success')"
```
