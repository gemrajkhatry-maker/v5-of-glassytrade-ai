"""Tests for scripts/dataset_render.py — nifty_amt_data -> live prompt format."""

import json

from app.domain.fabio_ai.services.prompt_builder import render_entry_prompt
from scripts.dataset_render import (
    DATASET_DIR,
    OUTPUT_DIR,
    key_value_to_fields,
    render_row,
    render_split,
)


def _first_row():
    with open(DATASET_DIR / "train.jsonl") as f:
        return json.loads(f.readline())


def test_render_matches_live_prompt_shape():
    row = _first_row()
    fields = key_value_to_fields(row["messages"][1]["content"])
    rendered = render_entry_prompt(fields)
    assert "SESSION:" in rendered  # live header
    assert "POC" in rendered.upper()
    assert "state" not in rendered.lower() or "MARKET STATE" in rendered.upper()
    assert '"direction"' in row["messages"][2]["content"]


def test_first_row_user_content_is_live_prose():
    row = _first_row()
    out = render_row(row)
    user_content = out["messages"][1]["content"]
    assert "SESSION:" in user_content
    assert "MARKET STATE" in user_content


def test_assistant_contract_is_direction_confidence_rationale_only():
    row = _first_row()
    out = render_row(row)
    assistant = json.loads(out["messages"][2]["content"])
    assert set(assistant.keys()) == {"direction", "confidence", "rationale"}
    assert "setup" not in assistant


def test_assistant_preserves_original_direction_and_confidence():
    row = _first_row()
    original = json.loads(row["messages"][2]["content"])
    out = render_row(row)
    assistant = json.loads(out["messages"][2]["content"])
    assert assistant["direction"] == original["direction"]
    assert assistant["confidence"] == original["confidence"]


def test_render_split_writes_output_file():
    dst = render_split("train")
    assert dst.exists()
    assert dst.stat().st_size > 0
    assert OUTPUT_DIR.exists()
