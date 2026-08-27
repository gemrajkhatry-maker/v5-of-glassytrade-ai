"""Tests for LLM Decision & Narrative Bridge and Dataset Integrity."""

import json
import pytest
from quant.decision.context import DecisionContext
from quant.bars import Bar
from quant.contracts.enums import MarketState
from quant.llm.bridge import context_to_prompt, extract_llm_json
from quant.llm.dataset_generator import generate_scenario, generate_dataset


def test_context_to_prompt_schema():
    bar = Bar(time="2026-08-25T10:15:00+05:30", open=24200.0, high=24220.0, low=24195.0, close=24210.0, volume=2500.0, buy_volume=1600.0, sell_volume=900.0, delta=700.0, vwap=24205.0)
    ctx = DecisionContext(
        symbol="NIFTY",
        bar=bar,
        market_state=MarketState.BALANCED,
        poc=24205.0,
        vah=24230.0,
        val=24185.0,
        cvd_slope=5.5,
        absorption_side="BUY",
        session_phase="PRIMARY",
        profile_shape="b",
        bid=24209.95,
        ask=24210.05,
    )
    sys_prompt, user_text = context_to_prompt(ctx)
    assert "Auction Market Theory" in sys_prompt
    assert "NIFTY" in user_text
    assert '"market_state": "BALANCED"' in user_text
    assert '"absorption_side": "BUY"' in user_text
    assert '"cvd_slope": 5.5' in user_text


def test_extract_llm_json_variants():
    # 1. Clean JSON with prime
    prime = '{\n  "rationale": "'
    raw1 = 'Absorption at VAL with positive delta.", "action": "ENTER_LONG", "direction": "LONG", "confidence": "High", "setup": "TRIPLE_A"}'
    res1 = extract_llm_json(raw1, prime=prime)
    assert res1.get("direction") == "LONG"
    assert res1.get("action") == "ENTER_LONG"
    assert "Absorption at VAL" in res1.get("rationale", "")

    # 2. Already fully closed JSON without prime needed
    raw2 = '{"action": "ENTER_SHORT", "direction": "SHORT", "setup": "TRIPLE_A", "confidence": "High", "rationale": "Selling at VAH."}'
    res2 = extract_llm_json(raw2, prime="")
    assert res2.get("direction") == "SHORT"
    assert res2.get("action") == "ENTER_SHORT"

    # 3. Trailing comma repair
    raw3 = '{"action": "FLAT", "direction": "FLAT", "setup": "NO_EDGE", "rationale": "Midday chop",}'
    res3 = extract_llm_json(raw3, prime="")
    assert res3.get("direction") == "FLAT"


def test_dataset_generator_balance():
    data = generate_dataset(300)
    assert len(data) == 300
    counts = {"LONG": 0, "SHORT": 0, "FLAT": 0}
    for item in data:
        resp = json.loads(item["messages"][2]["content"])
        d = resp.get("direction")
        counts[d] += 1

    # Exact 1:1:1 balance
    assert counts["LONG"] == 100
    assert counts["SHORT"] == 100
    assert counts["FLAT"] == 100


def test_context_to_prompt_recent_decisions():
    bar = Bar(time="2026-08-25T10:15:00+05:30", open=24200.0, high=24220.0, low=24195.0, close=24210.0, volume=2500.0, buy_volume=1600.0, sell_volume=900.0, delta=700.0, vwap=24205.0)
    recent = (
        {"time": "10:13", "action": "FLAT", "direction": "FLAT", "setup": "NO_EDGE", "rationale": "Chop at POC"},
        {"time": "10:14", "action": "ENTER_LONG", "direction": "LONG", "setup": "TRIPLE_A", "rationale": "Absorption at VAL"},
    )
    ctx = DecisionContext(
        symbol="NIFTY",
        bar=bar,
        recent_decisions=recent,
    )
    _, user_text = context_to_prompt(ctx)
    assert '"recent_decisions"' in user_text
    assert '"Absorption at VAL"' in user_text
    assert '"Chop at POC"' in user_text
