# Fabio AMT Indian Options Behavior Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the active `quant/` strategy produce only structurally valid Fabio AMT entries, execute them safely as Indian options trades, and manage positions deterministically from entry through exit.

**Architecture:** Keep `AMTAnalyzer` as the canonical market-analysis source and `DecisionService` as the canonical entry decision source. The analyzer describes auction state; a setup state machine proves the entry sequence; the decision engine validates setup, option liquidity, risk/reward, and session rules; the execution layer owns fills, stops, trailing, partials, and forced exits. No LLM or UI component may approve a trade.

**Tech Stack:** Python 3.13, pytest, existing `quant/amt`, `quant/decision`, `quant/execution`, `quant/runtime`, Dhan/broker adapters, JSON session persistence.

## Global Constraints

- Do not build auction structure from option-premium candles when an underlying futures/index feed is available.
- `IMBALANCED` is a market regime, never an approval by itself.
- Every approved entry must identify one named setup and its evidence.
- `NO_EDGE` is the safe result for incomplete, stale, missing, or contradictory evidence.
- One position at a time unless the base position is risk-free and a separately validated pyramid setup exists.
- All monetary risk must be checked after Indian lot-size rounding.
- Use IST-aware session and expiry logic; never infer live behavior from synthetic timestamps.
- Preserve existing user changes and do not reintroduce the removed LLM decision layer.
- Every non-trivial behavior change gets a focused failing test before implementation.
- Run tests with `PYTHONPATH="$PWD:$PWD/backend"` until test discovery is made repository-independent.

## File Map

- Modify `quant/decision/context.py`: carry explicit setup evidence and option-risk facts.
- Modify `quant/decision_context_builder.py`: map AMT DTOs into evidence without converting regime into approval.
- Create `quant/decision/setup_state.py`: immutable setup/evidence types and setup validation.
- Modify `quant/decision/gates_edge.py`: validate completed setup sequences.
- Modify `quant/decision/decision_service.py`: enforce setup hierarchy and safe fallback behavior.
- Modify `quant/decision/va_fade.py`: require failed acceptance and structure-aware stops.
- Modify `quant/decision/signal_builder.py`: produce structural stops/targets and validate minimum stop distance.
- Modify `quant/amt_engine.py` and `quant/amt/analyzer.py`: expose complete, timestamped order-flow/setup evidence.
- Modify `quant/amt/orderflow/drive.py`: make D1/D2/D3 state and expiry/reset behavior explicit.
- Modify `quant/execution/risk.py`: enforce hard risk caps, lot-aware risk, and safe cushion sizing.
- Modify `quant/execution/exits.py` and `quant/execution/exit_rules.py`: centralize live position-management priority.
- Modify `quant/position_manager.py` and `quant/runtime.py`: wire entry, exit, risk, and session transitions through one path.
- Modify `quant/amt/session/context.py` and `quant/session_gates.py`: validate NSE/MCX session and expiry behavior.
- Modify `qa_sanity_components.py`, `qa_sanity_full_infra.py`: update stale QA scripts to current `quant` APIs.
- Modify `conftest.py` or project test configuration: make test imports work without manually setting `PYTHONPATH`.
- Add tests under `tests/quant/decision`, `tests/quant/amt`, `tests/quant/execution`, `tests/quant/runtime`, and `tests/system`.

---

### Task 1: Establish a reproducible baseline and event trace

**Files:**
- Create: `tests/system/test_fabio_behavior_trace.py`
- Modify: `quant/runtime.py` only if an existing event is missing from the trace

**Interfaces:**
- Consume `QuantEngine`/runtime events and `DecisionService` results.
- Produce a deterministic trace containing: bar time, session phase, market state, setup state, direction, gate results, decision reason, entry, stop, target, risk, and exit reason.

- [ ] **Step 1: Write failing tests for the minimum trace contract.**

