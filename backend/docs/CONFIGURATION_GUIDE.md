# Configuration System Guide

GlassyTrade AI now uses a professional YAML-based configuration system with mode-based selection. This eliminates the need to manually edit `.env` files when switching between trading modes.

## Quick Start

### Switch to MCX Mode

```bash
cd backend
./venv/bin/python scripts/select_mode.py --env paper --strategy mcx_options
./venv/bin/uvicorn app.main:app --port 9090
```

### Switch to NSE Mode

```bash
cd backend
./venv/bin/python scripts/select_mode.py --env paper --strategy nse_options
./venv/bin/uvicorn app.main:app --port 9090
```

### Using Startup Scripts

```bash
# MCX mode
./backend/scripts/start_mcx.sh

# NSE mode
./backend/scripts/start_nse.sh
```

## Configuration Hierarchy

The system loads configuration in this order (later files override earlier ones):

1. **base.yaml** - All defaults (493 lines)
   - Location: `backend/config/base.yaml`
   - Contains: Global constants, AMT thresholds, risk parameters

2. **environments/{env}.yaml** - Environment overrides
   - Location: `backend/config/environments/`
   - Files: `development.yaml`, `paper.yaml`, `live.yaml`
   - Controls: Log level, broker mode, risk settings

3. **strategies/{strategy}.yaml** - Strategy-specific settings
   - Location: `backend/config/strategies/`
   - Files: `mcx_options.yaml`, `nse_options.yaml`
   - Controls: Exchange, symbols, scanner config, feature flags

4. **.env** - Secrets only (API keys, tokens)
   - Location: project root `.env`
   - Contains: DHAN credentials, API keys, LLM paths

## Available Modes

### Environments

| Environment | Use Case | Log Level | Broker Mode | Risk Profile |
|-------------|----------|-----------|-------------|--------------|
| `development` | Testing & debugging | DEBUG | Paper | Relaxed (10 consecutive losses allowed) |
| `paper` | Paper trading | INFO | Paper | Realistic (3 consecutive losses) |
| `live` | Production trading | WARNING | Live | Conservative (2 consecutive losses) |

### Strategies

| Strategy | Exchange | Underlyings | Symbols | AMT Thresholds |
|----------|----------|-------------|---------|----------------|
| `mcx_options` | MCX | CRUDEOIL, NATURALGAS | 4 contracts | aggression_sigma=2.0, cvd_block=50 |
| `nse_options` | NFO | NIFTY, BANKNIFTY, FINNIFTY | 3 contracts | aggression_sigma=2.5, cvd_block=5000 |

## Mode Selection Script

The `select_mode.py` script makes it easy to switch modes:

```bash
# List all available modes
./venv/bin/python scripts/select_mode.py --list

# Set MCX paper trading
./venv/bin/python scripts/select_mode.py --env paper --strategy mcx_options

# Set NSE live trading
./venv/bin/python scripts/select_mode.py --env live --strategy nse_options
```

The script updates your `.env` file with:
```bash
GLASSYTRADE_ENV=paper
GLASSYTRADE_STRATEGY=mcx_options
```

## Environment Variables

Only two environment variables control the entire configuration:

- `GLASSYTRADE_ENV` - Environment name (development/paper/live)
- `GLASSYTRADE_STRATEGY` - Strategy name (mcx_options/nse_options)

All other configuration comes from YAML files.

## Adding Custom Strategy

You can create your own trading strategy without modifying existing files:

1. **Create strategy file**: `backend/config/strategies/my_strategy.yaml`

```yaml
strategy:
  name: "my_strategy"
  description: "My custom trading strategy"

scanner:
  mode: "mcx_options"
  underlyings: ["CRUDEOIL"]
  top_n: 2

exchange:
  default: "MCX"
  symbols: ["CRUDEOIL"]

feature_flags:
  risk_tier_engine: true
  short_signals_enabled: true
```

