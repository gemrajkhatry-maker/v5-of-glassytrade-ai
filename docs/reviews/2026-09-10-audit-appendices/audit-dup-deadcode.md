# Audit: Duplication, Dead Code, Conflicting Config

Repo: `/Users/apple/Documents/v5-of-glassytrade-ai` (branch `feat/timesfm-paper-e2e-validation`)
Scope: READ-ONLY. `quant/*.py`, `quant/**/*.py`, `backend/app/**/*.py`. Every claim below is proven with `file:line` + quote.

---

## AREA 1 — ENVIRONMENT VARIABLES

### 1.1 Full inventory of `os.getenv` / `os.environ` reads (quant/ + backend/app/)

**quant/**

| file:line | var | default |
|---|---|---|
| quant/amt/session/scanner.py:69 | `SCANNER_BIG_MOVE` | `""` |
| quant/amt/session/scanner.py:75 | `SCANNER_BIG_MOVE_MAX_STRADDLE_PCT` | `"0.02"` |
| quant/amt/session/scanner.py:77 | `SCANNER_BIG_MOVE_MIN_DTE` | `"2"` |
| quant/amt/session/scanner.py:407 | `TIMESFM_CONTRACT_SELECTION` | `"true"` |
| quant/amt/session/scanner.py:408 | `TIMESFM_ADVISOR_ENABLED` | `"false"` |
| quant/amt/session/scanner.py:592 | `OPTION_SCANNER_PARALLEL_UNDERLYINGS` | `""` |
| quant/amt/session/scanner.py:601 | `OPTION_SCANNER_MAX_WORKERS` | `"4"` |
| quant/amt/session/scanner_config.py:42 | `SCANNER_TOP_N` | `"4"` |
| quant/amt/session/scanner_config.py:44 | `SCANNER_UNDERLYINGS` | `"CRUDEOIL,NATURALGAS,GOLDM,SILVERM"` |
| quant/amt/session/scanner_config.py:48 | `SCANNER_OPTION_TYPE` | `""` |
| quant/amt/session/scanner_config.py:49 | `SCANNER_EXPIRY_INDEX` | `"0"` |
| quant/amt/session/scanner_config.py:50 | `STRIKES_AROUND_ATM` | `"2"` |
| quant/multi_engine.py:397 | `GLASSYTRADE_SEED_INTERVAL_SEC` | `"0.5"` |
| quant/multi_engine.py:1385 | `TIMESFM_CONTRACT_SELECTION` | `"true"` |
| quant/multi_engine.py:1386 | `TIMESFM_ADVISOR_ENABLED` | `"false"` |
| quant/runtime.py:331 | `TIMESFM_END_TO_END` | `""` |
| quant/event_store.py:40 | `EVENT_STORE_SECRET` | `"glassytrade-genesis-secret-2026"` |
| quant/decision/timesfm_client.py:22 | `TIMESFM_SERVICE_URL` | `"http://localhost:8091"` |
| quant/wiring_advisor.py:67 | `LLM_ADVISOR_ENABLED` | `"false"` |
| quant/wiring_advisor.py:73 | `TIMESFM_ADVISOR_ENABLED` | `"false"` |
| quant/wiring_advisor.py:74 | `TIMESFM_NATIVE` | `"true"` |
| quant/wiring_advisor.py:82 | `TIMESFM_SERVICE_URL` | `"http://localhost:8091"` |
| quant/wiring_advisor.py:109 | `MLX_MODEL_PATH` | `None` |
| quant/wiring_advisor.py:110 | `MLX_ADAPTER_PATH` | `None` |
| quant/hotpath.py:82 | `GLASSYTRADE_HOTPATH_TRACE_FILE` | `None` |
| quant/hotpath.py:91 | `GLASSYTRADE_HOTPATH_TRACE` | `""` |

**backend/app/**

| file:line | var | default |
|---|---|---|
| backend/app/shared/mode.py:17 | `GLASSYTRADE_ENV` | `"paper"` |
| backend/app/shared/mode.py:18 | `TRADING_MODE` | `""` |
| backend/app/config_models/validator.py:282 | `ML_MODEL_DIR` | `""` |
| backend/app/config_models/settings_adapter.py:90 | `DHAN_CLIENT_ID` | `""` |
| .../settings_adapter.py:91 | `DHAN_ACCESS_TOKEN` | `""` |
| .../settings_adapter.py:92 | `DHAN_API_KEY` | `""` |
| .../settings_adapter.py:93 | `DHAN_API_SECRET` | `""` |
| .../settings_adapter.py:94 | `TELEGRAM_BOT_TOKEN` | `""` |
| .../settings_adapter.py:95 | `TELEGRAM_CHAT_ID` | `""` |
| .../settings_adapter.py:106 | `SCANNER_MODE` | `"mcx_options"` |
| .../settings_adapter.py:113 | `DEFAULT_EXCHANGE` | `"MCX"` |
| .../settings_adapter.py:120 | `DHAN_SYMBOLS` | `"CRUDEOIL,NATURALGAS"` |
| .../settings_adapter.py:128 | `SCANNER_UNDERLYINGS` | `"CRUDEOIL,NATURALGAS,GOLDM,SILVERM"` |
| .../settings_adapter.py:143 | `SCANNER_UNDERLYING_PRIORITY` | `""` |
| .../settings_adapter.py:153 | `SCANNER_TOP_N` | `"4"` |
| .../settings_adapter.py:160 | `SCANNER_TOP_PER_UNDERLYING` | `"2"` |
| .../settings_adapter.py:167 | `STRIKES_AROUND_ATM` | `"2"` |
| .../settings_adapter.py:174 | `SCANNER_EXPIRY_INDEX` | `"0"` |
| .../settings_adapter.py:181 | `SCANNER_OPTION_TYPE` | `""` |
| .../settings_adapter.py:188 | `AGGRESSION_SIGMA` | `"2.0"` |
| .../settings_adapter.py:195 | `DISPLACEMENT_MULTIPLIER` | `"1.2"` |
| .../settings_adapter.py:200 | `BALANCE_RATIO_THRESHOLD` | `"0.55"` |
| .../settings_adapter.py:208 | `ALLOW_SHORT` | `"true"` |
| .../settings_adapter.py:216 | `RISK_TIER_ENGINE` | `"true"` |
| .../settings_adapter.py:224 | `SHORT_SIGNALS_ENABLED` | `"true"` |
| .../settings_adapter.py:232 | `LLM_PRE_CANDLE_ADVISORY` | `"true"` |
| .../settings_adapter.py:240 | `SCALP_ENGINE_ENABLED` | `"false"` |
| .../settings_adapter.py:248 | `SCALP_IB_BREAKOUT` | `"false"` |
| .../settings_adapter.py:256 | `QUANT_DECISION_ENABLED` | `"false"` |
| .../settings_adapter.py:261 | `CORS_ORIGINS` | (long csv) |
| .../settings_adapter.py:277 | `QUANT_EXECUTION_MODE` | `""` |
| .../settings_adapter.py:314 | `REALISTIC_COST_MODEL` | `"true"` |
| .../settings_adapter.py:321 | `LLM_TIMEOUT_SECONDS` | `"60"` |
| .../settings_adapter.py:326 | `LLM_EXECUTION_ENABLED` | `"true"` |
| .../settings_adapter.py:333 | `CAPITAL` | `"5000000"` |
| .../settings_adapter.py:340 | `STREAM_INTERVAL` | `"5m"` |
| .../settings_adapter.py:345 | `TICK_POLL_SECONDS` | `"5.0"` |
| .../settings_adapter.py:350 | `SIGNAL_STALE_SECONDS` | `"60"` |
| .../settings_adapter.py:361 | `GAP_FILL_ENABLED` | `"true"` |
| .../settings_adapter.py:368 | `GAP_FILL_INTERVAL` | `"300"` |
| .../settings_adapter.py:375 | `GAP_FILL_MIN_GAP_SECONDS` | `"60"` |
| .../settings_adapter.py:382 | `GAP_FILL_MAX_LOOKBACK` | `"600"` |
| .../settings_adapter.py:389 | `GAP_FILL_MAX_FILL_AGE` | `"120"` |
| .../settings_adapter.py:403 | `name` (dynamic) | `None` |
| backend/app/config_models/loader.py:184 | `GLASSYTRADE_ENV` | `"paper"` |
| backend/app/config_models/loader.py:209 | `GLASSYTRADE_STRATEGY` | `"mcx_options"` |
| backend/app/config_models/loader.py:252 | `CANDLE_TIMEFRAME_MINUTES` | `5` |
| backend/app/application/di/composition_root.py:163 | `LLM_ADVISOR_ENABLED` | `"false"` |
| backend/app/application/di/composition_root.py:164 | `TIMESFM_ADVISOR_ENABLED` | `"false"` |
| backend/app/main.py:428 | `RECONCILE_DELETE_STALE` | `None` |
| backend/app/infrastructure/adapters/dhan_order_feed.py:131 | `DHAN_ORDER_WS_URL` | `""` |
| .../dhan_order_feed.py:135 | `DHAN_WS_USER_TYPE` | `"SELF"` |
| .../dhan_order_feed.py:138 | `DHAN_ORDER_WS_RECONNECT_SEC` | `"5"` |
| .../dhan_adapter.py:67 | `OPTION_CHAIN_CACHE_TTL_SEC` | `"8.0"` |
| .../dhan_adapter.py:74 | (fetch-serialize flag) | — |
| .../dhan_broker_adapter.py:73 | `DHAN_ORDER_POLL_INTERVAL_SEC` | `"0.5"` |
| .../dhan_broker_adapter.py:76 | `DHAN_ORDER_POLL_TIMEOUT_SEC` | `"30"` |
| .../dhan_broker_adapter.py:79 | (flag) | — |
| .../dhan_broker_adapter.py:88 | (flag) | — |
| .../dhan_broker_adapter.py:96 | (flag) | — |
| .../dhan_broker_adapter.py:117 | `DHAN_CLIENT_ID` | `""` |
| .../dhan_broker_adapter.py:122 | `DHAN_ACCESS_TOKEN` | `""` |

65 distinct names.

### FINDING 1 — HIGH — Same env var read in 2+ places, and scanner config has TWO independent sources that can disagree (`SCANNER_TOP_N` default `4` vs `.env.example` / composition `8`)
- `quant/amt/session/scanner_config.py:42` — `top_n=int(os.getenv("SCANNER_TOP_N", "4")),`
- `quant/amt/session/scanner_config.py:57` — `top_n=int(settings.SCANNER_TOP_N),`
- `backend/app/config_models/settings_adapter.py:153` — `return int(os.getenv("SCANNER_TOP_N", "4"))`
- `backend/app/application/di/composition_root.py:147` — `"n": int(_settings.SCANNER_TOP_N or 8),`
- `.env.example:50` — `SCANNER_TOP_N=8`

`ScannerConfig.from_env()` (fallback path) reads the env var directly with default `4`; `from_settings()` reads the same var through `SettingsAdapter` (also `4`); the composition root uses `or 8` as a further fallback. Three different defaults for one knob, and the class docstring (`scanner_config.py:37`) admits these are "legacy settings-adapter defaults." Why it matters: the number of contracts scanned per cycle can differ depending on which construction path the runtime took.

### FINDING 2 — HIGH — `SCANNER_UNDERLYINGS` duplicated with a drift-prone duplicate parser
- `quant/amt/session/scanner_config.py:44-46` — `os.getenv("SCANNER_UNDERLYINGS", "CRUDEOIL,NATURALGAS,GOLDM,SILVERM")`
- `backend/app/config_models/settings_adapter.py:128-129` — `"SCANNER_UNDERLYINGS", "CRUDEOIL,NATURALGAS,GOLDM,SILVERM"`

Two independent env reads + two parsers of the same comma list (the module even comments at line 24 "Mirrors SettingsAdapter.SCANNER_UNDERLYINGS env branch: strip-only"). Any change to one parser silently diverges.

### FINDING 3 — HIGH — `SCANNER_EXPIRY_INDEX` / `STRIKES_AROUND_ATM` / `SCANNER_OPTION_TYPE` duplicated across two modules
- `quant/amt/session/scanner_config.py:48-50` (`from_env`) vs `scanner_config.py:59-61` (`from_settings`)
- `backend/app/config_models/settings_adapter.py:167,174,181`

Each of the three vars is read directly from env AND via the settings adapter, i.e. the same value has two authorities.

### FINDING 4 — CRITICAL — `LLM_ADVISOR_ENABLED` is treated as an OR-enable in one place and a hard-disable in another
- `quant/wiring_advisor.py:67-72` — treats `false` as a **hard disable** that short-circuits before TimesFM is considered:
  ```python
  enabled_val = os.getenv("LLM_ADVISOR_ENABLED", "false").strip().lower()
  if enabled_val in ("0", "false", "no", "disable", "disabled"):
      logger.info("LLM advisor is DISABLED (LLM_ADVISOR_ENABLED=%s)", enabled_val)
      return None
  ```
- `backend/app/application/di/composition_root.py:163-164` — treats the *same* var as one arm of an **OR-enable**:
  ```python
  "advisor_enabled": (
      os.getenv("LLM_ADVISOR_ENABLED", "false").strip().lower() in ("true", "1", "yes")
      or os.getenv("TIMESFM_ADVISOR_ENABLED", "false").strip().lower() in ("true", "1", "yes")
  ),
  ```
Why it matters: `LLM_ADVISOR_ENABLED=false` + `TIMESFM_ADVISOR_ENABLED=true` yields `advisor_enabled=True` in the coordinator config while `build_live_advisor()` returns `None`. The two subsystems disagree about whether an advisor exists; TimesFM is silently unavailable on the exact configuration that claims to enable it.

### FINDING 5 — HIGH — Same flag pair (`TIMESFM_CONTRACT_SELECTION` OR `TIMESFM_ADVISOR_ENABLED`) enables the same subsystem, duplicated verbatim in 3 modules
- `quant/amt/session/scanner.py:407-408`
  ```python
  os.getenv("TIMESFM_CONTRACT_SELECTION", "true").strip().lower() in ("1", "true", "yes")
  or os.getenv("TIMESFM_ADVISOR_ENABLED", "false").strip().lower() in ("1", "true", "yes")
  ```
- `quant/multi_engine.py:1385-1386` — byte-identical logic
- `backend/app/application/di/composition_root.py:163-164` — same OR with tuple order `("true","1","yes")`

`TIMESFM_CONTRACT_SELECTION` **defaults to `true`**, so the TimesFM subsystem is enabled by default through this OR even when `TIMESFM_ADVISOR_ENABLED=false`. Three copies means a default flip must be made in three places.

### FINDING 6 — MEDIUM — `TIMESFM_SERVICE_URL` read in 2 places, same literal default duplicated
- `quant/decision/timesfm_client.py:22` — `DEFAULT_SERVICE_URL = os.getenv("TIMESFM_SERVICE_URL", "http://localhost:8091")`
- `quant/wiring_advisor.py:82` — `service_url=os.getenv("TIMESFM_SERVICE_URL", "http://localhost:8091"),`
The literal `"http://localhost:8091"` is hard-coded twice; changing the port requires editing both.

### FINDING 7 — MEDIUM — Flag-enable map for the requested subsystem flags
| flag | read at | default | what it enables |
|---|---|---|---|
| `TIMESFM_ADVISOR_ENABLED` | wiring_advisor.py:73, scanner.py:408, multi_engine.py:1386, composition_root.py:164 | `"false"` | builds `TimesFMAdvisor` **and** enables contract selection |
| `TIMESFM_NATIVE` | wiring_advisor.py:74 | `"true"` | in-process engine vs remote service |
| `TIMESFM_END_TO_END` | runtime.py:331 | `""` | swaps strategy to `TimesFMTradingStrategy` |
| `TIMESFM_CONTRACT_SELECTION` | scanner.py:407, multi_engine.py:1385 | `"true"` | enables TimesFM contract-selection forecasts |
| `LLM_ADVISOR_ENABLED` | wiring_advisor.py:67, composition_root.py:163 | `"false"` | LLM advisor (AND hard-disable of TimesFM path) |
| `TRADING_MODE` | shared/mode.py:18 | `""` | paper/live mirror of `GLASSYTRADE_ENV` |
| `QUANT_EXECUTION_MODE` | settings_adapter.py:277 | `""` | off\|shadow\|paper\|live quant gate |

Overlaps: `TIMESFM_CONTRACT_SELECTION` (default true) and `TIMESFM_ADVISOR_ENABLED` both reach the same `tfm_enabled` boolean (Finding 5). `TIMESFM_NATIVE` is read **only** in `wiring_advisor.py:74`, but `TIMESFM_END_TO_END` (runtime.py:331) depends on `advisor._native_engine` existing — so `TIMESFM_END_TO_END=true` with `TIMESFM_NATIVE=false` produces `TimesFMTradingStrategy(engine=None)` and a silently dead E2E path. `QUANT_EXECUTION_MODE` vs `QUANT_DECISION_ENABLED` are two aliases for one gate (settings_adapter.py:277-286).

---

## AREA 2 — DUPLICATION

### FINDING 8 — CRITICAL — TimesFM forecast block (quantile slicing, p10/p90 fallback, `q_spread`, `forecast_steps`) duplicated verbatim in 3 production modules
Three near-identical blocks build `TimesFMForecast` from `quantiles[:, 4]` / `[:, 0]` / `[:, 8]`:

`quant/multi_engine.py:1456-1481`:
```python
p50 = quantiles[:, 4]
p10 = quantiles[:, 0]
p90 = quantiles[:, 8]
q_spread = float(np.mean(p90 - p10))
else:
    p50 = np.full(32, curr_price)
    p10 = np.full(32, curr_price * 0.998)
    p90 = np.full(32, curr_price * 1.002)
    q_spread = 0.0
...
forecast_steps=["LONG" if p > curr_price else "SHORT" for p in p50],
```

`quant/amt/session/scanner.py:466-495`:
```python
p50 = quantiles[:, 4]
p10 = quantiles[:, 0]
p90 = quantiles[:, 8]
q_spread = float(np.mean(p90 - p10))
else:
    p50 = np.full(32, curr_price)
    p10 = np.full(32, curr_price * 0.998)
    p90 = np.full(32, curr_price * 1.002)
    q_spread = 0.0
...
forecast_steps=["LONG" if p > curr_price else "SHORT" for p in p50],
```

`quant/strategies/timesfm_strategy.py:313-341` (same math, different fallback constant):
```python
p50 = quantiles[:, 4].astype(np.float32)
p10 = quantiles[:, 0].astype(np.float32)
p90 = quantiles[:, 8].astype(np.float32)
q_spread = float(np.mean(p90 - p10))
...
p10 = p50 - (curr_price * 0.002)   # <-- different fallback than the two above
p90 = p50 + (curr_price * 0.002)
```

Plus a fourth consumer of the same slice indices at `quant/decision/timesfm_engine.py:362-365`:
```python
p50_path = quantiles[:, 4]
...
q_spread = float(np.mean(p90_path - p10_path))
```
Why it matters: the quantile index contract (`4`=p50, `0`=p10, `8`=p90) is asserted by comment (`timesfm_engine.py:354 "Quantile shape: (32, 9) where index 4 is p50, 0 is p10, 8 is p90"`) in four places and checked nowhere. A model/quantile-count change silently corrupts all four. The fallback constants also already disagree (`* 0.998/1.002` vs `± curr_price*0.002`).

### FINDING 9 — HIGH — `TimesFMForecast(...)` constructed at 5 sites with drifting step-label semantics
Sites: `quant/amt/session/scanner.py:479`, `quant/multi_engine.py:1469`, `quant/decision/timesfm_engine.py:383`, `quant/strategies/timesfm_strategy.py:288`, `quant/strategies/timesfm_strategy.py:330`.
Two different label rules coexist:
- `quant/multi_engine.py:1477` / `scanner.py:487`: `["LONG" if p > curr_price else "SHORT" for p in p50]` — binary, **never emits FLAT**
- `quant/strategies/timesfm_strategy.py:328`: `["LONG" if p > curr_price else ("SHORT" if p < curr_price else "FLAT") for p in p50]` — ternary
- `quant/strategies/timesfm_strategy.py:296` compares against `snapshot.p50_path[0]` (the *first* forecast step) rather than `curr_price`
- `quant/decision/timesfm_engine.py:373-380` builds step-by-step with `FLAT` for near-equal

Downstream `quant/decision/timesfm_agents.py:229-231` counts `s == "LONG"` / `"SHORT"` over `forecast_steps`, and `quant/execution/risk.py:345` counts `s == side.upper()`. Consumers assume FLAT is possible; the two highest-volume producers never produce it.

### FINDING 10 — HIGH — Absorption-direction mapping (`SELL_ABSORBED`→`LONG`) implemented 4+ times with different semantics
- `quant/decision/context_builder.py:121-122` — dict map:
  ```python
  if amt_dto.get("absorptionSide") in ("SELL_ABSORBED", "BUY_ABSORBED"):
      return {"SELL_ABSORBED": "LONG", "BUY_ABSORBED": "SHORT"}.get(amt_dto.get("absorptionSide"))
  ```
- `quant/decision/context_builder.py:218-219` — inline ternary, **duplicated literal**:
  ```python
  if nearest_leg_lvn > 0 and amt_dto.get("absorptionSide") in ("SELL_ABSORBED", "BUY_ABSORBED"):
      direction = "LONG" if amt_dto.get("absorptionSide") == "SELL_ABSORBED" else "SHORT"
  ```
- `quant/decision/timesfm_engine.py:434-437` — substring form:
  ```python
  if ctx.cvd_slope > 0 and "SELL" in absorption:
      direction = "LONG"
  elif ctx.cvd_slope < 0 and "BUY" in absorption:
      direction = "SHORT"
  ```
- `quant/position_manager.py:538-541` — inverted guard form:
  ```python
  if long and absorption_side != "SELL_ABSORBED": ...
  if not long and absorption_side != "BUY_ABSORBED": ...
  ```
- `quant/decision/timesfm_agents.py:500-518` — a *contradicting* mapping: `(side == "LONG" and absorption in ("BUY", "BUY_ABSORBED"))` marks BUY_ABSORBED as agreeing with LONG, i.e. the opposite of context_builder's `BUY_ABSORBED→SHORT`.
Why it matters: bullish/bearish sign of the same field is encoded five ways; `timesfm_agents.py:500` (BUY_ABSORBED ⇒ agrees with LONG) conflicts with `context_builder.py:122` (BUY_ABSORBED ⇒ SHORT).

### FINDING 11 — HIGH — The "is option contract AND endswith CALL/CE/PUT/PE" test repeated in 4 modules
- `quant/amt/session/selector.py:478-482`
  ```python
  is_call = is_option_contract(option_symbol) and (
      sym_upper.endswith(("CALL", "CE")) or sym_upper.endswith("-CE"))
  is_put = is_option_contract(option_symbol) and (
      sym_upper.endswith(("PUT", "PE")) or sym_upper.endswith("-PE"))
  ```
- `quant/runtime.py:1276-1281` — identical, on `self.symbol`
- `backend/app/infrastructure/adapters/_dhan_common.py:66-68` — variant using regex on top of `endswith`, and `is_put = is_option and not is_call`:
  ```python
  is_call = is_option and (
      symbol.upper().endswith(("CALL", "CE")) or bool(re.search(r"(?:CALL|CE)$", symbol.upper())))
  is_put = is_option and not is_call
  ```
- `quant/amt/analyzer.py:350-352` — a *fourth* variant that does **not** call `is_option_contract`:
  ```python
  if sym.endswith("CALL") or re.search(r"\d+\s*CE$", sym):
  if sym.endswith("PUT") or re.search(r"\d+\s*PE$", sym):
  ```
Why it matters: `analyzer.py` version is not gated on `is_option_contract` and uses a different regex (`\d+\s*CE$`), so a symbol like `"SOMECE"` or a futures root ending in `CE` classifies differently between analyzer and selector/runtime.

### FINDING 12 — MEDIUM — Session-phase substring checks (`OPENING`/`PRE_OPEN`/`CLOSE`/`EOD`) duplicated 6 times
- `quant/decision/timesfm_agents.py:59` — `if any(p in phase for p in ("OPENING", "PRE_OPEN", "PRE_MARKET")):`
- `quant/decision/timesfm_agents.py:69` — `elif any(p in phase for p in ("CLOSE", "POST_MARKET", "EOD")):`
- `quant/decision/timesfm_agents.py:74` — `if any(p in phase for p in ("OPENING", "PRE_OPEN")):`
- `quant/decision/timesfm_agents.py:254-255` — `is_opening = any(p in session_phase for p in ("OPENING", "PRE_OPEN", "PRE_MARKET"))` / `is_closing = ... ("CLOSE", "POST_MARKET", "EOD")`
- `quant/decision/timesfm_engine.py:301` — `is_opening = any(p in session_phase for p in ("OPENING", "PRE_OPEN", "PRE_MARKET"))`
- `quant/llm/narrative.py:238` — `return any(p in phase for p in ("OPENING", "PRE_OPEN", "PRE_MARKET"))`
Note `timesfm_agents.py:74` omits `"PRE_MARKET"` while :59 and :254 include it — the "opening" definition already disagrees within one file.

### FINDING 13 — MEDIUM — `poc` resolution `ctx.poc or ctx.state.poc or curr_price` duplicated
- `quant/decision/timesfm_agents.py:109` — `poc = float(ctx.poc or (ctx.state.poc if ctx.state else curr_price))`
- `quant/decision/timesfm_agents.py:439` — identical in the position-management agent
- `quant/decision/timesfm_client.py:61` — variant: `poc = float(ctx.poc or (amt.poc if amt else close_p))`
- Related in `quant/decision/context_builder.py:323,432` — `vah = float(amt_dto.get("valueAreaHigh") or 0.0)`
Two different resolution chains (state vs amt dto) for the same concept.

### FINDING 14 — MEDIUM — `dto.get("valueAreaHigh")` resolution repeated
- `quant/decision/context_builder.py:323` — `vah = float(amt_dto.get("valueAreaHigh") or 0.0)`
- `quant/decision/context_builder.py:432` — `vah=float(amt_dto.get("valueAreaHigh") or 0.0),`
- `quant/runtime.py:932` — `"poc": amt_dto.get("poc"), "vah": amt_dto.get("valueAreaHigh"),`
- `quant/runtime.py:536` — `vah=float(amt.get("valueAreaHigh") or 0.0),`
Same camelCase key + same `or 0.0` coercion copy-pasted.

### FINDING 15 — MEDIUM — Duplicated forecast fallback constant `0.998` / `1.002`
- `quant/amt/session/scanner.py:473-474` — `p10 = np.full(32, curr_price * 0.998)` / `p90 = np.full(32, curr_price * 1.002)`
- `quant/multi_engine.py:1463-1464` — identical
- `quant/decision/timesfm_engine.py:358-359` — identical
- `quant/llm/narrative.py:88-89` — same magic as a TP band: `px >= tp * 0.998` / `px <= tp * 1.002`
- `quant/multi_engine.py:825` — `(curr_px * (1.002 if pos_side == "LONG" else 0.998))`
Five sites, no named constant.

### FINDING 16 — MEDIUM — `INITIAL_CAPITAL` vs literal `100000` fallback for equity (1000x scale mismatch)
- `quant/contracts/aggregates.py:28` — `INITIAL_CAPITAL: Decimal = Decimal("1000000")  # 10 lakhs INR (1M)`
- `quant/decision/timesfm_agents.py:323` — `equity=float(getattr(ctx, "equity", None) or 100000.0),`
Why it matters: the canonical default capital is **1,000,000**, but when `ctx.equity` is falsy the sizer is fed **100,000** — a 10x undersizing of position risk on any context lacking equity. Every other module imports `INITIAL_CAPITAL` (`ws_contract.py:19`, `state.py:23`, `execution/risk.py:9`, `execution/portfolio_risk.py:21`, `multi_engine.py:46`); this one site does not.

### FINDING 17 — LOW — `3.0 * tick` "retest tolerance" duplicated
- `quant/decision/gates_edge.py:101` — `abs(float(ctx.bar.close) - trapped) <= 3.0 * tick`
- `quant/decision/context_builder.py:379` — `abs(float(bar.close) - trapped_lvl) <= 3.0 * tick  # ponytail: retest proxy`
- `quant/decision/gates_session_position.py:44` — `max_spread = max(3.0 * tick, close_px * 0.001, 0.40)`
- `quant/amt/analyzer.py:513` — `abs(h - poc_price) > 3.0 * tick_approx`
Four independent definitions of the same tolerance.

### FINDING 18 — MEDIUM — `0.65` conviction threshold duplicated as literal instead of using the named constant
- `quant/contracts/constants.py:182` — `CONFIDENCE_HIGH_THRESHOLD = 0.65`
- `quant/multi_engine.py:834` — `"confidenceScore": 0.85 if is_risk_free else 0.65,`
- `quant/decision/decision_service.py:73` — `and ctx.agent_probability >= 0.65`
- `quant/decision/timesfm_sizing.py:204` — `1.15 - (0.65 * horizon_fraction)`
A named constant exists but three call sites hard-code the value.

### FINDING 19 — LOW — `quant/amt/session/scanner_config.py` FROM_ENV vs FROM_SETTINGS parallel construction
`scanner_config.py:38-51` (`from_env`) and `scanner_config.py:53-62` (`from_settings`) construct the same dataclass from two authorities (see Findings 1-3). This is structural duplication: the env branch will silently diverge from the settings/YAML branch forever.

---

## AREA 3 — DEAD CODE

### FINDING 20 — HIGH — `ExitEngine`-adjacent rule functions `update_peak_profit` and `is_valid_rr` are dead (no caller anywhere, including tests)
- `quant/execution/exit_rules.py:111` — `def update_peak_profit(position: "Position", current_price: float) -> float:`
- `quant/execution/exit_rules.py:234` — `def is_valid_rr(entry: float, sl: float, tp: float, min_rr: float | None = None) -> bool:`

Proof: `grep -rn "update_peak_profit" quant/ backend/app/` returns only the definition; `grep -rn "is_valid_rr" . --include=*.py` (excluding `.venv`, `node_modules`, `__pycache__`) returns only `exit_rules.py:234`. No import, no test reference. (Contrast: `classify_exit` is imported at `quant/contracts/entities.py:22`; `get_session_time_stop` at `quant/execution/exits.py:12` and `exit_checks.py:178`; `update_excursions` is referenced only from tests — see Finding 21.)

### FINDING 21 — MEDIUM — `update_excursions` has no production caller; tests-only
- `quant/execution/exit_rules.py:84` — `def update_excursions(position: "Position", current_price: float) -> None:`
Proof: `grep -rn "update_excursions" quant/ backend/app/` → only the definition. Callers exist solely in `backend/tests/unit/domain/test_exit_rules.py:20,32,36` and `backend/tests/runtime_validation/test_phase1_leaf_components.py:33,121,131`. The MAE/MFE tracking it implements is therefore not wired into the live exit path.

### FINDING 22 — LOW — `compute_option_lot_size` / `compute_lot_size` used only by tests
- `quant/amt/session/selector.py:319` — `def compute_lot_size(`
- `quant/amt/session/selector.py:339` — `def compute_option_lot_size(`
Proof: only callers are `tests/quant/decision/test_option_signal_translation.py:16,38,58,67`. No `quant/` or `backend/app/` caller, so production position sizing does not use these methods (`_lot_size_for` at `selector.py:117` is used instead).

### FINDING 23 — HIGH — `quant/decision/timesfm_client.py` (`TimesFMSnapshotBuffer`, `context_to_snapshot`, `TimesFMClient`) is reachable only through the remote path that `TIMESFM_NATIVE=true` disables
- `quant/decision/timesfm_client.py:25` — `def context_to_snapshot(ctx: DecisionContext) -> dict:`
- `quant/decision/timesfm_client.py:132` — `class TimesFMSnapshotBuffer:`
- Consumers: `quant/decision/timesfm_advisor.py:27-28` (imports) used at `timesfm_advisor.py:152,220`.
- Guard in the advisor, `quant/decision/timesfm_advisor.py:143-152`:
  ```python
  if self._use_native_engine:
      ...
      self._client = None
      self._buffer = None
  else:
      self._client = TimesFMClient(service_url)
      self._buffer = TimesFMSnapshotBuffer(target_size=32)
  ```
  and `timesfm_advisor.py:207-208`: `if not self._client or not self._buffer: return`.
- `TIMESFM_NATIVE` defaults to `"true"` (`quant/wiring_advisor.py:74`), and `_use_native_engine=use_native`.
Proof: `grep -rn "timesfm_client" quant/ backend/` → the only import is `timesfm_advisor.py:24`. So with the default config (`TIMESFM_NATIVE` unset ⇒ `true`), `TimesFMClient` and `TimesFMSnapshotBuffer` are constructed as `None` and every line in the `else` branch at `timesfm_advisor.py:203-232` (snapshotting + remote predict + deep-narrative) is unreachable in production. The whole module is exercised only by `tests/quant/decision/test_timesfm_client.py`.

### FINDING 24 — MEDIUM — `quant/strategy.py` `TradingStrategy` protocol is referenced only as a type annotation; nothing enforces or checks it
- `quant/strategy.py:14` — `class TradingStrategy(Protocol):` with `on_bar` and `should_enter`.
- Usages: `quant/runtime.py:66` (import for annotation), `quant/runtime.py:165` (`strategy: TradingStrategy | None = None`), `quant/multi_engine.py:347` (comment only "...TradingStrategy — None means engine uses default").
Both implementations (`AmtScalpingStrategy` at `strategies/amt_scalping.py:22`, `TimesFMTradingStrategy` at `strategies/timesfm_strategy.py:40`) are plain classes that do **not** inherit or reference the protocol, and no `isinstance`/`runtime_checkable` check exists. The protocol is a decorative docstring; nothing prevents a strategy that violates it from being swapped in.

### FINDING 25 — LOW — `quantv2/` is 62 files, 100% `.pyc`, zero `.py`, zero importers
`find quantv2 -type f -not -name "*.pyc"` → empty. `find quantv2 -type f | wc -l` → 62, all under `quantv2/__pycache__/` (`absorption`, `cvd`, `clock`, `journal`, `oms`, `replay`, `risk`, `setups`, `snapshot`, `coordinator` — for both cpython-313 and cpython-314). `git ls-files quantv2` → 0. `grep -rn "quantv2" quant/ backend/ shared/ scripts/ tests/ --include=*.py` → no matches. Orphaned bytecode for a source tree that no longer exists.

---

## AREA 4 — DEAD ARTIFACTS / REPO CLUTTER

### FINDING 26 — HIGH — `backend/graphify-out/` is checked into git (235 files)
- `git ls-files | grep -c graphify-out` → **235**
- `git ls-files backend/graphify-out | wc -l` → **235** (all of them)
- `git ls-files graphify-out | wc -l` → 0 and `git ls-files quant/graphify-out | wc -l` → 0

Root `graphify-out/` (195M on disk) and `quant/graphify-out/` are correctly gitignored, but `backend/graphify-out/` was committed. This is generated graph-analysis output (a tool cache) tracked as source.

### FINDING 27 — MEDIUM — Large dead/generated directories on disk
| dir | size | tracked | notes |
|---|---|---|---|
| `models/` | 8.6G | 16 files | model weights tree (configs tracked; weights presumably not) |
| `graphify-out/` | 195M | 0 | gitignored tool output at root |
| `old.freebuff/` | 62M | 0 | gitignored legacy snapshot of `.freebuff` |
| `amt_dataset/` | 22M | 6 files | `live_aligned/*.jsonl`, `position_mgmt/*.jsonl` tracked |
| `.freebuff/` | 76K | 17 files | tracked bench/probe scripts |
| `runtime_audit/` | 1.2M | 13 files | tracked one-off phase test scripts |
| `quantv2/` | — | 0 | 62 orphan `.pyc` (Finding 25) |
| `poc_temp/` | empty | 0 | gitignored empty dir |
| `scratch/` | — | 4 files | tracked throwaway scripts |
| `.worktrees/` | — | 0 | gitignored |

Tracked clutter (proves it is committed, not just present):
- `git ls-files scratch` → `scratch/check_discrepancies.py`, `scratch/compare_option_selection.py`, `scratch/compare_timesfm_sizing_vs_baseline.py`, `scratch/evaluate_dataset_accuracy.py`
- `git ls-files amt_dataset` → `amt_dataset/live_aligned/test.jsonl`, `amt_dataset/live_aligned/train.jsonl`, `amt_dataset/position_mgmt/test.jsonl`, `amt_dataset/position_mgmt/train.jsonl`, `amt_dataset/position_mgmt/valid.jsonl`, `amt_dataset/position_mgmt_train.jsonl`
- `git ls-files runtime_audit` → 13 `runtime_audit/audit|backend|e2e|transport/test_phase*.py` + `build_fixture.py`, `boot_helper.py`, `dead_code_scan.py`, `mem_probe.py`
- `git ls-files .freebuff` → `bench_firstcall.py`, `bench_gpu.py`, `bench_mlx.py`, `bench_model.py`, `debug_short.py`, `launch_detached.py`, `probe_dhan_volume.py`, `probe_lot_sizes.py`, `probe_ws_bisect.py`, ... (17 files)
- `git ls-files .kilo` → `.kilo/plans/1787738160269-amt-certification-review-plan.md`
- `git ls-files .commandcode` → `.commandcode/settings.json`, `.commandcode/taste/taste.md`, `.commandcode/taste/workflow/taste.md`

### FINDING 28 — LOW — `amt_dataset/position_mgmt_train.jsonl` sits beside `amt_dataset/position_mgmt/` — flat/duplicate dataset naming
`git ls-files amt_dataset` lists both `amt_dataset/position_mgmt_train.jsonl` (flat file) and `amt_dataset/position_mgmt/{train,test,valid}.jsonl` (directory). Two layouts for one dataset namespace; no code reference identified in `quant/` or `backend/app/`.

### FINDING 29 — LOW — Empty `poc_temp/` and `live_trading_logs/` directories
`ls -la poc_temp` → only `.`/`..` (empty, gitignored). `live_trading_logs/` is an empty directory at repo root. Neither is tracked, so they are pure local noise.

---

## AREA 5 — HOT-PATH CODE SMELLS

### FINDING 30 — HIGH — 50 bare `except Exception: pass` handlers in `quant/` (full list)
AST-verified (single `pass` body, no logging). Each silently swallows the failure:

`quant/aggregator.py:37`, `quant/amt/analyzer.py:180`, `quant/amt/analyzer.py:454`, `quant/amt/analyzer.py:1047`, `quant/amt/market/acceptance_rejection.py:95`, `quant/amt/orderflow/drive.py:124`, `quant/amt/orderflow/drive.py:216`, `quant/amt/session/ib_engine.py:125`, `quant/amt/session/ib_engine.py:168`, `quant/amt/session/scanner.py:167`, `quant/amt/session/scanner.py:454`, `quant/amt_engine.py:342`, `quant/brokers/multiplexed_feed.py:391`, `quant/contracts/timezones.py:49`, `quant/decision/context_builder.py:347`, `quant/decision/context_builder.py:351`, `quant/decision/timesfm_advisor.py:182`, `quant/decision/timesfm_advisor.py:185`, `quant/decision/timesfm_advisor.py:252`, `quant/event_store.py:58`, `quant/execution/exits.py:195`, `quant/execution/live_oms.py:139`, `quant/execution/live_oms.py:223`, `quant/execution/live_oms.py:447`, `quant/llm/advisor.py:82`, `quant/llm/advisor.py:85`, `quant/llm/bridge.py:94`, `quant/multi_engine.py:127`, `quant/multi_engine.py:134`, `quant/multi_engine.py:146`, `quant/multi_engine.py:153`, `quant/multi_engine.py:590`, `quant/multi_engine.py:663`, `quant/multi_engine.py:1434`, `quant/multi_engine.py:1446`, `quant/multi_engine.py:1545`, `quant/multi_engine.py:1600`, `quant/multi_engine.py:1652`, `quant/multi_engine.py:1766`, `quant/multi_engine.py:1890`, `quant/persistence.py:85`, `quant/runtime.py:565`, `quant/runtime.py:571`, `quant/runtime.py:587`, `quant/runtime.py:996`, `quant/runtime.py:1160`, `quant/runtime.py:1348`, `quant/runtime.py:1517`, `quant/session_gates.py:39`, `quant/session_levels.py:194`

Representative quotes:
```python
quant/decision/context_builder.py:347:            except Exception: pass
quant/decision/context_builder.py:351:            except Exception: pass
quant/execution/live_oms.py:140:                pass  # audit must never break trading
quant/runtime.py:588:            pass  # certification must never break trading
```
Why it matters: several sit directly on the live path — `quant/execution/live_oms.py:139/223/447` (order/audit state), `quant/runtime.py:565/571` (engine init), `quant/decision/context_builder.py:347/351` (session-info resolution feeding `session_phase`). A failure in `live_oms` order audit or in session classification is discarded with no log, so a degraded live session is indistinguishable from a healthy one.

### FINDING 31 — HIGH — Functions >120 lines (complexity hot spots)
AST-measured, `quant/`:
| function | file:line | lines |
|---|---|---|
| `analyze` | quant/amt/analyzer.py:389 | 477 |
| `evaluate` (entry agent) | quant/decision/timesfm_agents.py:93 | 324 |
| `_decide` | quant/runtime.py:861 | 318 |
| `__init__` | quant/runtime.py:146 | 296 |
| `_scan_underlying_for_contracts` | quant/amt/session/scanner.py:277 | 272 |
| `evaluate_setup_a` | quant/amt/session/ib_scalp.py:70 | 216 |
| `_spawn_engine` | quant/multi_engine.py:1667 | 213 |
| `amt_result_to_dto` | quant/amt/dto.py:19 | 198 |
| `build` | quant/decision/context_builder.py:284 | 196 |
| `analyze` | quant/decision/timesfm_engine.py:217 | 193 |
| `evaluate` (position agent) | quant/decision/timesfm_agents.py:425 | 190 |
| `classify_touch` | quant/amt/orderflow/drive.py:72 | 186 |
| `seed` | quant/amt_engine.py:223 | 173 |
| `evaluate_setup_b` | quant/amt/session/ib_scalp.py:287 | 169 |
| `extract_features` | quant/probability/features.py:76 | 165 |
| `generate_scenario` | quant/llm/dataset_generator.py:38 | 158 |
| `_dict_to_event` | quant/event_store.py:719 | 158 |
| `simulate_contract_payoff` | quant/decision/timesfm_option_selector.py:94 | 153 |
| `check_pyramid` | quant/position_manager.py:476 | 150 |
| `snapshot` | quant/multi_engine.py:747 | 146 |
| `scan_top_n` | quant/amt/session/scanner.py:550 | 146 |
| `evaluate` | quant/execution/exits.py:108 | 146 |
| `_run_inner` | quant/runtime.py:590 | 143 |
| `update` | quant/amt/market/half_trend.py:148 | 143 |
| `compute_gamma_exposure` | quant/amt/profile/gamma.py:49 | 142 |
| `_build_result` | quant/amt/analyzer.py:867 | 138 |
| `compute_size` | quant/decision/timesfm_sizing.py:138 | 137 |
| `should_enter` | quant/strategies/timesfm_strategy.py:84 | 136 |
| `evaluate_exit` | quant/decision/timesfm_risk.py:98 | 123 |
| `compute_order_flow_metrics` | quant/amt/orderflow/compute.py:21 | 122 |
| `detect_displacement_leg` | quant/amt/profile/displacement.py:39 | 122 |

`quant/runtime.py:861 _decide` (318 lines) and `quant/decision/timesfm_agents.py:93 evaluate` (324) are the two live-decision monoliths; `quant/amt/analyzer.py:389 analyze` at 477 lines is the largest.

### FINDING 32 — MEDIUM — Duplicated constants listed in Area 2 re-appear as unnamed literals on the hot path
Summary of duplicated numeric literals found: `0.998`/`1.002` (5 sites, Finding 15); `0.65` vs `CONFIDENCE_HIGH_THRESHOLD` (3 sites, Finding 18); `3.0 * tick` (4 sites, Finding 17); `0.20` used as both a confidence increment (`quant/amt/market/state_engine.py:80,105`) and multiple unrelated ratios (`selector.py:76 max_theta_ratio`, `selector.py:365 cushion`, `contracts/constants.py:206 ATR_TRAIL_STEP_PCT`, `execution/exits.py:49 trail_giveback_pct`); `1.4` used as a payoff-ratio gate (`timesfm_agents.py:351`) and a sizing clamp ceiling (`timesfm_sizing.py:197`); `horizon=32`/`np.full(32, ...)` hard-coded in all four forecast builders (Findings 8-9). None are named constants; the same numeral means different things in different modules.

---

## Severity summary

| # | Severity | Title |
|---|---|---|
| 4 | CRITICAL | `LLM_ADVISOR_ENABLED` hard-disable vs OR-enable conflict |
| 8 | CRITICAL | TimesFM forecast block duplicated verbatim in 3 modules (+1 consumer) |
| 1 | HIGH | `SCANNER_TOP_N` 3 defaults (`4`/`4`/`8`) across 2 authorities |
| 2 | HIGH | `SCANNER_UNDERLYINGS` duplicate parser |
| 3 | HIGH | `SCANNER_EXPIRY_INDEX`/`STRIKES_AROUND_ATM`/`SCANNER_OPTION_TYPE` dual authority |
| 5 | HIGH | `TIMESFM_CONTRACT_SELECTION OR TIMESFM_ADVISOR_ENABLED` triplicated |
| 9 | HIGH | `TimesFMForecast(...)` 5 sites, divergent FLAT semantics |
| 10 | HIGH | Absorption-direction mapping 5 sites, two contradictory |
| 11 | HIGH | option-contract+CE/PE test 4 implementations (one ungated, different regex) |
| 20 | HIGH | `update_peak_profit`, `is_valid_rr` dead (zero callers) |
| 23 | HIGH | `timesfm_client.py` unreachable when `TIMESFM_NATIVE=true` (the default) |
| 26 | HIGH | `backend/graphify-out/` 235 generated files committed |
| 30 | HIGH | 50 bare `except Exception: pass` in `quant/` |
| 31 | HIGH | 31 functions >120 lines (max 477) |
| 6,7,12,13,14,15,16,18,21,24,27 | MEDIUM | url default dup; flag overlap map; session-phase ×6; poc resolution; valueAreaHigh; 0.998/1.002; INITIAL_CAPITAL 10x; 0.65 literal; `update_excursions` tests-only; protocol unenforced; clutter |
| 17,19,22,25,28,29,32 | LOW | 3.0*tick; from_env/from_settings; lot-size tests-only; quantv2 pyc; dataset naming; empty dirs; numeric literals |

Areas covered: (1) env vars, (2) duplication, (3) dead code, (4) dead artifacts, (5) hot-path smells. No files modified; no pytest run.
