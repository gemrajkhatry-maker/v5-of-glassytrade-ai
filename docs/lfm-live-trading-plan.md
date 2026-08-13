# LFM2.5 → Live Trading: End-to-End Readiness Plan

Goal: make the LFM2.5-2.6B + `nifty_amt_lora` model (copied to `models/lfm2.5-2.6b-mlx-8bit/` + `models/lfm2.5-nifty-amt-lora/`) take **live trading decisions and execute them end to end**, with vibethinker retained as the fallback and a paper-first rollout.

---

## 0. Ground truth (what the codebase actually does today)

| Fact | Where |
|---|---|
| Model is env-selectable; default unchanged (`vibethinker-3b` + `vibethinker-amt-lora`); LFM lines are commented in root `.env` | `.env`, `quant/inference/mlx_inference_adapter.py` (`MLX_MODEL_PATH` / `MLX_ADAPTER_PATH`) |
| LFM loads in **1.3s**, generates in **1.5–3s**; vibethinker takes 20–78s (trips the 60s timeout) | measured this session; `LLM_TIMEOUT_SECONDS=60` |
| `predict()` → `parse_entry_response()` works with LFM today (unquoted JSON keys + `</think>` trace handled by existing fallbacks) | measured this session |
| **LLM is advisory-only. No model — including vibethinker — drives execution today.** `_decide()` gates on the deterministic Triple-A signal; the async `_schedule_llm()` only emits events + persists rows | `quant/runtime.py:251` `_decide`, `:583` `_schedule_llm` |
| `LLM_EXECUTION_ENABLED=true` in `.env` is surfaced in health/config only — **no behavioral code path** | `backend/app/config_models/settings_adapter.py:319`, `backend/app/api/routers/health.py:344` |
| Trade path exists: `_decide` → `_decision_service.evaluate(ctx)` (5 gates) → `SignalApproved` → `_oms.submit(signal, quantity)`; OMS = `PaperBroker` or `DhanBrokerAdapter` via `GLASSYTRADE_ENV` | `quant/runtime.py:251-288` |
| Training data: flat `key: value` NSE-only, ~35 scenarios × 50 dups (1680 rows); `dataset_render.py` already bridges to live narrative format → `amt_dataset/nifty_amt_data_livefmt/` | `amt_dataset/nifty_amt_data/`, `backend/scripts/dataset_render.py` |
| Retrain machinery exists: `backend/scripts/train_mlx.sh` + `mlx_lora_retrain.yaml` (currently points at vibethinker-3b) | `backend/scripts/` |
| **Prompt-shape mismatch to fix:** live sends the narrative in the SYSTEM message (`build_entry_prompt`) + a compact bar line in USER (`_llm_input`); training livefmt puts the narrative in the USER message + `_DEFAULT_INSTRUCTION` in SYSTEM | `quant/runtime.py:712` (`_llm_instruction`), `:806` (`_llm_input`), `dataset_render.py:render_row` |
| Live mode tonight is **MCX** (CRUDEOIL/GOLDM/SILVERM/NATURALGAS); LFM is trained on **NSE index** scenarios | `backend/config/strategies/mcx_options.yaml`, POC data |
| Per-decision audit trail exists: DB rows persist `input_prompt`, `instruction`, `raw_output`, direction, confidence → ready-made eval set | `backend/app/infrastructure/storage/database.py`, `quant/runtime.py:598-610` |
| Live order path has duplicate-order protection + idempotency (from prior session) | `brokers/broker/dhan/application/broker.py` |

**Headline:** the "trade end to end" gap is not LFM-specific — the LLM (any model) is not wired into the gates. Phase 3 below is the wiring; Phases 0–2 make LFM trustworthy enough to feed it.

---

## Phase 0 — Acceptance bar & offline eval harness

Deliverable: `backend/scripts/eval_lfm.py` + a written acceptance bar. **Nothing moves forward until it passes.**

