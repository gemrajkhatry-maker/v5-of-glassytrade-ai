"""Parity: inference/RL cluster moved modules vs legacy shims.

Compares legacy `app.domain.fabio_ai.*` shims against the ported
`quant.inference.*` / `quant.amt.*` modules on identical fixed inputs.

Skipped by design (note in track report):
  - generative_ai_service.analyze_market: LLM-adapter dependent (exercised by
    the ported unit tests with a mock adapter).
  - valentini_env / trainer: need optional `gymnasium` / `stable_baselines3`
    (absent in this env), so their modules cannot be imported for parity.
"""

from __future__ import annotations

import pytest

from quant.contracts.value_objects import OHLC, AMTResult, ModelWeights

# prompt_builder
from quant.inference.prompt_builder import (
    build_entry_prompt as new_build_entry_prompt,
    build_overseer_prompt as new_build_overseer_prompt,
    build_advisory_prompt as new_build_advisory_prompt,
    parse_entry_response as new_parse_entry_response,
    parse_overseer_response as new_parse_overseer_response,
)
from app.domain.fabio_ai.services.prompt_builder import (
    build_entry_prompt as legacy_build_entry_prompt,
    build_overseer_prompt as legacy_build_overseer_prompt,
    build_advisory_prompt as legacy_build_advisory_prompt,
    parse_entry_response as legacy_parse_entry_response,
    parse_overseer_response as legacy_parse_overseer_response,
)

# prediction engine
from quant.inference.prediction import PredictionEngine as NewPredictionEngine
from app.domain.fabio_ai.services.prediction_engine import (
    PredictionEngine as LegacyPredictionEngine,
)

# reward shaper
from quant.inference.rl.reward_shaper import (
    ValentiniRewardShaper as NewRewardShaper,
    TradeResult,
)
from app.domain.fabio_ai.rl.reward_shaper import (
    ValentiniRewardShaper as LegacyRewardShaper,
)

# data loader
from quant.inference.rl.data_loader import split_data as new_split_data
from app.domain.fabio_ai.rl.data_loader import split_data as legacy_split_data

from tests.quant.parity import assert_parity


# ---------------------------------------------------------------------------
# Fixed inputs
# ---------------------------------------------------------------------------

ENTRY_FIXTURES = [
    {"ltp": 100, "vah": 105, "val": 95, "poc": 100, "delta": 50},
    {"ltp": 15300.0, "vah": 15200.0, "val": 15000.0, "poc": 15100.0,
     "market_state": "Imbalanced", "delta": -500},
    {"ltp": 0, "vah": 0, "val": 0, "poc": 0, "delta": 0},
    {"ltp": 24080.0, "session_vwap": 24000.0, "vwap_upper_2": 24080.0,
     "vwap_lower_2": 23920.0, "vah": 24100.0, "val": 23900.0, "poc": 24000.0},
    {"ltp": 100, "vah": 105, "val": 95, "poc": 100, "cvd_divergence": "BEARISH_DIV",
     "volume_bubbles": "BUY bubble at 100", "cvd_slope": 200},
]

PARSE_ENTRY_FIXTURES = [
    '{"direction":"LONG","rationale":"Balance at VAL with buyers stepping in","confidence":"High","market_state":"Balance"}',
    "Trigger: **Enter Long**",
    "The quick brown fox jumped over the lazy dog.",
    "",
    '```json\n{"direction":"SHORT","rationale":"Breakout failed","confidence":"Low"}\n```',
    "STATE: TREND\nTRADE: LONG",
]

POS_STATE = {
    "position_id": "P1", "side": "LONG", "entry_price": 100.0,
    "current_price": 105.0, "unrealized_pnl_pct": 0.05,
    "time_in_trade_secs": 30.0, "stop_loss": 95.0, "take_profit": 110.0,
}

PARSE_OVERSEER_FIXTURES = [
    '{"action": "TIGHTEN_SL", "new_sl_price": 102.5}',
    '{"action": "FULL_EXIT"}',
    "Close position now!",
    "I think the market looks fine",
    '{"action": "PARTIAL_EXIT", "reason": "taking half"}',
]


def _tick():
    return OHLC(
        time="2025-01-15T10:00:00+05:30",
        open=100, high=101, low=99, close=100,
        volume=500, vwap=100, delta=50,
    )


def _amt(**kwargs):
    base = dict(
        market_state="BALANCED", poc=100, value_area_high=105,
        value_area_low=95, aggression=0.6, cvd_slope=4.0,
        delta_normalized_option=0.3, lvns=(98,), hvns=(102,),
    )
    base.update(kwargs)
    return AMTResult(**base)


