"""FULL_SYSTEM §7 — LLM training/live format-parity guard.

Guards against the live inference prompt drifting away from the vocabulary the
model was fine-tuned on (amt_dataset/nifty_amt_data_livefmt).

Strategy:
  1. Build a representative AuctionState-derived market-data dict.
  2. Render the live prompt via quant.inference.prompt_builder.build_entry_prompt.
  3. Assert the canonical section markers appear in the live prompt.
  4. Read 1-2 samples from nifty_amt_data_livefmt/train.jsonl and assert the
     SAME section vocabulary appears in the training user messages.

Assertions are substring-based on section labels, so minor wording changes in
the prose do not break the guard. If the livefmt dataset is absent or not
parseable, the dataset half is skipped and the prompt-structure half still runs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant.inference.prompt_builder import build_entry_prompt

_SECTION_MARKERS = (
    "SESSION:",
    "MARKET STATE:",
    "ORDER FLOW & AGGRESSION",
)

_LIVEFMT_DIR = Path("amt_dataset/nifty_amt_data_livefmt")
_TRAIN_FILE = _LIVEFMT_DIR / "train.jsonl"

# Number of sample lines read from the livefmt training file.
_N_SAMPLES = 2


def _auction_state_dict() -> dict:
    """Representative AuctionState-derived market-data dict (live vocabulary)."""
    return {
        "session_name": "NSE_PRIMARY",
        "market_state": "BALANCED",
        "poc": 24550.0,
        "vah": 24600.0,
        "val": 24500.0,
        "ltp": 24575.0,
        "cvd_slope": 5.0,
        "aggression": 1.2,
        "profile_shape": "D",
        "is_second_drive": False,
        "session_vwap": 24560.0,
    }


def _render_live_prompt() -> str:
    return build_entry_prompt(_auction_state_dict())


class TestLivePromptStructure:

    def test_live_prompt_has_canonical_section_markers(self):
        prompt = _render_live_prompt()
        for marker in _SECTION_MARKERS:
            assert marker in prompt, f"live prompt missing marker {marker!r}"

    def test_live_prompt_starts_with_session(self):
        prompt = _render_live_prompt()
        assert prompt.lstrip().startswith("SESSION:")


def _read_livefmt_samples() -> list[str]:
    """Return user-message contents from the first N livefmt train samples."""
    if not _TRAIN_FILE.exists():
        pytest.skip(f"livefmt dataset absent: {_TRAIN_FILE}")
    contents: list[str] = []
    with open(_TRAIN_FILE, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= _N_SAMPLES:
                break
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                pytest.skip(f"livefmt train line {i} is not valid JSON")
            user_msg = next(
                (m for m in obj.get("messages", []) if m.get("role") == "user"),
                None,
            )
            if user_msg is None or not user_msg.get("content"):
                pytest.skip(f"livefmt train line {i} has no user message")
            contents.append(user_msg["content"])
    if not contents:
        pytest.skip(f"livefmt train file empty or unreadable: {_TRAIN_FILE}")
    return contents


class TestTrainingLivefmtParity:

    def test_training_samples_use_same_section_vocabulary(self):
        samples = _read_livefmt_samples()
        for marker in _SECTION_MARKERS:
            assert any(
                marker in sample for sample in samples
            ), f"no livefmt sample contains marker {marker!r}"

    def test_live_prompt_vocabulary_matches_training_samples(self):
        prompt = _render_live_prompt()
        samples = _read_livefmt_samples()
        live_markers = {m for m in _SECTION_MARKERS if m in prompt}
        assert live_markers, "live prompt missing every canonical marker"
        for marker in live_markers:
            assert any(
                marker in sample for sample in samples
            ), f"live marker {marker!r} absent from every livefmt sample"
