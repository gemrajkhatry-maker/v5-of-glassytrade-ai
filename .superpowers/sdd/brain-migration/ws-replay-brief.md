# WS-REPLAY — Golden-file replay harness + recorder (architecture proposal §5.2, §5.4)

**Worktree:** `/Users/apple/Documents/wt-ws-replay` (branch `migration/ws-replay`). Work ONLY there.

**Context:** The proposal's "superpower" is golden-file replay: capture a real session's bar sequence once, replay it through the analysis layer, assert the `AuctionState` series matches byte-for-byte (catches VP/VWAP/absorption/Triple-A drift). The backend has no recorded tick/bar capture yet (databases show 0 ticks), so the harness must be built + a live-capture recorder added; the byte-for-byte gate against a REAL day is enabled but not yet filled.

**Deliverable 1 — `quant/tools/replay.py`** (pure, no backend imports):
- `capture(bars, analyzer) -> list[AuctionState]` and `replay(states, analyzer) -> list[AuctionState]` — capture builds a JSONL golden file of (bar → AuctionState) for a given `AuctionCoordinator`/`AMTAnalyzer` instance; replay feeds the same bars back and returns states.
- `assert_replay_equal(golden_path, analyzer)` — replays the golden file and raises on ANY field divergence (floats within 1e-9; enums/str exact).
- Deterministic: a fresh analyzer instance per replay.

**Deliverable 2 — a real (synthetic) golden fixture + determinism test:**
- `tests/quant/replay/test_replay.py`: (a) build a deterministic 120-bar session (extend the `_session_bars()` shape from `tests/quant/test_golden_file.py` with more varied bars: absorption spikes, quiet bars, VA-edge bars); (b) capture → golden JSONL committed at `tests/fixtures/replay/session_120.jsonl`; (c) replay twice with fresh analyzers → byte-equal; (d) mutate one bar's volume and assert the replay test FAILS (proves drift detection).
- This is the §5.2 determinism test. Reuse the existing `tests/quant/test_golden_file.py` determinism pattern.

**Deliverable 3 — live-capture recorder hook (backend):**
- In `backend/app/application/services/quant_bridge.py::on_bar_close`, when env `QUANT_RECORD_REPLAY=1`, append `{"symbol", "time", "open","high","low","close","volume","buy_volume","delta","oi", "auction": auction_dto}` to `backend/live_trading_logs/replay_<symbol>_<date>.jsonl` (create the dir if needed). Add it as a guarded, cheap append (the main path unchanged when env is unset).
- Add a unit test for the recorder (env set → file written; env unset → no write).

**Verify:** `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant/replay backend/tests/unit/application/test_quant_bridge.py -q --tb=short` (worktree root). Full `tests/quant` green.

**Commits:** `feat(quant): replay harness + golden capture/replay`, `test(quant): replay determinism + drift detection`, `feat(backend): QUANT_RECORD_REPLAY live-capture hook`.

**Report:** `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/ws-replay-report.md` (note: a real-day capture is required to fill the byte-for-byte gate; the hook is ready). Reply: status, commits, test counts, concerns.