def _ohlc_series(count: int = 60) -> list[OHLC]:
    out = []
    price = 100.0
    for i in range(count):
        price += 0.1 if i % 2 else -0.05
        out.append(
            OHLC(
                time=f"2025-01-15T09:{i:02d}:00+00:00",
                open=price, high=price + 0.5, low=price - 0.5,
                close=price, volume=1000.0, vwap=price,
                taker_buy_volume=550.0, delta=5.0 if i % 2 else -5.0,
            )
        )
    return out


# ---------------------------------------------------------------------------
# prompt_builder parity
# ---------------------------------------------------------------------------


class TestPromptBuilderParity:
    def test_build_entry_prompt(self):
        for data in ENTRY_FIXTURES:
            assert_parity(legacy_build_entry_prompt, new_build_entry_prompt, data)
            assert_parity(
                legacy_build_entry_prompt, new_build_entry_prompt, data, True
            )

    def test_build_overseer_prompt(self):
        for amt in (_amt(), _amt(market_state="IMBALANCED", poc=90, value_area_high=95, value_area_low=85)):
            assert_parity(
                lambda: legacy_build_overseer_prompt(POS_STATE, _tick(), amt),
                lambda: new_build_overseer_prompt(POS_STATE, _tick(), amt),
            )

    def test_build_advisory_prompt(self):
        assert_parity(
            lambda: legacy_build_advisory_prompt("NIFTY", _tick(), _amt()),
            lambda: new_build_advisory_prompt("NIFTY", _tick(), _amt()),
        )

    def test_parse_entry_response(self):
        for text in PARSE_ENTRY_FIXTURES:
            assert_parity(
                lambda: legacy_parse_entry_response(text),
                lambda: new_parse_entry_response(text),
            )

    def test_parse_overseer_response(self):
        for text in PARSE_OVERSEER_FIXTURES:
            assert_parity(
                lambda: legacy_parse_overseer_response(text, POS_STATE),
                lambda: new_parse_overseer_response(text, POS_STATE),
            )


# ---------------------------------------------------------------------------
# prediction_engine parity
# ---------------------------------------------------------------------------


class TestPredictionEngineParity:
    def test_predict_identical_result_fields(self):
        data = _ohlc_series(60)
        weights = ModelWeights()
        legacy = LegacyPredictionEngine().predict(data, weights, 10)
        new = NewPredictionEngine().predict(data, weights, 10)
        assert_parity(lambda: legacy, lambda: new)

    def test_predict_insufficient_data(self):
        data = _ohlc_series(10)
        weights = ModelWeights()
        assert_parity(
            lambda: LegacyPredictionEngine().predict(data, weights, 5),
            lambda: NewPredictionEngine().predict(data, weights, 5),
        )


# ---------------------------------------------------------------------------
# reward_shaper parity
# ---------------------------------------------------------------------------


class TestRewardShaperParity:
    def test_compute_identical(self):
        results = [
            TradeResult(pnl=100, hit_target=True, moved_to_be=False, risk_pct=0.1,
                        bars_held=10, max_bars=50, failed_auction_hold=False,
                        fighting_flow=False),
            TradeResult(pnl=-200, hit_target=False, moved_to_be=False, risk_pct=1.0,
                        bars_held=5, max_bars=50, failed_auction_hold=True,
                        fighting_flow=True),
            TradeResult(pnl=0, hit_target=False, moved_to_be=True, risk_pct=0.2,
                        bars_held=30, max_bars=50, failed_auction_hold=False,
                        fighting_flow=False),
        ]
        for result in results:
            assert_parity(
                lambda: LegacyRewardShaper().compute(result),
                lambda: NewRewardShaper().compute(result),
            )


# ---------------------------------------------------------------------------
# data_loader parity
# ---------------------------------------------------------------------------


class TestDataLoaderParity:
    def test_split_data_counts_and_slices(self):
        data = [OHLC(time=f"t{i}", open=1, high=2, low=0, close=1, volume=10)
                for i in range(100)]
        legacy = legacy_split_data(data, 0.6, 0.2)
        new = new_split_data(data, 0.6, 0.2)
        assert legacy.total == new.total == 100
        assert len(legacy.train) == len(new.train) == 60
        assert len(legacy.validation) == len(new.validation) == 20
        assert len(legacy.test) == len(new.test) == 20
        assert [c.time for c in legacy.train] == [c.time for c in new.train]
        assert [c.time for c in legacy.test] == [c.time for c in new.test]