1. **Batch replay on persisted decisions.** Read the DB's LLM rows (each has `input_prompt` + `instruction` + recorded vibethinker `direction`/`confidence`). Replay the exact live prompt pair through `MLXInferenceAdapter.predict()` with the LFM adapter and compare:
   - valid-JSON rate (must be ≥ 95% — current LFM on live-format input is lower than its training format),
   - direction agreement vs recorded vibethinker decision (≥ 70%),
   - where Triple-A fired, agreement vs the deterministic direction,
   - latency p95 (must be « 60s; LFM is ~2-3s).
2. **Held-out livefmt test split.** Run the same harness on `amt_dataset/nifty_amt_data_livefmt/test.jsonl` (210 rows) so scores are on data the model never saw, in the exact live vocabulary.
3. **Per-exchange breakdown** (NSE vs MCX rows) — the model will score differently on MCX until Phase 1 retrains.
4. Reuse/extend `backend/scripts/audit_llm_rationales.py` for rationale grounding (structure/flow keyword hits, lazy-phrase detection) on LFM output.
5. Write the bar into the doc: e.g. valid-JSON ≥ 95%, agreement ≥ 70%, p95 latency ≤ 10s, rationale score ≥ 6/10. Fail → iterate in Phase 1, don't wire.

## Phase 1 — Data + retrain (fix format & domain gaps)

1. **Fix the prompt-shape mismatch at the source.** Pick one canonical split and make live == training:
   - Recommended: change `QuantEngine._llm_instruction` so the narrative (`render_entry_prompt` + option block) goes in the **USER** message and the SYSTEM message is `_DEFAULT_INSTRUCTION`-style — matching what `dataset_render.py` already trains on. Update `_llm_input` accordingly (drop the redundant compact line, or keep it as a trailing context line).
   - Then re-run `dataset_render.py` so train/val/test == live byte-for-byte, and add a unit test asserting live instruction/user == training shape.
2. **Generate MCX live-format data.** Write `backend/scripts/generate_mcx_data.py` mirroring the AMT decision rules (from `generate_nifty_data.py` / `quant/triple_a.py` / `quant/amt/session/context.py` MCX phase table): commodity symbols, 09:00–23:15 phases, tick sizes, and the same scenario→decision mapping — **no 50× duplication**: render each scenario across real float ranges (POC/VAH/VAL/CVD/delta/VWAP with live-style magnitudes) so the model sees in-distribution numbers. Target ~3–5k rows. Extend the NSE generator the same way (dedup the current 50× copies).
3. **Retrain LFM2.5.** New config `backend/scripts/mlx_lora_retrain_lfm.yaml`:
   - `model: models/lfm2.5-2.6b-mlx-8bit`, `data: amt_dataset/nifty_amt_data_livefmt` (+ MCX livefmt),
   - capacity between the POC's 4-layer and vibethinker's 16-layer: start rank 8, **8–16 layers**, `max_seq_length: 2048` (live prompt is long), `mask_prompt: true`, `learning_rate: 2e-5`, iters 500–1000, `save_every: 100`.
   - Run via `python -m mlx_lm.lora --config backend/scripts/mlx_lora_retrain_lfm.yaml` (~1–2h on M1 Max).
4. **Re-run Phase 0** on the retrained adapter. Gate: meet the bar on BOTH NSE and MCX splits.

## Phase 2 — In-app integration hardening (parity with vibethinker)

1. **Switch `.env` to the LFM adapter**, restart the MCX backend, and observe ≥ 1 full session of bar closes: decisions parse, rationale grounded, DB rows persist `instruction`, no timeouts, `</think>`-trace output handled.
2. **JSON robustness** (only if Phase 0 shows drops): add a `</think>`-aware extractor and an unquoted-key repair to `_try_parse_json`/`_extract_json_candidate`; add regression tests pinning LFM-style output through `parse_entry_response`.
3. **Model identity**: add `mlxModel`/`mlxAdapter` (and validity-JSON-rate) to `/health` config so the dashboard shows which model is live; log model+adapter at load.
4. **Fallback chain**: if LFM's rolling invalid-JSON rate or timeout rate crosses a threshold (e.g. > 5% over 20 calls), auto-rollback `MLX_ADAPTER_PATH` to vibethinker and alert. Implement as a small wrapper in the composition root (env-driven, no code change to the adapter).

