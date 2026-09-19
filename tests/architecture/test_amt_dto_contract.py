"""Architecture test: the AMT DTO producer -> reader key contract.

Entry gates, exits, sizing, rotation and the advisor narrative read the AMT DTO
as a *plain dict*; ``amt_result_to_dto`` emits it. Nothing in the type system
links the two, so a producer-side rename or drop is invisible: every consumer
test builds its own dict and keeps passing while production loses the field.
That is exactly how ``driveNumber`` (read by the drive-exhaustion guard, never
emitted), ``marketState`` (emitted but unproducible for option engines) and the
coordinator's rotation DTO shipped broken while the suite stayed green.

This test closes the gap from the producer side. It discovers the DTO keys the
decision layer reads straight from the source — so a new read is covered with
no registration — runs the real producer, and fails when a read key is absent.
There is deliberately no allowlist: the legacy fallbacks that once needed one
(``acceptance``, ``rejection``, ``legLvn``, ``data_quality``, ``bid``/``ask``,
``time``) have been removed, so any absent key is a real contract gap.

Reader convention this relies on: a consumer names the AMT DTO ``amt_dto`` (or
``dto``) or holds it in a ``*_amt_dto`` attribute. A consumer that binds it to
some other name must add that name to ``_DTO_NAMES``/``_DTO_ATTRS``, and a
locally-scoped ``dto`` that is *not* the AMT DTO would have to be renamed —
today ``quant/`` has exactly one ``dto`` binding and it is the AMT DTO.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest

from quant.amt.analyzer import AMTAnalyzer
from quant.amt.dto import amt_result_to_dto
from quant.contracts.value_objects import OHLC
from quant.runtime import _OPTION_SCALE_KEYS
from quant.contracts.value_objects import AMTResult, FootprintCandle
from quant.contracts.enums import MarketState

REPO_ROOT = Path(__file__).resolve().parents[2]
QUANT_ROOT = REPO_ROOT / "quant"

# Names that hold the AMT DTO on the reader side.
_DTO_NAMES = frozenset({"amt_dto", "dto"})
_DTO_ATTRS = frozenset({"_last_amt_dto", "_option_amt_dto", "_underlying_amt_dto"})

# The runtime's typed getters (``_db`` bool, ``_df`` float, ``_ds`` str, ...).
_DTO_ACCESSORS = frozenset({"_db", "_df", "_ds", "_di", "_dv"})

OPTION_SYMBOL = "NIFTY 25000 CE"
_ACTIVE_VOLUME = 4000.0
_CANDLE_COUNT = 40

# Canary: each of these modules must keep contributing these reads, so a renamed
# DTO variable or a new accessor helper fails loudly instead of leaving the core
# assertion below trivially satisfied.
_KNOWN_CONSUMERS = {
    "quant/decision/context_builder.py": {"marketState", "cvdSlope", "squeezeDirection"},
    "quant/engine/decision_loop.py": {"marketState", "balanceRatio", "legLvn"},
    "quant/execution/exit_checks.py": {"cvdSlope"},
    "quant/multi_engine.py": {"marketState"},
    "quant/position_manager.py": {"marketState", "legProfile"},
}


class _DtoReadVisitor(ast.NodeVisitor):
    """Collect the literal keys read from an AMT-DTO variable/attribute.

    Recognises the three read dialects the decision layer uses: the runtime's
    typed getters (``self._db(amt_dto, "key")``), ``amt_dto.get("key")`` and
    ``amt_dto["key"]`` — load context only, so writes are never counted.
    """

    def __init__(self) -> None:
        self.keys: dict[str, set[str]] = defaultdict(set)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, (ast.Name, ast.Attribute)):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            if name in _DTO_ACCESSORS and len(node.args) == 2:
                holder = self._holder(node.args[0])
                if holder:
                    self._record(holder, node.args[1])
            if name == "get" and isinstance(node.func, ast.Attribute) and node.args:
                holder = self._holder(node.func.value)
                if holder:
                    self._record(holder, node.args[0])
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if isinstance(node.ctx, ast.Load):
            holder = self._holder(node.value)
            if holder:
                self._record(holder, node.slice)
        self.generic_visit(node)

    @staticmethod
    def _holder(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name) and node.id in _DTO_NAMES:
            return node.id
        if isinstance(node, ast.Attribute) and node.attr in _DTO_ATTRS:
            return node.attr
        return None

    def _record(self, holder: str, key: ast.expr) -> None:
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            self.keys[holder].add(key.value)


def _candle(index: int) -> OHLC:
    """5-minute IST candle at 09:15 + index, steady volume."""
    total = 15 + index * 5
    return OHLC(
        time=f"2026-01-01T{total // 60:02d}:{total % 60:02d}:00Z",
        open=150.0,
        high=150.3,
        low=149.7,
        close=150.0,
        volume=_ACTIVE_VOLUME,
        vwap=150.0,
        taker_buy_volume=_ACTIVE_VOLUME / 2,
        delta=0.0,
    )


@lru_cache(maxsize=1)
def _produced_keys() -> frozenset[str]:
    """Keys the real producer emits for an option-premium analysis."""
    result = AMTAnalyzer().analyze([_candle(i) for i in range(_CANDLE_COUNT)], symbol=OPTION_SYMBOL)
    return frozenset(amt_result_to_dto(result))


@lru_cache(maxsize=1)
def _read_keys() -> dict[str, frozenset[str]]:
    """AMT-DTO keys read under ``quant/``, mapped to the files that read them."""
    reads: dict[str, set[str]] = defaultdict(set)
    for path in sorted(QUANT_ROOT.rglob("*.py")):
        visitor = _DtoReadVisitor()
        visitor.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for keys in visitor.keys.values():
            for key in keys:
                reads[key].add(str(path.relative_to(REPO_ROOT)))
    return {key: frozenset(files) for key, files in reads.items()}


def test_every_dto_key_the_decision_layer_reads_is_emitted():
    """No reader may look up a key the producer omits."""
    produced = _produced_keys()

    missing = {
        key: sorted(files)
        for key, files in _read_keys().items()
        if key not in produced
    }

    assert not missing, (
        "AMT DTO key(s) read by the decision layer that amt_result_to_dto never emits — "
        f"the field is silently absent in production: {missing}. Emit it in quant/amt/dto.py "
        "or stop reading it."
    )


def test_footprint_presence_does_not_upgrade_provenance_to_tick_exact():
    result = AMTResult(
        market_state=MarketState.BALANCED,
        poc=0.0,
        value_area_high=0.0,
        value_area_low=0.0,
        cvd_source="underlying",
        footprints={"bar": FootprintCandle(time="2026-01-01T00:00:00Z")},
    )

    assert amt_result_to_dto(result)["dataQuality"] == "CANDLE_DISTRIBUTED"


def test_unknown_provenance_remains_unavailable_for_cvd_sources():
    for source in ("underlying", "option"):
        base = AMTResult(
            market_state=MarketState.BALANCED,
            poc=0.0,
            value_area_high=0.0,
            value_area_low=0.0,
            cvd_source=source,
        )
        result = SimpleNamespace(**vars(base), data_quality="future-unknown-quality")

        assert amt_result_to_dto(result)["dataQuality"] == "UNAVAILABLE"


def test_dto_preserves_explicit_provenance_for_each_required_family():
    result = AMTResult(
        market_state=MarketState.BALANCED,
        poc=0.0,
        value_area_high=0.0,
        value_area_low=0.0,
        evidence_provenance={
            "footprint_imbalance": "TICK_EXACT",
            "cvd_delta": "CANDLE_DISTRIBUTED",
            "ofi_depth": "TICK_EXACT",
            "absorption": "UNKNOWN",
            "stacked_imbalance": "TICK_EXACT",
        },
    )

    assert amt_result_to_dto(result)["evidenceProvenance"] == {
        "footprint_imbalance": "TICK_EXACT",
        "cvd_delta": "CANDLE_DISTRIBUTED",
        "ofi_depth": "TICK_EXACT",
        "absorption": "UNAVAILABLE",
        "stacked_imbalance": "TICK_EXACT",
    }


def test_option_scale_merge_keys_are_real_dto_keys():
    """runtime blanks every ``_OPTION_SCALE_KEYS`` entry from ``_EMPTY_AMT_DTO``.

    A key in that tuple that the producer does not emit injects a phantom
    ``None`` into the WS ``amt`` payload; a price-scaled key missing from it
    would let futures-scale prices ride onto the option chart.
    """
    phantom = sorted(set(_OPTION_SCALE_KEYS) - _produced_keys())

    assert not phantom, f"quant/runtime._OPTION_SCALE_KEYS names keys amt_result_to_dto never emits: {phantom}"


@pytest.mark.parametrize(("module", "required_keys"), sorted(_KNOWN_CONSUMERS.items()))
def test_scan_still_sees_the_known_consumers(module: str, required_keys: set[str]):
    """Canary: the scanner must keep recognising the readers it guards."""
    seen = {key for key, files in _read_keys().items() if module in files}

    assert required_keys <= seen, (
        f"{module} no longer shows up as reading {sorted(required_keys - seen)} — "
        "the DTO read scanner (or the module's DTO variable name) drifted, so the "
        "emitted-key contract is no longer actually enforced for it"
    )