```python
def test_incomplete_imbalanced_market_is_no_edge():
    decision = decision_for(imbalance=True, direction="LONG", absorption=False,
                           accumulation=False, aggression=False)
    assert decision.approved is False
    assert decision.reason == "NO_EDGE"

def test_completed_triple_a_is_approved_with_named_model():
    decision = decision_for(imbalance=True, direction="LONG", absorption=True,
                           accumulation=True, aggression=True)
    assert decision.approved is True
    assert decision.model_label == "Triple-A"
```

- [ ] **Step 2: Run the focused test and confirm the first test fails because `IMBALANCED` currently approves.**

Run: `PYTHONPATH="$PWD:$PWD/backend" pytest -q tests/system/test_fabio_behavior_trace.py -x`

- [ ] **Step 3: Record current behavior without changing production code.**

Run: `PYTHONPATH="$PWD:$PWD/backend" python - <<'PY'` with a neutral imbalanced context and save the output in the task notes.

- [ ] **Step 4: Commit only the baseline test and trace support.**

```bash
git add tests/system/test_fabio_behavior_trace.py quant/runtime.py
git commit -m "test: capture fabio decision behavior baseline"
```

### Task 2: Define explicit setup evidence and state transitions

**Files:**
- Create: `quant/decision/setup_state.py`
- Modify: `quant/decision/context.py`
- Add: `tests/quant/decision/test_setup_state.py`

**Interfaces:**
- `SetupType = Literal["TRIPLE_A", "SECOND_DRIVE", "LVN_SNIPER", "VA_FADE", "NONE"]`.
- `SetupEvidence` fields: `setup_type`, `direction`, `level`, `absorption`, `accumulation`, `aggression`, `acceptance`, `rejection`, `drive_number`, `d1_rejected`, `fresh_bars`, `cvd_agrees`, `obi_agrees`, `price_location`, `target`, `invalidation`, `evidence_age_bars`.
- `SetupEvidence.is_complete() -> bool`.
- `SetupEvidence.rejection_reason() -> str`.
- Add `setup_evidence: SetupEvidence | None` to `DecisionContext`.

- [ ] **Step 1: Write tests for each legal and illegal state transition.**

```python
def test_imbalanced_regime_is_not_a_setup():
    evidence = SetupEvidence(setup_type="NONE", direction="LONG")
    assert evidence.is_complete() is False

def test_triple_a_requires_all_three_legs_and_acceptance():
    evidence = triple_a(absorption=True, accumulation=True,
                        aggression=True, acceptance=True)
    assert evidence.is_complete() is True

def test_triple_a_without_accumulation_is_incomplete():
    evidence = triple_a(absorption=True, accumulation=False,
                        aggression=True, acceptance=True)
    assert evidence.is_complete() is False
```

- [ ] **Step 2: Implement only the value object and validation rules.**
- [ ] **Step 3: Run the focused tests.**

Run: `PYTHONPATH="$PWD:$PWD/backend" pytest -q tests/quant/decision/test_setup_state.py`

- [ ] **Step 4: Commit.**

```bash
git add quant/decision/setup_state.py quant/decision/context.py tests/quant/decision/test_setup_state.py
git commit -m "feat: model explicit fabio setup evidence"
```

### Task 3: Correct AMT-to-decision mapping

**Files:**
- Modify: `quant/decision_context_builder.py`
- Modify: `quant/amt_engine.py`
- Modify: `quant/amt/analyzer.py`
- Add: `tests/quant/decision/test_context_builder_behavior.py`

**Interfaces:**
- `DecisionContextBuilder.build(bar, symbol, market, contract_expiry, tick_size, bar_index, warm_bars, cooldown_remaining_sec, risk_state, amt_dto, interval_seconds=60)` must preserve `market_state` separately from `setup_evidence`.
- `AMTAnalyzer` DTO must expose the evidence required by `SetupEvidence`, including setup type, leg booleans, acceptance/rejection, level, age, direction, and target.

- [ ] **Step 1: Add tests proving regime does not create direction approval.**