## Phase 3 — Wire the LLM into decisions ("trades end to end")

This is the real feature. Two tiers, paper-first:

**3a — LLM-consensus gate (safe default).**
- `_decide` already builds `DecisionContext`; add `llm_direction`/`llm_confidence` fields stamped by the fold-back thread (bar-stamped so a stale advisory can't leak into a later bar).
- Add gate 6 in `_decision_service.evaluate`: when `LLM_EXECUTION_ENABLED=true`, `SignalApproved` requires `llm_direction == agent_direction` (Triple-A) AND `llm_confidence == High`. The LLM becomes a **confirmation filter** on the deterministic kernel — it can only block, never invent.
- `LLM_EXECUTION_ENABLED` finally gates a real path (currently dead config).
- This works with either model, but LFM's speed makes the wait for consensus practical.

**3b — LLM-first path (later, optional, strictly capped).**
- When Triple-A is WAITING but LFM gives High-confidence direction with a coherent narrative (IB break + absorption + VWAP bias aligned), allow entry at reduced size (e.g. 1/3 of normal risk, hard SL, session-gate still enforced).
- Only LFM-class speed makes this viable (vibethinker can't answer inside the 5m bar); still keep it off until 3a has ≥ 2 green paper sessions.
- Add max N LLM-first trades/session and a dashboard kill switch.

**Rollout:** `GLASSYTRADE_ENV=paper` with 3a for ≥ 2 full sessions; compare paper P&L vs an LLM-disabled baseline on the same bars. Only then consider live (`GLASSYTRADE_ENV=live`, Dhan), starting with 1 symbol and the smallest lot.

## Phase 4 — Production safety & go-live

1. **Kill switch**: `LLM_EXECUTION_ENABLED=false` (env, hot-reloadable) + dashboard toggle; instant rollback to LLM-as-advisory-only.
2. **Risk caps**: LLM-gated trades capped at normal size (3a) or ⅓ (3b); no LLM involvement in the last hour of the session (close-protection already in gates 1/5); per-session trade caps.
3. **Monitoring**: per-model KPIs on the dashboard — valid-JSON %, latency p95, direction-vs-Triple-A agreement, timeout rate. Alert + auto-rollback on agreement < threshold.
4. **Eval loop**: nightly replay of the day's persisted decisions through both models (Phase 0 harness); promotion of a new adapter requires 2 consecutive green sessions.
5. **Run doc**: document model switch, execution-mode flags, and rollback procedure in `.freebuff/run.md`.

---

## Risk register

| Risk | Mitigation |
|---|---|
| LLM executes on hallucinated direction | 3a consensus gate (LLM can only block); 3b capped size + hard SL + session gate |
| MCX domain mismatch (model trained NSE) | Phase 1 MCX dataset; don't let LFM touch MCX live before it scores on MCX eval |
| Format mismatch (narrative in wrong role) | Phase 1 fix + unit test asserting live == training shape |
| `</think>`/unquoted-JSON parse drops | Phase 2 hardening + regression tests + auto-rollback |
| Stale advisory from fold-back thread | bar-stamped consensus fields in `DecisionContext` |
| vibethinker regression | default untouched; LFM behind env flag; auto-rollback wrapper |
| Paper ≠ live slippage | paper validation first; live rollout 1 symbol, smallest lot |

## Suggested order of work

1. Phase 0 harness + acceptance bar (½ day)
2. Phase 1 prompt-shape fix + MCX generator + retrain + re-eval (1–2 days)
3. Phase 2 switch + observe + harden (½–1 day)
4. Phase 3a consensus gate + paper sessions (1–2 days)
5. Phase 3b only after 3a green; Phase 4 ongoing

The single most important step is **Phase 0/1**: an LFM that cannot reliably answer the live prompt shape must never reach the gates, no matter how fast it is.
