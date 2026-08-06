# amt_dataset — Training Data Inventory

## `nifty_amt_data/` — shipped adapter training data (key:value ChatML)

The dataset the shipped `models/vibethinker-amt-lora` adapter was trained on
(`adapter_config.json` data path). Split: **920 train / 115 val / 115 test**
rows. Each row is ChatML with a `key: value` user block (e.g. `session: nse`,
`poc: above`) and an assistant JSON with a 4-key schema
`{direction, confidence, setup, rationale}` — a **10-setup vocabulary**
(`EXHAUSTION`, `MEAN_REVERSION`, `NO_REENTRY`, `NO_TRADE`, `PREPARE`,
`RISK_CHECK`, `STOP_TRADING`, `STRUCTURAL`, `TRIPLE_A`, `WAIT`).

This format is what the live app sends **at training time, not at inference**:
the live entry prompt is narrative prose (see below), so this split is the raw
source, not the retrain target.

## `nifty_amt_data_livefmt/` — regenerated live-prose format (retrain target)

Regenerated from `nifty_amt_data/` with the shared live renderer:

```bash
cd backend && PYTHONPATH=..:. python scripts/dataset_render.py
```

Each user block is parsed by `key_value_to_fields` and rendered through
`prompt_builder.render_entry_prompt(fields)`, producing the exact live narrative
(`SESSION: …`, `MARKET STATE: …`, `ORDER FLOW & AGGRESSION: …`, dataset context),
and the assistant target is restricted to the live 3-key contract
`{direction, confidence, rationale}` (the dataset-only `setup` key is dropped).

**This is the recommended retrain data** — it matches what
`prompt_builder.render_entry_prompt` emits at inference, eliminating the
key:value ↔ narrative prose distribution shift. Parity between the dataset and
the live prompt is guarded by
`backend/tests/unit/scripts/test_dataset_live_parity.py`, which asserts every
numeric dataset field appears in the rendered prose (excluding `delta` and
`cvd_slope`, which the live narrative deliberately categorizes rather than
prints).

## Removed artifacts

- `amt_data_final/` — unused US-AMT training set (dropped; this repo ships only
  the Indian NIFTY/BankNifty data the adapter actually trained on).
- `stats.json` — stale file claiming 78,681 rows; removed as inaccurate (actual
  corpus is 1,150 rows across the three splits).
