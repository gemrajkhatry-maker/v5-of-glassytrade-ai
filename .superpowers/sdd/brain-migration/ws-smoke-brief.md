# WS-SMOKE — In-process paper-smoke protocol test (architecture proposal §5.5)

**Worktree:** `/Users/apple/Documents/wt-ws-smoke` (branch `migration/ws-smoke`). Work ONLY there.

**Context:** §5.5 paper week 1: "identical to live data feed, no fills risk. Compare paper trades to AuctionState — any trade that fires with no edge is a bug, not a loss." This must run in CI with NO network/broker. The existing `tests/system/test_quant_runtime_e2e.py` already boots the deterministic `QuantEngine` (feed → AuctionCoordinator → DecisionService → PaperOMS → exits → Journal → StateProjector WS). Extend the coverage to assert the paper-protocol invariants.

**Task — add `tests/system/test_paper_protocol.py`:**
1. Boot a fresh `QuantEngine` with the `SyntheticGateway` on a deterministic 240-bar session that contains: a clean AGGRESSION-LONG setup, a VAL-bounce fade setup, and long quiet stretches.
2. **Invariant A — no-trade-no-edge:** over the whole replay, every `PositionOpened` event must correspond to a prior bar whose `AuctionState` produced an approved `QuantDecision` (assert position.open reason/trace maps to an approved decision; count approved-decisions-without-position and assert they're explainable by risk/cooldown — log them, don't fail on cooldown skips).
3. **Invariant B — no fabricated data:** every bar processed by the engine is a real bar from the feed (assert the StateProjector's `auction`/`tick` never carries zero-volume candles for non-zero-volume inputs; assert no bar count inflation vs the feed).
4. **Invariant C — fill within spread:** paper fills (entry/exit prices in `Position` events) are within ±1 tick of the bar close used to generate the signal (slippage model).
5. **Invariant D — idempotent exits:** each position closes exactly once (one `PositionClosed`/EXIT per position_id).
6. Assert the WS contract still carries the `auction` + `quantDecision` keys for the approved setup bar.

**Rules:** reuse existing harness (`tests/quant/test_golden_file.py::_session_bars` shape or the SyntheticGateway from `quant/brokers/synthetic.py`); do not weaken the deterministic engine; no network.

**Verify:** `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/system -q --tb=short` (worktree root). Full `tests/quant tests/system` green.

**Commits:** `test(system): paper-protocol invariants (no-trade-no-edge, no-fabricated-data, fill, idempotent exits)`.

**Report:** `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/ws-smoke-report.md` (list the approved-decisions-without-position count + reasons, and any invariant that failed and how you handled it). Reply: status, commits, test counts, concerns.
