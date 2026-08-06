#!/usr/bin/env python3
"""Convert amt_dataset/nifty_amt_data key:value rows to the live prompt format.

Reads amt_dataset/nifty_amt_data/{train,val,test}.jsonl, parses each user
`key: value` block into the live market_data_ai vocabulary (key_value_to_fields),
renders the live narrative prose with render_entry_prompt, restricts the
assistant target to {direction, confidence, rationale} (dropping the dataset's
`setup` key), and writes amt_dataset/nifty_amt_data_livefmt/{train,val,test}.jsonl.

The adapter was trained on this key:value dataset while the live app sends
narrative prose with a 3-key JSON contract — this renderer bridges the gap so a
retrain sees the exact live prompt shape.

Usage (from backend/):
    PYTHONPATH=..:. python scripts/dataset_render.py
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATASET_DIR = PROJECT_ROOT / "amt_dataset" / "nifty_amt_data"
OUTPUT_DIR = PROJECT_ROOT / "amt_dataset" / "nifty_amt_data_livefmt"
SPLITS = ("train", "val", "test")

_SESSION_NAME = "NSE_PRIMARY"
_CATEGORICAL_POC = ("above", "below", "middle")

from app.domain.fabio_ai.services.prompt_builder import render_entry_prompt


def _to_float(value):
    try:
        return float(str(value).replace("+", ""))
    except (TypeError, ValueError):
        return None


def key_value_to_fields(content: str) -> dict:
    """Parse a dataset user `key: value` block into render_entry_prompt fields.

    Maps onto the live market_data_ai vocabulary: session->session_name,
    state->market_state, price->ltp, rejection->rejection_at_high,
    second_drive->is_second_drive, categorical poc->poc_tag, and keeps the
    dataset-only keys (phase, absorptionSide, ib_range, note, entry, ...) as-is
    for render_entry_prompt's dataset context block.
    """
    raw = {}
    for line in str(content).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        raw[key.strip()] = value.strip()

    fields = {"session_name": _SESSION_NAME}
    for key, value in raw.items():
        if key == "session":
            fields["session_name"] = _SESSION_NAME
        elif key == "state":
            fields["market_state"] = value
        elif key == "poc":
            if value in _CATEGORICAL_POC:
                fields["poc_tag"] = value
            else:
                num = _to_float(value)
                if num is not None:
                    fields["poc"] = num
        elif key == "price":
            num = _to_float(value)
            if num is not None:
                fields["ltp"] = num
        elif key == "absorption":
            fields["absorptionSide"] = "VAH" if "VAH" in value.upper() else "VAL"
        elif key == "rejection":
            # "rejection: yes" only co-occurs with poc: above (failed auction at VAH).
            if value.lower() == "yes":
                fields["rejection_at_high"] = True
        elif key == "second_drive":
            if value.lower() == "confirmed":
                fields["is_second_drive"] = True
        elif key == "cvd_slope":
            num = _to_float(value)
            if num is not None:
                fields["cvd_slope"] = num
        elif key == "delta":
            num = _to_float(value)
            if num is not None:
                fields["delta"] = num
        elif key in ("time", "symbol", "phase", "ib_range", "profile_shape", "note"):
            fields[key] = value
        else:
            num = _to_float(value)
            fields[key] = num if num is not None else value
    return fields


def _assistant_content(assistant_raw: str) -> dict:
    """Restrict the assistant target to the live {direction, confidence, rationale}."""
    data = json.loads(assistant_raw)
    return {
        "direction": data.get("direction", "FLAT"),
        "confidence": data.get("confidence", "Medium"),
        "rationale": data.get("rationale", "") or "",
    }


def render_row(row: dict) -> dict:
    """Render one dataset row to the live prompt shape.

    The system message mirrors what live inference sends
    (generative_ai_service._DEFAULT_INSTRUCTION + the JSON contract reminder),
    so a retrain teaches the model the exact instruction it will see at runtime.
    """
    from app.domain.fabio_ai.services.generative_ai_service import _DEFAULT_INSTRUCTION
    from app.domain.fabio_ai.services.llm_contract import ENTRY_JSON_RUNTIME_REMINDER

    messages = row["messages"]
    fields = key_value_to_fields(messages[1]["content"])
    return {
        "messages": [
            {"role": "system", "content": _DEFAULT_INSTRUCTION + "\n" + ENTRY_JSON_RUNTIME_REMINDER},
            {"role": "user", "content": render_entry_prompt(fields)},
            {
                "role": "assistant",
                "content": json.dumps(
                    _assistant_content(messages[2]["content"]), ensure_ascii=False
                ),
            },
        ]
    }


def render_split(split: str) -> Path:
    """Write one split to nifty_amt_data_livefmt. Returns the output path."""
    src = DATASET_DIR / f"{split}.jsonl"
    dst = OUTPUT_DIR / f"{split}.jsonl"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(src) as f_in, open(dst, "w") as f_out:
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            f_out.write(json.dumps(render_row(json.loads(line)), ensure_ascii=False) + "\n")
    return dst


def main() -> None:
    for split in SPLITS:
        dst = render_split(split)
        count = sum(1 for _ in open(dst))
        print(f"{split}: wrote {dst} ({count} rows)")


if __name__ == "__main__":
    sys.exit(main())