```python
def test_imbalanced_context_has_no_setup_without_sequence():
    ctx = build_ctx({"marketState": "IMBALANCED", "ofi": 0.5})
    assert ctx.market_state.value == "IMBALANCED"
    assert ctx.setup_evidence is None or not ctx.setup_evidence.is_complete()
```

- [ ] **Step 2: Add tests for each DTO-to-setup mapping.**

```python
def test_triple_a_dto_maps_to_complete_setup():
    ctx = build_ctx({
        "marketState": "IMBALANCED", "setupType": "TRIPLE_A",
        "setupDirection": "LONG", "absorption": True,
        "accumulation": True, "aggression": True,
        "acceptance": True, "cvdAgrees": True,
    })
    assert ctx.setup_evidence.setup_type == "TRIPLE_A"
    assert ctx.setup_evidence.is_complete() is True
```

- [ ] **Step 3: Populate evidence from the analyzer’s actual state machine rather than deriving it from `marketState`.**
- [ ] **Step 4: Make missing or stale DTO fields produce `setup_evidence=None`, not inferred conviction.**
- [ ] **Step 5: Run focused analyzer/context tests.**

Run: `PYTHONPATH="$PWD:$PWD/backend" pytest -q tests/quant/decision/test_context_builder_behavior.py tests/quant/amt/test_analyzer.py`

- [ ] **Step 6: Commit.**

```bash
git add quant/decision_context_builder.py quant/amt_engine.py quant/amt/analyzer.py tests/quant/decision/test_context_builder_behavior.py
git commit -m "fix: separate market regime from setup evidence"
```

### Task 4: Implement correct Fabio setup approval flows

**Files:**
- Modify: `quant/decision/gates_edge.py`
- Modify: `quant/decision/decision_service.py`
- Add: `tests/quant/decision/test_setup_approval_flow.py`

**Interfaces:**
- `gate_triple_a_edge(ctx)` returns `passed=True` only for complete `SetupEvidence`.
- Preserve distinct reasons: `Triple-A`, `Second Drive`, `LVN Sniper`, `VA Fade`.

- [ ] **Step 1: Add failing tests for the four valid flows and invalid flows.**

```python
def test_imbalanced_without_setup_returns_no_edge():
    assert evaluate_case("IMBALANCED", setup=None).approved is False
def test_triple_a_requires_absorption_accumulation_aggression():
    assert evaluate_case("TRIPLE_A", absorption=True, accumulation=False, aggression=True).approved is False
def test_second_drive_requires_d1_rejection_and_d2():
    assert evaluate_case("SECOND_DRIVE", d1_rejected=False, drive_number=2).approved is False
def test_lvn_sniper_requires_lvn_return_and_absorption():
    assert evaluate_case("LVN_SNIPER", at_lvn=False, absorption=True).approved is False
def test_va_fade_requires_rejection_not_just_outside_va():
    assert evaluate_case("VA_FADE", outside_va=True, rejection=False).approved is False
def test_conflicting_cvd_blocks_direction():
    assert evaluate_case("TRIPLE_A", direction="LONG", cvd_agrees=False).approved is False
def test_stale_evidence_returns_no_edge():
    assert evaluate_case("TRIPLE_A", evidence_age_bars=99).approved is False
```

- [ ] **Step 2: Implement the setup-specific validators.**

The decision order must be:

```text
session/risk/position guards
→ setup evidence exists
→ setup evidence is complete and fresh
→ direction and CVD agree
→ price is not climax-extended
→ target/invalidation are valid
→ risk/reward passes
→ signal approved
```

- [ ] **Step 3: Remove the behavior where `IMBALANCED` alone returns Triple-A approval.**
- [ ] **Step 4: Run focused decision tests.**

Run: `PYTHONPATH="$PWD:$PWD/backend" pytest -q tests/quant/decision`

- [ ] **Step 5: Commit.**

```bash
git add quant/decision/gates_edge.py quant/decision/decision_service.py tests/quant/decision/test_setup_approval_flow.py
git commit -m "fix: approve only complete fabio setup sequences"
```

