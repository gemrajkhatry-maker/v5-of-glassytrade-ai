# Task 2 Report: Block Proxy AMT Entries in Live Mode

## Files

- `quant/decision/decision_service.py`: added metadata to the existing decision contract.
- `quant/engine/decision_loop.py`: added the live proxy gate before translation, sizing, and submission; preserved certification and decision events.
- `quant/runtime.py`: wired live detection from the existing `LiveOMS`/`PaperOMS` boundary.
- `tests/quant/decision/test_proxy_live_entry_block.py`: added live block, paper allow/metadata, exact-data, and OMS spy tests.

## Red/Green

Red: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_proxy_live_entry_block.py -q` produced `2 failed`, because proxy decisions reached submission and had no metadata field.

Green: the focused proxy suite passed after the implementation. The affected decision-loop/submission suites passed `56 passed`. The combined certification command had one known unrelated dirty-worktree failure in `test_s5_conviction_formula_is_explicit`.

## Rationale

The existing OMS injection is the live/paper boundary. The gate reuses `DataQuality` and normalization, blocks `CANDLE_DISTRIBUTED` and `UNAVAILABLE` in live mode, and marks non-exact paper/replay decisions `PROXY_MODE` without upgrading evidence.

## Concerns

- The broader certification suite retains the known unrelated AMT scenario failure.
- `PROXY_MODE` is carried in `QuantDecision.metadata` and certification records only; no broader UI schema change was made.
