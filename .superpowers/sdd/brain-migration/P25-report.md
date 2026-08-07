# P2.5 Report — Infrastructure adapters import brain from `quant.*`

- **Status:** DONE — all imports swapped, all tests green (only the 4 pre-existing env errors).
- **Commit:** `dd7efa0` `refactor(backend): infrastructure adapters import brain from quant.*` (10 files, 28 insertions, 28 deletions) on branch `migration/P25`.

## Files changed

| File | Imports remapped |
|---|---|
| `adapters/delta_profile_adapter.py` | `app.domain.ports.delta_profile` → `quant.contracts.ports.delta_profile`; `app.domain.constants` → `quant.contracts.constants`; `app.domain.services.delta_profile` → `quant.amt.profile.delta_profile` |
| `adapters/npoc_adapter.py` | `app.domain.ports.npoc` → `quant.contracts.ports.npoc`; `app.domain.fabio_ai.services.npoc_tracker` → `quant.amt.session.npoc` |
| `adapters/lgbm_probability_adapter.py` | `app.domain.ports.probability_inference` → `quant.contracts.ports.probability_inference`; `app.domain.probability.features` → `quant.probability.features` |
| `adapters/mlx_inference_adapter.py` | `app.domain.fabio_ai.services.llm_contract` → `quant.inference.llm_contract`; `app.domain.ports.llm_inference` → `quant.contracts.ports.llm_inference` |
| `adapters/gguf_inference_adapter.py` | same as mlx_inference_adapter |
| `adapters/paper_broker.py` | `app.domain.trading.models.entities` → `quant.contracts.entities`; `app.domain.trading.models.aggregates` → `quant.contracts.aggregates`; `app.domain.ports.broker` → `quant.contracts.ports.broker`; `app.domain.services.trade_costs` → `quant.execution.trade_costs` |
| `adapters/dhan_adapter.py` | `app.domain.trading.models.value_objects` → `quant.contracts.value_objects`; `app.domain.ports.market_data` → `quant.contracts.ports.market_data`; `app.domain.services.market_data_utils` → `quant.contracts.market_data_utils`; `app.shared.timezones` → `quant.contracts.timezones` |
| `serialization/schemas.py` | lazy imports: `app.domain.trading.models.value_objects` → `quant.contracts.value_objects` (x2); `app.domain.fabio_ai.models.predictions` → `quant.inference.models` (ModelWeights) |
| `metrics.py` | no brain imports — no change |
| `strategies/mcx_strategy.py` | `app.domain.models.exchange_config` → `quant.contracts.exchange_config`; `app.domain.ports.exchange_strategy` → `quant.contracts.ports.exchange_strategy`; `app.shared.timezones` → `quant.contracts.timezones` |
| `strategies/nse_strategy.py` | same as mcx_strategy |

## Verification

- `backend/tests/unit`: **1324 passed, 60 skipped, 4 errors**. The 4 errors are the pre-existing env failures (1 gymnasium `ModuleNotFoundError` in `test_valentini_rl.py` + 3 httpx in `test_optimizations.py::TestDebugMemoryEndpoint`) — no NEW failures.
- `tests/quant`: **1448 passed, 30 skipped, 0 errors**.
- All 11 target modules import cleanly from the `quant.*` paths (verified via a direct import smoke test).

## `# TODO(p2)` fallbacks

- **None.** All canonical `quant.*` targets existed. No circular imports: a grep confirmed no `quant/` module imports any backend `app.*` module (one hit in `quant/contracts/value_objects.py` is a comment, not an import). No unmigrated strategy modules were needed in this track.

## Concerns

- `metrics.py` was listed in the brief but contained no brain imports; left untouched.
- None of the swapped symbols changed identity — every `app.domain.*` path used here is a re-export shim pointing at the exact `quant.*` module used, so this is a pure path swap with zero behavioral change.