### Task 5: Correct value-area fades, stops, targets, and option translation

**Files:**
- Modify: `quant/decision/va_fade.py`
- Modify: `quant/decision/signal_builder.py`
- Modify: `quant/contracts/exchange_config.py`
- Add: `tests/quant/decision/test_va_fade_risk.py`
- Add: `tests/quant/decision/test_option_signal_translation.py`

**Interfaces:**
- `detect_va_fade(ctx)` requires failed acceptance outside VA, not merely `close < VAL` or `close > VAH`.
- A signal must carry `setup_type`, `underlying_level`, `invalidation_level`, `target_level`, and `risk_per_unit`.
- Minimum stop distance must be the greater of configured tick floor and measured structural/volatility floor.

- [ ] **Step 1: Write tests for rejection and stop behavior.**

```python
def test_price_outside_va_without_rejection_is_not_fade():
    assert detect_case(outside_va=True, rejected=False) is None
def test_rejected_val_probe_fades_to_poc():
    assert detect_case(outside_va=True, rejected=True).target == 100.0
def test_fade_stop_is_not_one_tick_when_structure_is_wider():
    assert detect_case(outside_va=True, rejected=True, structural_buffer=1.0).risk > 0.05
def test_target_after_costs_meets_minimum_rr():
    assert detect_case(outside_va=True, rejected=True, costs=0.2).rr >= 1.5
```

- [ ] **Step 2: Implement VA rejection using wick/close/acceptance evidence from the analyzer.**
- [ ] **Step 3: Calculate structural invalidation around VAL/VAH/LVN/absorption level.**
- [ ] **Step 4: Translate underlying invalidation into option risk using the existing option metadata/delta path; reject when no reliable conversion exists.**
- [ ] **Step 5: Run decision and signal tests.**

Run: `PYTHONPATH="$PWD:$PWD/backend" pytest -q tests/quant/decision`

- [ ] **Step 6: Commit.**

```bash
git add quant/decision/va_fade.py quant/decision/signal_builder.py quant/contracts/exchange_config.py tests/quant/decision
git commit -m "fix: make value-area signals structurally tradable"
```

### Task 6: Make Indian option selection and sizing risk-correct

**Files:**
- Modify: `quant/amt/session/selector.py`
- Modify: `quant/execution/risk.py`
- Modify: `quant/runtime.py`
- Modify: `quant/position_manager.py`
- Add: `tests/quant/amt/session/test_india_option_selection.py`
- Add: `tests/quant/execution/test_lot_aware_risk.py`

**Interfaces:**
- Option selection must return a contract with valid bid, ask, premium, volume/open interest, delta, expiry, lot size, and spread percentage.
- `SessionRisk.position_size(entry, sl, lot_size, multiplier=1.0) -> int` returns whole lots and never exceeds the configured rupee risk.
- Add hard caps: per-trade risk, daily loss, maximum lots, and expiry-day risk.

- [ ] **Step 1: Add failing tests for missing liquidity, spread, delta, lot rounding, and cushion caps.**

```python
def test_rejects_option_with_missing_bid_ask():
    assert select_case(bid=0.0, ask=0.0).accepted is False
def test_rejects_option_when_spread_exceeds_premium_limit():
    assert select_case(bid=10.0, ask=12.0, premium=10.0).accepted is False
def test_position_size_rounds_down_to_lots():
    assert size_case(risk_rupees=1000.0, loss_per_unit=7.0, lot_size=15).lots == 9
def test_lot_rounding_never_exceeds_rupee_risk_cap():
    assert size_case(risk_rupees=1000.0, loss_per_unit=7.0, lot_size=15).rupee_risk <= 1000.0
def test_expiry_day_uses_reduced_risk_cap():
    assert size_case(risk_rupees=1000.0, expiry_day=True).rupee_risk < size_case(risk_rupees=1000.0, expiry_day=False).rupee_risk
```

