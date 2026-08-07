# Task 0.2 — Move shared models + ports into `quant/contracts/` (with shims)

**From:** docs/superpowers/plans/2026-08-06-quant-brain-migration.md — Phase 0, Task 0.2

**Goal:** Move the shared contract types (trading models, ports, constants, exchange_config, timezones, 4 shared utils) and the two exit helper modules that the models depend on, from `backend/app/domain/` into `quant/contracts/` (and `quant/execution/`), leaving a **re-export shim** at every legacy path so the backend keeps working. This is the highest-risk task: everything imports these. Do it one file at a time, verifying the backend unit suite after each.

**Files to move (in this exact order — leaf deps first):**

1. `backend/app/domain/trading/models/enums.py` → `quant/contracts/enums.py`
2. `backend/app/domain/trading/models/value_objects.py` → `quant/contracts/value_objects.py`
3. `backend/app/domain/constants.py` → `quant/contracts/constants.py`
4. `backend/app/domain/trading/models/utils.py` → `quant/contracts/utils.py`
5. `backend/app/domain/trading/models/volume_profile.py` → `quant/contracts/volume_profile_models.py` (keep all exports identical)
6. `backend/app/domain/trading/models/vwap_bands.py` → `quant/contracts/vwap_bands.py`
7. `backend/app/domain/trading/models/cvd.py` → `quant/contracts/cvd.py`
8. `backend/app/domain/trading/models/initial_balance.py` → `quant/contracts/initial_balance.py`
9. `backend/app/domain/fabio_ai/services/exit_signal.py` → `quant/execution/exit_signal.py` (early move)
10. `backend/app/domain/fabio_ai/services/exit_rules.py` → `quant/execution/exit_rules.py` (early move — depends on enums, constants, exit_signal)
11. `backend/app/domain/trading/models/entities.py` → `quant/contracts/entities.py` (depends on enums, exit_rules, decimal_utils)
12. `backend/app/domain/trading/models/aggregates.py` → `quant/contracts/aggregates.py` (depends on enums, entities, value_objects, exit_rules)
13. `backend/app/domain/trading/models/trading_context.py` → `quant/contracts/trading_context.py`
14. `backend/app/domain/trading/events.py` → `quant/contracts/events.py`
15. `backend/app/domain/trading/event_store.py` → `quant/contracts/event_store.py`
16. `backend/app/domain/models/exchange_config.py` → `quant/contracts/exchange_config.py`
17. every file in `backend/app/domain/ports/*.py` → `quant/contracts/ports/<same name>.py`
18. `backend/app/shared/timezones.py` → `quant/contracts/timezones.py`
19. `backend/app/domain/services/decimal_utils.py` → `quant/contracts/decimal_utils.py`
20. `backend/app/domain/services/tick_utils.py` → `quant/contracts/tick_utils.py`
21. `backend/app/domain/services/market_data_utils.py` → `quant/contracts/market_data_utils.py`
22. `backend/app/domain/services/candle_metrics.py` → `quant/contracts/candle_metrics.py`

**Import-rewrite map (apply to the moved file's own imports):**
- `app.domain.trading.models.enums` → `quant.contracts.enums`
- `app.domain.trading.models.value_objects` → `quant.contracts.value_objects`
- `app.domain.trading.models.entities` → `quant.contracts.entities`
- `app.domain.trading.models.aggregates` → `quant.contracts.aggregates`
- `app.domain.trading.models.<x>` → `quant.contracts.<x>`
- `app.domain.trading.events` / `event_store` → `quant.contracts.events` / `quant.contracts.event_store`
- `app.domain.ports.<x>` → `quant.contracts.ports.<x>`
- `app.domain.constants` → `quant.contracts.constants`
- `app.domain.models.exchange_config` → `quant.contracts.exchange_config`
- `app.shared.timezones` → `quant.contracts.timezones`
- `app.domain.services.decimal_utils|tick_utils|market_data_utils|candle_metrics` → `quant.contracts.<same>`
- `app.domain.fabio_ai.services.exit_signal` → `quant.execution.exit_signal`
- `app.domain.fabio_ai.services.exit_rules` → `quant.execution.exit_rules`

**Shim template** — after each move, write at the legacy path:
```python
"""Re-export shim — moved to <quant target>. Delete after importers switch (Phase 3)."""
from quant.<target> import *  # noqa: F401,F403
```
If the module defines `__all__`, include it: `from quant.<target> import __all__  # noqa: F401`.

For `ports/`: `quant/contracts/ports/__init__.py` re-exports every port module. The legacy `backend/app/domain/ports/*.py` each become a shim.

**Special cases:**
- `entities.py` also imports `app.domain.services.decimal_utils.to_decimal` → rewrite to `quant.contracts.decimal_utils.to_decimal`.
- `trading_context.py` has only `TYPE_CHECKING` imports — leave them as strings under `if TYPE_CHECKING:`; if any point at legacy brain modules (e.g. `fabio_ai.services.session_context`, `probability.agent_pipeline`), leave them as-is (they are lazy) and add `# TODO(migration)` — they resolve once those modules move in Phase 1.
- `ports/exchange_strategy.py` imports `ExchangeConfig` — now `quant.contracts.exchange_config.ExchangeConfig`.
- `exit_rules.py` has `from app.domain.fabio_ai.services.exit_signal import ExitSignal` → `quant.execution.exit_signal`.
- Do NOT edit the moved files' logic beyond import rewrites. Preserve every public name, field, and constant exactly.

**Port the tests:** copy these backend test files into `tests/quant/contracts/` (adjusting imports to `quant.contracts.*` / `quant.execution.*`):
- `backend/tests/unit/domain/trading/models/*` (entities, aggregates, value_objects, enums, utils, trading_context, volume_profile, vwap_bands, cvd, initial_balance) — copy whatever exists
- `backend/tests/unit/domain/fabio_ai/test_exit_rules*.py` and any `test_exit_signal*.py` → `tests/quant/execution/`
- `backend/tests/unit/domain/test_constants*.py` if it exists → `tests/quant/contracts/`
Keep the backend copies in place (they still pass via shims). Just ADD the quant copies.

**Verification (run after EACH move, then once more at the end):**
```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai/backend
/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short -x   # backend green via shims
cd /Users/apple/Documents/v5-of-glassytrade-ai
/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short     # quant green
```
The backend suite is large; after the first few moves you may spot-check with `-q` and full-run once at the end. Do not commit a move that breaks the backend suite.

**Commit:** one commit for the whole batch (or one per logical group) with message `refactor(quant): move trading models + ports into quant/contracts`.

**Zero-backend-import rule:** after this task, `grep -rn "import app\.\|from app\." quant/contracts quant/execution/exit_signal.py quant/execution/exit_rules.py --include=*.py` must return nothing (except `# TODO(migration)` comments).

## Report contract

Write your report to `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/task-0.2-report.md`:
- Commit hash(es)
- List of every moved file → target
- The `grep` result proving zero backend imports in moved code (or the exceptions)
- Test output tails (backend unit + quant)
- Any import cycles or surprises you hit and how you resolved them

Return: status (DONE / DONE_WITH_CONCERNS / BLOCKED), commit hash, one-line test summary, and any concerns.
