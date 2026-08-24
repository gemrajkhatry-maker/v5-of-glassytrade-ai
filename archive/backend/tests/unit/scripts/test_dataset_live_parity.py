"""Parity smoke test: every dataset row must render to live-vocabulary prose.

Guards against a field in amt_dataset/nifty_amt_data being silently dropped by
key_value_to_fields / render_entry_prompt — if a future dataset row introduces a
numeric key the renderer cannot emit, this test fails.

Deliberate exclusions (fields the live narrative never prints as a raw number):
- delta: no live prompt block reads it (T6 gotcha).
- cvd_slope: live _build_narrative_order_flow categorizes the magnitude
  ("CVD EXTREME BUYING" / "Sustained selling" etc.) and never prints the number
  itself — the dataset is rendered identically, so a retrain on
  nifty_amt_data_livefmt still matches live prose.
"""

import json

from quant.inference.prompt_builder import render_entry_prompt
from scripts.dataset_render import DATASET_DIR, key_value_to_fields

_CATEGORIZED = {"delta", "cvd_slope"}


def _rendered_contains(rendered: str, value) -> bool:
    if isinstance(value, bool):
        # Booleans are emitted semantically ("REJECTION at VAH.",
        # "SECOND DRIVE"), never as the literal string "True".
        return True
    if isinstance(value, float) and value.is_integer():
        # Narrative formats with :g / :.0f, dropping a trailing ".0"
        # (e.g. AUCTION entry=24800 for 24800.0).
        return str(int(value)) in rendered or f"{value:g}" in rendered
    return str(value) in rendered


def test_dataset_rows_render_with_live_vocab():
    with open(DATASET_DIR / "train.jsonl") as f:
        lines = f.read().splitlines()[:20]
    assert lines, "amt_dataset/nifty_amt_data/train.jsonl is empty"
    for line in lines:
        row = json.loads(line)
        fields = key_value_to_fields(row["messages"][1]["content"])
        rendered = render_entry_prompt(fields)
        assert "SESSION:" in rendered
        for k, v in fields.items():
            if k in _CATEGORIZED:
                if k == "cvd_slope":
                    assert "CVD" in rendered.upper(), "cvd_slope must drive the order-flow narrative"
                continue
            if isinstance(v, (int, float)):
                assert _rendered_contains(rendered, v), (
                    f"field {k}={v!r} lost in render: {rendered}"
                )
