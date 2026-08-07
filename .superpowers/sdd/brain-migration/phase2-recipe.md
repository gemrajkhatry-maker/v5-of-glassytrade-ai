# Phase 2 — Shared Consumer Import-Swap Recipe (read this FIRST)

**Goal:** Rewrite backend consumers' imports from the legacy `app.domain.*` shim paths to the canonical `quant.*` paths. Do NOT change any logic. Do NOT delete shims (Phase 3 deletes them after all tracks merge — a shim may be used by consumers in another track).

**Rules:**
- Only edit the files listed in your track brief. Do not touch other files.
- For each file: `grep -n "from app\.\|import app\." <file>` to find brain imports; replace each with the canonical `quant.*` path.
- **Find the canonical path** by grepping for the symbol in quant: `grep -rn "def <symbol>\|class <symbol>" /Users/apple/Documents/<YOUR-WORKTREE>/quant --include="*.py"`. Use that module path. If a symbol is exported from a package `__init__`, use the package path.
- Keep imports sorted/grouped as the file already has them. Preserve lazy (function-level / TYPE_CHECKING) imports as lazy, just with the new path.
- If a `quant.*` import would create a circular import (the file imports a symbol that imports this backend module back), fall back to the legacy shim path with a `# TODO(p2): circular — resolve in Phase 3` comment and report it.

**Canonical import map (quick reference):**
- `app.domain.trading.models.*` → `quant.contracts.*`
- `app.domain.trading.{events,event_store}` → `quant.contracts.{events,event_store}`
- `app.domain.trading.services.{risk_manager,kill_switch,signal_validator}` → `quant.execution.{risk_manager,kill_switch,signal_validator}`
- `app.domain.ports.*` → `quant.contracts.ports.*`
- `app.domain.constants` → `quant.contracts.constants`
- `app.domain.models.exchange_config` → `quant.contracts.exchange_config`
- `app.domain.fabio_ai.services.amt_analyzer` → `quant.amt.analyzer`
- `app.domain.fabio_ai.services.mlx_compute` → `quant.amt.compute`
- `app.domain.fabio_ai.services.{cvd_tracker,orderflow_detectors,aggression_scorer,order_flow_service,footprint_analyzer,drive_tracker,drive_decay}` → `quant.amt.orderflow.{cvd,detectors,aggression,service,footprint,drive,drive_decay}`
- `app.domain.fabio_ai.services.{profile_factory,profile_classifier}` → `quant.amt.profile.{factory,classifier}`
- `app.domain.fabio_ai.services.{market_state_engine,market_structure_classifier,opening_classifier,regime_detector}` → `quant.amt.market.{state_engine,structure,opening,regime}`
- `app.domain.fabio_ai.services.{session_context,session_context_factory,npoc_tracker,eia_calendar,option_scanner,option_selector}` → `quant.amt.session.{context,context_factory,npoc,eia,scanner,selector}`
- `app.domain.fabio_ai.services.{exit_engine,exit_rules,exit_signal,trail_engine,scale_manager,pyramid_manager,partition_exit_manager,loss_tracker,session_risk_manager}` → `quant.execution.{exit_engine,exit_rules,exit_signal,trail,scale,pyramid,partition,loss_tracker,session_risk_manager}`
- `app.domain.fabio_ai.services.{gate_pipeline,position_sizer,signal_coordinator,trade_thesis,vwap_breakout,prediction_engine,learning_engine}` → `quant.decision.{gates.legacy_gate_pipeline,sizer,signal_coordinator,trade_thesis,vwap_breakout}` / `quant.inference.{prediction,learning_engine}`
- `app.domain.fabio_ai.services.{generative_ai_service,prompt_builder,llm_contract}` → `quant.inference.{generative_ai,prompt_builder,llm_contract}`
- `app.domain.fabio_ai.services.entry_gates.*` → `quant.decision.gates.*`
- `app.domain.fabio_ai.models.{predictions,observation}` → `quant.inference.models` / `quant.amt.models.observation`
- `app.domain.fabio_ai.rl.*` → `quant.inference.rl.*`
- `app.domain.fabio_ai.strategy.{protocols,setup_detector,fabio_detectors,squeeze_detector}` → `quant.amt.strategy.*` (these may not be migrated yet — if missing in quant, KEEP the legacy import with `# TODO(p2)` and report)
- `app.domain.probability.*` → `quant.probability.*`
- `app.domain.services.{volume_profile,delta_profile,lvn_detector,aggressive_prints,tick_delta,initial_balance_engine,ib_breakout_scalp,one_min_bar_engine,symbol_registry,underlying_futures_provider}` → `quant.amt.{profile,profile,profile,orderflow,orderflow,session.ib_engine,session.ib_scalp,session.one_min_bar,session.symbol_registry,session.futures_provider}.*`
- `app.domain.services.{displacement_detector,break_detector,lvn_play_detector,acceptance_rejection}` → `quant.amt.market.{displacement,break_detector,lvn_play,acceptance_rejection}`
- `app.domain.services.{risk_sizing_engine,risk_tier_engine,circuit_breakers,trade_costs}` → `quant.execution.{risk_sizing,risk_tier,circuit_breakers,trade_costs}`
- `app.domain.services.{scalp_gate_pipeline,short_signal_gates}` → `quant.decision.gates.{scalp,short}`
- `app.domain.services.{decimal_utils,tick_utils,market_data_utils,candle_metrics}` → `quant.contracts.*`
- `app.domain.services.{position_reconciliation,startup_reconciliation,self_healing,mobile_alerts,gate_rejection_tracker,latency_tracker}` → STAY in backend (`app.domain.services`) — these are ops modules that remain; do not remap them.
- `app.shared.timezones` → `quant.contracts.timezones`
- `app.core.async_boundary` → STAY (`app.core`) — backend core helper, not brain.
- `app.domain.models.{market_state,exchange}` → STAY.

**Verification (per file batch and at end):**
```bash
cd /Users/apple/Documents/<YOUR-WORKTREE>/backend
/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short --continue-on-collection-errors
cd /Users/apple/Documents/<YOUR-WORKTREE>
/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short
```
Report exact pass/skip/error counts. The 4 pre-existing env errors (gymnasium + 3 httpx) are acceptable; any NEW failure must be fixed or explained.

**Commit:** one commit per logical file-group, or one commit for the whole track: `refactor(backend): <layer> imports brain from quant.*`

**Report contract:** write to `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/<track>-report.md`: files changed, any circular-import fallbacks (`# TODO(p2)`), any `# TODO(p2)` for unmigrated strategy modules, test counts.
