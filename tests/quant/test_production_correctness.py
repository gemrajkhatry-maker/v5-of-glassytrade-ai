"""Production-correctness contracts the previous suites encoded as passing bugs.

Uses real contract strings and IST timestamps. No broker mocks, no synthetic
``t300`` clocks. A green run here means the MIDCPNIFTY / SL / Triple-A class
of silent failures cannot recur in the shared functions.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from quant.amt.session.context import get_session_info, is_expiry_day
from quant.amt.triple_a import ACCUMULATING, AGGRESSION, ABSORBING, TripleAMachine, WAITING
from quant.bars import Bar
from quant.contracts.enums import MarketState
from quant.contracts.instrument_registry import (
    DEFAULT_REGISTRY,
    is_futures_contract,
    is_option_contract,
)
from quant.decision.context import DecisionContext
from quant.decision.decision_service import DecisionService
from quant.decision.gates_edge import gate_triple_a_edge
from quant.decision.gates_rr import gate_risk_reward
from quant.decision.result import GateResult
from quant.decision.signal_builder import SignalBuilder
from quant.decision.stops import structural_stop
from quant.session_gates import parse_contract_expiry, session_force_exit

IST = ZoneInfo("Asia/Kolkata")


def _bar(close: float, **kw) -> Bar:
    return Bar(
        time=kw.get("time", "2026-08-19T10:30:00+05:30"),
        open=kw.get("open", close),
        high=kw.get("high", close),
        low=kw.get("low", close),
        close=close,
        volume=kw.get("volume", 100.0),
    )


def _ctx(**kw) -> DecisionContext:
    close = kw.pop("close", 100.0)
    fields = dict(
        state=None,
        bar=_bar(close),
        symbol=kw.pop("symbol", "NIFTY 27 AUG 25500 CALL"),
        time_str="2026-08-19T10:30:00+05:30",
        agent_direction=kw.pop("agent_direction", "LONG"),
        agent_probability=0.7,
        market_state=kw.pop("market_state", MarketState.IMBALANCED),
        poc=kw.pop("poc", 100.0),
        vah=kw.pop("vah", 102.0),
        val=kw.pop("val", 98.0),
        tick_size=kw.pop("tick_size", 0.05),
        cvd_slope=kw.pop("cvd_slope", 0.0),
        absorption_side=kw.pop("absorption_side", ""),
        obi=kw.pop("obi", 0.0),
        triple_a_phase=kw.pop("triple_a_phase", WAITING),
        triple_a_signal=kw.pop("triple_a_signal", ""),
    )
    fields.update(kw)
    return DecisionContext(**fields)


# ---- instrument identity -------------------------------------------------


def test_nifty_bank_is_banknifty_not_nifty():
    spec = DEFAULT_REGISTRY.resolve("NIFTY BANK 27 AUG 55000 CALL")
    assert spec.root == "BANKNIFTY"
    assert spec.lot_size == 30
    assert spec.dhan_exchange == "NFO"


def test_crudeoil_does_not_resolve_as_mini():
    full = DEFAULT_REGISTRY.resolve("CRUDEOIL 19 MAR 6000 CALL")
    mini = DEFAULT_REGISTRY.resolve("CRUDEOILM 19 MAR 6000 CALL")
    assert full.root == "CRUDEOIL" and full.lot_size == 100
    assert mini.root == "CRUDEOILM" and mini.lot_size == 10


def test_gold_aliases_do_not_collapse():
    assert DEFAULT_REGISTRY.resolve("GOLD 28 AUG 72000 CALL").root == "GOLD"
    assert DEFAULT_REGISTRY.resolve("GOLDM 28 AUG 72000 CALL").root == "GOLDM"
    assert DEFAULT_REGISTRY.resolve("GOLDPETAL 28 AUG CALL").root == "GOLDPETAL"


def test_compact_and_hyphenated_options_are_options():
    assert is_option_contract("NIFTY23FEB18000CE")
    assert is_option_contract("NIFTY-27FEB-25500-CE")
    assert is_option_contract("CRUDEOIL 19 MAR 6000 CALL")
    assert not is_option_contract("CRUDEOIL AUG FUT")
    assert not is_option_contract("NIFTY")


def test_futures_formats_the_broker_actually_sends():
    assert is_futures_contract("CRUDEOIL AUG FUT")
    assert is_futures_contract("CRUDEOIL-I")
    assert is_futures_contract("CRUDEOIL-19MAR2026")
    assert is_futures_contract("NIFTY25AUGFUT")
    assert not is_futures_contract("CRUDEOIL 19 MAR 6000 CALL")
    assert not is_futures_contract("NIFTY23FEB18000CE")


def test_sensex_is_bfo_not_mcx():
    spec = DEFAULT_REGISTRY.resolve("SENSEX 17 AUG 82000 CALL")
    assert spec.exchange == "BSE"
    assert spec.dhan_exchange == "BFO"
    assert spec.session_profile == "NSE"


# ---- session / expiry ----------------------------------------------------


def test_mcx_afternoon_is_open_when_nse_is_closed():
    ts = "2026-08-19T16:45:00+05:30"
    nse = get_session_info(ts, market="NSE")
    mcx = get_session_info(ts, market="MCX")
    assert nse.allow_entry is False
    assert mcx.allow_entry is True
    assert mcx.force_exit is False


def test_opening_noise_does_not_flatten_open_positions():
    """09:20 IST is no-entry, not force-exit. Flattening here dumps into the open."""
    ts = "2026-08-19T09:20:00+05:30"
    info = get_session_info(ts, market="NSE")
    assert info.allow_entry is False
    assert info.force_exit is False
    assert session_force_exit(ts, market="NSE") is False


def test_close_protection_does_flatten():
    ts = "2026-08-19T15:20:00+05:30"
    assert session_force_exit(ts, market="NSE") is True


def test_naive_iso_is_ist_not_utc():
    naive = datetime(2026, 8, 19, 10, 30, 0)  # wall-clock IST with no tz
    info = get_session_info(naive, market="NSE")
    assert info.session == "NSE_PRIMARY"
    assert info.allow_entry is True


def test_expiry_is_the_contract_date_not_every_tuesday():
    assert parse_contract_expiry("CRUDEOIL 28 AUG 7450 CALL") == date(2026, 8, 28)
    compact = parse_contract_expiry("NIFTY23FEB18000CE")
    assert compact is not None and compact.month == 2 and compact.day == 23
    hyphen = parse_contract_expiry("NIFTY-27FEB-25500-CE")
    assert hyphen is not None and hyphen.month == 2 and hyphen.day == 27
    # BANKNIFTY monthly: a random Tuesday in the month is not expiry.
    assert is_expiry_day(date(2026, 2, 10), symbol="BANKNIFTY") is False
    assert is_expiry_day(date(2026, 2, 24), symbol="BANKNIFTY") is True  # last Tuesday Feb 2026


# ---- SL semantics --------------------------------------------------------


def test_long_stop_is_inside_the_level_not_outside():
    # Support at 102, entry 110, tick 0.05 → inside = 102.10, outside = 101.90
    sl = structural_stop("LONG", entry=110.0, anchor=102.0, tick=0.05)
    assert sl == pytest.approx(102.10)
    assert sl > 102.0
    assert sl < 110.0


def test_short_stop_is_inside_the_level_not_outside():
    sl = structural_stop("SHORT", entry=90.0, anchor=98.0, tick=0.05)
    assert sl == pytest.approx(97.90)
    assert sl < 98.0
    assert sl > 90.0


def test_signal_builder_and_gate4_share_the_same_stop():
    ctx = _ctx(close=110.0, poc=100.0, vah=102.0, val=98.0, tick_size=0.05)
    sig = SignalBuilder().build(ctx, [GateResult(i, True) for i in range(1, 5)])
    g4 = gate_risk_reward(ctx)
    assert sig is not None
    assert "102.10" in (g4.extra or g4.reason)
    assert sig.sl == pytest.approx(102.10)


def test_imbalanced_alone_is_not_an_entry():
    ctx = _ctx(
        agent_direction="LONG",
        market_state=MarketState.IMBALANCED,
        close=110.0,
        triple_a_phase=WAITING,
        cvd_slope=1.0,
    )
    assert gate_triple_a_edge(ctx).passed is False
    d = DecisionService().evaluate(ctx)
    assert d.approved is False or d.reason == "VA_FADE"


def test_triple_a_aggression_is_required_for_playbook_a():
    ctx = _ctx(
        agent_direction="LONG",
        market_state=MarketState.BALANCED,
        close=110.0,
        triple_a_phase=AGGRESSION,
        triple_a_signal="LONG",
        cvd_slope=1.0,
    )
    r = gate_triple_a_edge(ctx)
    assert r.passed is True
    assert "AGGRESSION" in r.reason or "Triple-A" in r.reason


def test_absorption_without_accumulation_is_not_entry():
    ctx = _ctx(
        agent_direction="LONG",
        market_state=MarketState.BALANCED,
        close=100.5,
        absorption_side="SELL_ABSORBED",
        obi=0.20,
        triple_a_phase=ABSORBING,
        triple_a_signal="LONG",
        cvd_slope=0.1,
    )
    assert gate_triple_a_edge(ctx).passed is False


def test_triple_a_machine_requires_cluster_close():
    m = TripleAMachine()
    s = m.update(close=100.0, high=100.2, low=99.8, absorption_side="", vwap=99.5, cvd_slope=0.1)
    assert s.phase == WAITING
    # Detector pulse = displacement already confirmed → AGGRESSION this bar.
    s = m.update(close=100.5, high=100.6, low=100.2, absorption_side="SELL_ABSORBED", vwap=99.5, cvd_slope=0.4)
    assert s.phase == AGGRESSION
    assert s.signal == "LONG"
    # Next bar is not sticky.
    s = m.update(close=100.6, high=100.7, low=100.3, absorption_side="", vwap=99.5, cvd_slope=0.4)
    assert s.phase == WAITING


def test_float_epoch_normalizes_to_ist_date_not_prefix():
    from quant.state import _epoch_to_iso, session_date_key

    iso = _epoch_to_iso("1786095001.0")
    assert iso[4] == "-" and iso[7] == "-"
    assert session_date_key("1786095001.0") == session_date_key("1786095001")
    assert session_date_key("t300") == ""
    assert session_date_key("t0") == session_date_key("t309")


def test_nifty_bank_and_crudeoil_i_route_to_derivative_segments():
    from brokers.broker.dhan.application.exchange_resolver import DhanExchangeResolver
    from brokers.broker.dhan.domain import ExchangeSegment
    from brokers.broker.types import Exchange

    bank = DhanExchangeResolver.resolve("NIFTY BANK 27 AUG 55000 CALL")
    assert bank.exchange == Exchange.NFO
    assert bank.segment == ExchangeSegment.NSE_FNO
    assert DhanExchangeResolver._extract_underlying(
        "NIFTY BANK 27 AUG 55000 CALL"
    ) == "BANKNIFTY"

    fut = DhanExchangeResolver.resolve("CRUDEOIL-I")
    assert fut.exchange == Exchange.MCX
    assert fut.symbol_type == "future"

    # YAML session label NSE must not send index options to NSE_EQ.
    hinted = DhanExchangeResolver.resolve("NIFTY 27 AUG 25500 CALL", Exchange.NSE)
    assert hinted.exchange == Exchange.NFO
    assert hinted.segment == ExchangeSegment.NSE_FNO


def test_drive_number_alone_is_not_second_drive_evidence():
    from quant.decision.context_builder import DecisionContextBuilder

    class _Risk:
        equity = 1_000_000.0
        risk_per_trade_pct = 0.01
        halted = False
        consecutive_losses = 0

    builder = DecisionContextBuilder()
    ctx = builder.build(
        bar=_bar(100.5),
        symbol="NIFTY",
        market="NSE",
        contract_expiry=None,
        tick_size=0.05,
        bar_index=20,
        warm_bars=0,
        cooldown_remaining_sec=0.0,
        risk_state=_Risk(),
        amt_dto={
            "marketState": "IMBALANCED",
            "driveNumber": 2,
            "cvdSlope": 1.5,
        },
    )
    ev = ctx.setup_evidence
    assert ev is None or ev.setup_type != "SECOND_DRIVE" or not ev.is_complete()