2. **Activate it**:
```bash
export GLASSYTRADE_STRATEGY=my_strategy
./venv/bin/uvicorn app.main:app --port 9090
```

## Backward Compatibility

All existing code continues to work without modification:

```python
# Old way (still works - reads from YAML now)
from app.config import settings
print(settings.SCANNER_MODE)
print(settings.DEFAULT_EXCHANGE)
```

New code should use dependency injection (coming soon):

```python
# New way (recommended for future code)
from app.api.dependencies import get_system_config
config = await get_system_config(request)
print(config.default_exchange)
```

## Migration from .env

### Old Way (❌ No Longer Needed)

```bash
# Manual .env editing required
export SCANNER_MODE=mcx_options
export DEFAULT_EXCHANGE=MCX
export DHAN_SYMBOLS=CRUDEOIL,NATURALGAS
export AGGRESSION_SIGMA=2.0
# ... 74 more variables
```

### New Way (✅ Recommended)

```bash
# One command switches everything
./venv/bin/python scripts/select_mode.py --env paper --strategy mcx_options

# Or set environment variables
export GLASSYTRADE_ENV=paper
export GLASSYTRADE_STRATEGY=mcx_options
```

## Configuration Files Reference

### Strategy Files

- `backend/config/strategies/mcx_options.yaml` - MCX commodity options
- `backend/config/strategies/nse_options.yaml` - NSE index options

### Environment Files

- `backend/config/environments/development.yaml` - Development settings
- `backend/config/environments/paper.yaml` - Paper trading settings
- `backend/config/environments/live.yaml` - Production settings

### Base Configuration

- `backend/config/base.yaml` - All defaults and global constants

## Testing

Run the configuration tests:

```bash
cd backend
./venv/bin/pytest tests/unit/config/test_mode_config.py -v
```

Tests verify:
- MCX mode loads correctly
- NSE mode loads correctly
- Backward compatibility maintained
- Configuration hierarchy works
- Environment-specific settings applied

## Troubleshooting

### Problem: "Strategy file not found"

**Solution**: Check that the strategy file exists:
```bash
ls backend/config/strategies/
```

### Problem: Settings not updating after mode change

**Solution**: Restart the backend. Configuration is loaded at startup only.

### Problem: Missing API credentials

**Solution**: Ensure `.env` file contains:
```bash
DHAN_CLIENT_ID=your_client_id
DHAN_ACCESS_TOKEN=your_access_token
```

### Problem: Want to see what config is loaded

**Solution**: Check backend logs at startup. You'll see:
```
======================================================================
  GlassyTrade AI — Mode Configuration
======================================================================
  Environment: paper
  Strategy:    mcx_options
  Default Exchange: MCX
  Active Symbols: ['CRUDEOIL', 'NATURALGAS']
  ...
======================================================================
```

## Benefits

✅ **No More Manual .env Editing** - Switch modes with one command
✅ **Version Control** - YAML files trackable in Git
✅ **Mode Presets** - Pre-configured MCX/NSE strategies
✅ **Environment Profiles** - Development/paper/live separation
✅ **Backward Compatible** - Existing code continues working
✅ **Professional Architecture** - Follows 12-factor app principles
✅ **Type Safety** - Pydantic models validate all config
✅ **Testable** - Comprehensive test suite included

## Architecture

```
.env (secrets only)
  ↓
base.yaml (all defaults)
  ↓
environments/{env}.yaml (overrides)
  ↓
strategies/{strategy}.yaml (overrides)
  ↓
SettingsAdapter (backward compatibility)
  ↓
Application Code (25+ files)
```

## Next Steps

- [ ] Add dependency injection for new code
- [ ] Create web UI for mode selection
- [ ] Add more strategies (GOLD, SILVER, etc.)
- [ ] Add environment validation on startup
- [ ] Create configuration diff tool

## Support

For issues or questions:
1. Check this documentation
2. Review backend startup logs
3. Run tests: `pytest tests/unit/config/test_mode_config.py -v`
4. Check YAML file syntax