- [ ] **Step 2: Implement contract validation before order submission.**
- [ ] **Step 3: Compute risk from worst-case stop loss plus estimated spread, fees, and slippage.**
- [ ] **Step 4: Apply cushion tiers only inside the hard cap; never let the bonus create uncapped risk.**
- [ ] **Step 5: Verify quantity at the final OMS boundary after `clamp_quantity`.**
- [ ] **Step 6: Run risk and selector tests.**

Run: `PYTHONPATH="$PWD:$PWD/backend" pytest -q tests/quant/amt/session tests/quant/execution/test_risk.py tests/quant/execution/test_lot_aware_risk.py`

- [ ] **Step 7: Commit.**

```bash
git add quant/amt/session/selector.py quant/execution/risk.py quant/runtime.py quant/position_manager.py tests/quant/amt/session tests/quant/execution
git commit -m "fix: enforce Indian option liquidity and lot risk"
```

### Task 7: Make position management deterministic and thesis-aware

**Files:**
- Modify: `quant/execution/exits.py`
- Modify: `quant/execution/exit_rules.py`
- Modify: `quant/position_manager.py`
- Modify: `quant/contracts/entities.py`
- Add: `tests/quant/execution/test_position_management_flow.py`

**Interfaces:**
- Position metadata must retain setup type, entry level, invalidation, target sequence, session phase, expiry flag, entry CVD, and initial risk.
- Exit evaluation order:

```text
spread/liquidity emergency
→ hard stop
→ session/expiry force exit
→ thesis invalidation
→ structural target / partial
→ breakeven
→ trailing
→ time stop
```

- [ ] **Step 1: Write tests for every exit-priority branch.**

```python
def test_spread_emergency_precedes_normal_target():
    assert exit_case(spread_blowout=True, target_hit=True).reason == "SPREAD_BLOWOUT"
def test_hard_stop_precedes_trailing():
    assert exit_case(stop_hit=True, trailing_hit=True).reason == "SL"
def test_thesis_invalidation_exits_before_time_stop():
    assert exit_case(thesis_invalid=True, time_stop=True).reason == "THESIS_INVALIDATION"
def test_breakeven_arms_on_cvd_or_one_r():
    assert manage_case(cvd_confirmed=True).stop == manage_case().entry
def test_partial_target_leaves_only_risk_free_runner():
    assert manage_case(partial_target=True).runner_risk <= 0.0
def test_losing_position_cannot_pyramid():
    assert manage_case(unrealized_r=-0.2, pyramid=True).pyramid_allowed is False
def test_session_close_force_exits_open_position():
    assert exit_case(session_force_exit=True).reason == "SESSION_FORCE_EXIT"
```

- [ ] **Step 2: Remove duplicate or competing exit decisions between `exit_rules.py`, `exits.py`, and `PositionManager`; define one caller-owned priority.**
- [ ] **Step 3: Use current price in every scratch/time-stop calculation; never return an exit price of `0.0` for a live exit.**
- [ ] **Step 4: Ensure option spread blowout uses premium-relative spread and exits at a realistic executable side, not an unfillable midpoint.**
- [ ] **Step 5: Add structural trailing: VWAP band, next HVN/POC, or confirmed swing, selected from the position’s setup metadata.**
- [ ] **Step 6: Run execution tests.**

Run: `PYTHONPATH="$PWD:$PWD/backend" pytest -q tests/quant/execution tests/quant/runtime/test_exit_golden.py`

- [ ] **Step 7: Commit.**

```bash
git add quant/execution quant/position_manager.py quant/contracts/entities.py tests/quant/execution
git commit -m "fix: make position management thesis and priority deterministic"
```

### Task 8: Correct drive, bubble, squeeze, and order-flow lifecycle

**Files:**
- Modify: `quant/amt/orderflow/drive.py`
- Modify: `quant/amt/orderflow/detectors.py`
- Modify: `quant/amt_engine.py`
- Modify: `quant/amt/analyzer.py`
- Add: `tests/quant/amt/orderflow/test_setup_lifecycle.py`

