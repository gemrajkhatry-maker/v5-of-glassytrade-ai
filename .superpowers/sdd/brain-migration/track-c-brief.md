# Phase 1 Track C — Probability cluster → `quant/probability/`

**Worktree:** `/Users/apple/Documents/wt-gt-track-C` (branch `migration/track-C`). Do ALL work inside this worktree. Commit there. Do NOT touch `/Users/apple/Documents/v5-of-glassytrade-ai`.

**From:** docs/superpowers/plans/2026-08-06-quant-brain-migration.md — Phase 1, Track C. Recipe: `git mv` → rewrite `app.*` imports to `quant.*` → leave shim at legacy path → port backend tests → `assert_parity` test → run suites → commit `refactor(quant): move <module> from backend brain`.

**Modules to move (all into `quant/probability/`):**
1. `backend/app/domain/probability/features.py` → `quant/probability/features.py`
2. `backend/app/domain/probability/playbook.py` → `quant/probability/playbook.py`
3. `backend/app/domain/probability/regime_classifier.py` → `quant/probability/regime.py`
4. `backend/app/domain/probability/regime_hysteresis_store.py` → `quant/probability/regime_hysteresis.py`
5. `backend/app/domain/probability/direction_timing.py` → `quant/probability/direction_timing.py`
6. `backend/app/domain/probability/sizing.py` → `quant/probability/sizing.py`
7. `backend/app/domain/probability/labels.py` → `quant/probability/labels.py`
8. `backend/app/domain/probability/agent_pipeline.py` → `quant/probability/agent_pipeline.py` (biggest — 989 lines; do it LAST)
9. `backend/app/domain/probability/__init__.py` → becomes a re-export shim over `quant.probability` (it currently re-exports `RegimeState, RegimeHysteresis, classify_regime, DirectionSignal, pick_direction, assess_timing, calculate_timing_probability, kelly_size, adjust_sl_tp, select_playbook, playbook_thresholds, summarize_feature_drivers` + prompt-builder aliases — verify every name still resolves).

**Import-rewrite map:**
- `app.domain.trading.models.*` → `quant.contracts.*`
- `app.domain.constants` → `quant.contracts.constants`
- `app.domain.probability.<x>` → `quant.probability.<x>`
- **Track B is running in PARALLEL.** `agent_pipeline.py` imports `entry_gates.three_align.three_align_check` and `entry_gates.gate_runner.run_gate_pipeline`. Those are being moved by Track B (to `quant/decision/gates/`) — they are NOT in this worktree yet. KEEP the legacy lazy imports `from app.domain.fabio_ai.services.entry_gates...` with `# TODO(migration): switch to quant.decision.gates.* once Track B merges`.

**Tests to port** (from `backend/tests/unit/domain/probability/*`): all → `tests/quant/probability/`. Also `backend/tests/unit/domain/fabio_ai/test_agent_pipeline*.py` if any.

**Parity tests** via `assert_parity` (legacy shim vs moved): `extract_features` (synthetic OHLC+AMTResult; populate only accessed fields), `select_playbook`, `classify_regime`, `pick_direction`, `assess_timing`, `kelly_size`, `adjust_sl_tp`, `calculate_timing_probability` on fixed inputs. For `run_agent_pipeline` (needs a probability_engine): build a tiny fake engine returning fixed `ProbabilityEstimate`; skip if the stateful parts are too entangled — note the skip.

**Verification (after EACH module):**
```bash
cd /Users/apple/Documents/wt-gt-track-C
/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short
cd backend && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short
```
(The worktree has its own `backend/` — run from there. The 4 pre-existing env errors are unchanged.)

**Zero-backend-import rule:** `grep -rn "import app\.\|from app\." quant/ --include=*.py` → allowed: the Track-B `entry_gates` TODO in `agent_pipeline.py`, and Track-A5 `amt_analyzer` TODO in `quant/amt/profile/factory.py` (already there from stable_4). Nothing else new.

**Report:** write to `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/track-c-report.md` (commit hashes, TODO imports, test tails, parity skips). Reply: status, commits, one-line test summary, concerns.
