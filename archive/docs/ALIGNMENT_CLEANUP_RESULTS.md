# Align to amt_dataset + Dead-Surface Removal — Results

**Date:** 2026-08-06 · **Branch:** stable_4 · **Plan:** docs/superpowers/plans/2026-08-06-align-to-amt-dataset.md

## What shipped (9 commits, all TDD/verified)

| Task | Commit | Result |
|---|---|---|
| T1 dead ML surface | `e722f2c` | Removed 5 legacy training scripts + their unit test, unused `amt_data_final/` (US-AMT, 760 rows), stale `stats.json` (claimed 78,681 rows; only 1,910 existed). `amt_dataset/` now = `nifty_amt_data/` only. |
| T2 dead frontend | `354d054` | Deleted 29 files: `components/intelligence/` (tabbed AI UI, unreachable), SystemStatusBar, ModelIOPanel, ChartExecutionMarkers, ProfileHistogram, CrosshairManager, websocket/manager, stores/streaming, stores/portfolio, utils/chartUtils, utils/lruCache + orphaned tests; removed dangling imports. |
| T3 phantom fields | `87070ab` | Removed reads of `amt.tradeDecision/direction/pLong/pShort/agentRegime/agentTiming/agentKelly/agentRationale/tickSize/optionType/underlyingPrice/amtTimeWindow`, `state.depth20Active/feed/execution/readiness/state_digest`, `rejectionFromVah/Val`; rewired DecisionCard to real `agentDecision`; removed default UNSAFE badges; dropped prediction series. |
| T4 dead types | `5717830` | Pruned `types.ts` (AMTAnalysis 16 phantom members, TradeSignal, StrategyStats, ChartConfig.showPredictions, MessageRole/ChatMessage/AICommandResponse); deleted orphaned `types_generated.ts` + `types_rl.ts`; added source-level parity test. |
| T5 dead prompt keys | `db9dc56` | Removed `gate_context`/`session_context_for_llm`/`strategy_hint` from `market_data_ai` and the dead `delta` read in `_build_narrative_order_flow`. |
| T6 shared renderer | `b75da84` | Extracted pure `render_entry_prompt(fields)` used by both live `build_entry_prompt` and new `scripts/dataset_render.py`; converts `key: value` rows → live prose + 3-key assistant; produced `nifty_amt_data_livefmt/` (920/115/115). |
| T7 train config | `7068e26` | Committed `scripts/mlx_lora_retrain.yaml` (mirrors adapter_config.json exactly: 300 iters, lr 2e-5, rank 8, scale 20, 16 layers, mask_prompt) + `scripts/train_mlx.sh` entry point — a retrain is now reproducible. |
| T8 parity + README | `ef9a407` | Dataset↔live-prompt parity test; found & fixed a real gap (`price`→`ltp` was lost without vah/val → added dataset-only LOCATION fallback); `amt_dataset/README.md` documents both datasets. |

## Verified results

- **Backend tests:** 1817 passed / 77 skipped (only pre-existing env-broken suites ignored).
- **Frontend:** `npm run build` clean; **215 tests passed** (was 208 pre-cleanup).
- **Live smoke:** model loads, 3 contracts scanned, engine streams, **LLM fires** (renderer refactor didn't break inference), live prompt still renders `SESSION:` + `VWAP`, **0 tick errors**.
- **Alignment achieved:** retrain data (`nifty_amt_data_livefmt`) now matches what the app actually sends (`render_entry_prompt` output), assistant contract restricted to the live 3-key `{direction, confidence, rationale}`.

## Remaining known items (non-blocking)

- `amt_dataset/*.jsonl` remain gitignored (`**/*.jsonl`) — data lives in the working tree; `README.md` is the versioned inventory. To retrain from a fresh clone, run `scripts/dataset_render.py` first (or un-ignore the datasets, ~1.2 MB).
- `delta` is still emitted in `market_data_ai` but read by no prompt block (prunable later); `strategy_hint` remains in `llm_entry_handler`'s queue/save paths (out of scope).
- Training system prompt (`_DEFAULT_INSTRUCTION` with DECISION HIERARCHY + AMT RULES) is not yet baked into the dataset's system message — aligning that is a follow-up.
- `nifty_amt_data` direction skew (65% FLAT) is preserved as ground truth; not rebalanced.