**Interfaces:**
- Drive state must reset on the actual IST session date and expire stale levels.
- Bubble evidence must expose side, price zone, relative size, absorption, follow-through, contested status, and squeeze status.
- `SetupEvidence.evidence_age_bars` must prevent stale bubbles or absorption from approving a new trade.

- [ ] **Step 1: Add tests for D1, rejected D1, D2, D3 exhaustion, session reset, stale evidence, contested zones, and squeeze pullback.**
- [ ] **Step 2: Wire the tick footprint accumulator into the same analyzer call that produces the decision DTO.**
- [ ] **Step 3: Require price impact/follow-through checks before classifying aggression.**
- [ ] **Step 4: Treat opposing bubbles in the same zone as contested and return `NO_EDGE`.**
- [ ] **Step 5: Represent failed-auction squeeze as a setup with explicit trigger and invalidation; do not use a generic failed-auction block for every return.**
- [ ] **Step 6: Run order-flow and analyzer tests.**

Run: `PYTHONPATH="$PWD:$PWD/backend" pytest -q tests/quant/amt/orderflow tests/quant/amt/test_analyzer.py`

- [ ] **Step 7: Commit.**

```bash
git add quant/amt/orderflow quant/amt_engine.py quant/amt/analyzer.py tests/quant/amt/orderflow tests/quant/amt/test_analyzer.py
git commit -m "feat: complete order-flow setup lifecycle"
```

### Task 9: Correct session, expiry, and underlying-feed behavior

**Files:**
- Modify: `quant/amt/session/context.py`
- Modify: `quant/session_gates.py`
- Modify: `quant/runtime.py`
- Add: `tests/quant/test_india_session_contract.py`
- Add: `tests/quant/test_underlying_required.py`

**Interfaces:**
- Session functions must accept parseable ISO/epoch timestamps and explicitly classify synthetic replay timestamps.
- Live option trading must record whether analysis came from underlying or option fallback.
- Session phase, expiry cutoff, force-exit, and post-market behavior must be tested for NSE and MCX.

- [ ] **Step 1: Add boundary tests at 09:15, 09:30, 11:30, 14:00, 15:15, 15:30 IST and the configured MCX boundaries.**
- [ ] **Step 2: Add expiry-day tests for new-entry cutoff and force-exit behavior.**
- [ ] **Step 3: Reject live option trading when no underlying feed exists unless an explicit fallback mode is enabled and surfaced in the decision metadata.**
- [ ] **Step 4: Run session/runtime tests.**

Run: `PYTHONPATH="$PWD:$PWD/backend" pytest -q tests/quant/test_session_gates.py tests/quant/test_india_session_contract.py tests/quant/test_underlying_feed.py`

- [ ] **Step 5: Commit.**

```bash
git add quant/amt/session/context.py quant/session_gates.py quant/runtime.py tests/quant/test_india_session_contract.py tests/quant/test_underlying_required.py
git commit -m "fix: enforce Indian session and underlying feed rules"
```

### Task 10: Repair operational QA and test discovery

**Files:**
- Modify: `qa_sanity_components.py`
- Modify: `qa_sanity_full_infra.py`
- Modify: `conftest.py` or `pyproject.toml`/pytest configuration if present
- Add: `tests/test_qa_scripts.py`

**Interfaces:**
- QA scripts must use the current `quant.amt_engine.AMTEngine`, `quant.runtime.QuantEngine`, and current initialization methods.
- One documented command must run from repository root without manually setting `PYTHONPATH`.

- [ ] **Step 1: Add tests that execute both QA scripts through subprocess and assert exit code `0`.**
- [ ] **Step 2: Replace deleted `quant.coordinator` imports and removed `initialize_symbol()` calls with the current runtime APIs.**
- [ ] **Step 3: Configure test import paths in project configuration rather than relying on shell state.**
- [ ] **Step 4: Run the full suite from a clean shell.**

Run: `pytest -q --tb=short`

Expected: no collection errors; all active tests either pass or are explicitly marked skipped for unavailable live credentials.

- [ ] **Step 5: Commit.**

```bash
git add qa_sanity_components.py qa_sanity_full_infra.py conftest.py pyproject.toml tests/test_qa_scripts.py
git commit -m "test: restore repository QA and test discovery"
```

### Task 11: Add replay/golden behavior validation with Indian scenarios

**Files:**
- Create: `tests/system/fixtures/nse_fabio_scenarios.json`
- Create: `tests/system/test_nse_fabio_replay.py`
- Modify: `quant/persistence/journal.py` only if replay serialization is incomplete

**Required scenarios:**

1. Opening noise: no entry.
2. Balanced D-profile: no trend entry in rotation.
3. Valid VAL second-drive long.
4. Valid VAH second-drive short.
5. Imbalanced trend without absorption: no entry.
6. Complete Triple-A continuation: one entry.
7. Climax beyond VWAP ±2σ: no fresh entry.
8. Contested buy/sell bubbles: no entry.
9. Option spread blowout: immediate exit.
10. Expiry-day cutoff: no new entry and force exit.
11. Two losses: conservative risk tier.
12. Third loss or daily loss cap: halt.
13. Risk-free base position: allowed pyramid only after new confirmation.

- [ ] **Step 1: Create deterministic underlying bars, delta, depth, option quote, and timestamps for each scenario.**
- [ ] **Step 2: Assert exact setup, decision, quantity, position state, and exit event sequence.**
- [ ] **Step 3: Run replay tests before and after every strategy change.**

Run: `PYTHONPATH="$PWD:$PWD/backend" pytest -q tests/system/test_nse_fabio_replay.py tests/quant/test_golden_tape.py`

- [ ] **Step 4: Commit.**

```bash
git add tests/system/fixtures/nse_fabio_scenarios.json tests/system/test_nse_fabio_replay.py
git commit -m "test: add Indian Fabio behavior replay scenarios"
```

### Task 12: Paper-trading acceptance and live-readiness gate

**Files:**
- Modify: `docs/PAPER_LIVE_RUNBOOK.md`
- Create: `docs/FABIO_INDIA_BEHAVIOR_CONTRACT.md`
- Create: `backend/scripts/audit_fabio_behavior.py`

**Acceptance criteria:**

- No entry is approved solely because market state is `IMBALANCED`.
- Every approved decision contains setup type and evidence.
- Every option order contains valid quote, spread, expiry, delta, lot size, and rupee-risk metadata.
- No final quantity exceeds the configured risk cap after lot rounding.
- Session and expiry boundaries produce expected decisions in IST.
- Stop, target, breakeven, partial, trailing, spread emergency, thesis invalidation, and force-exit events are observable.
- Full automated suite passes from repository root.
- At least 20 paper sessions are replayed or recorded with no contract/risk/exit invariant violation before live enablement.
- Live mode remains disabled if underlying feed, quote quality, timestamp, or persistence checks fail.

- [ ] **Step 1: Document the behavior contract and event fields.**
- [ ] **Step 2: Implement the audit script to fail on false approvals, missing setup evidence, invalid risk, or invalid exit priority.**
- [ ] **Step 3: Run the paper acceptance checklist.**
- [ ] **Step 4: Commit documentation and audit tooling.**

```bash
git add docs/PAPER_LIVE_RUNBOOK.md docs/FABIO_INDIA_BEHAVIOR_CONTRACT.md backend/scripts/audit_fabio_behavior.py
git commit -m "docs: define Fabio India paper trading acceptance"
```

## Final verification commands

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
pytest -q --tb=short
python qa_sanity_components.py
python qa_sanity_full_infra.py
python backend/scripts/audit_fabio_behavior.py
```

Expected final state:

```text
market regime ≠ setup
setup ≠ approval
approval includes structure + liquidity + risk evidence
position management follows one deterministic priority
Indian option risk is lot-aware and premium-aware
replay and QA prove the behavior before live trading
```
