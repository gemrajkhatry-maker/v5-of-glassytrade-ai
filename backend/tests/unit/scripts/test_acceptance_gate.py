"""Tests for scripts/acceptance_gate.py — §5.4 journal metrics + harness detection."""

import json

from scripts.acceptance_gate import (
    _num,
    compute_metrics,
    flag_harness_artifacts,
    is_underlying_symbol,
    parse_journals,
)


def _exit(
    pnl,
    symbol="NIFTY 21 AUG 24500 CALL",
    run_id="20260806T000000Z-aaaaaaaa",
    timestamp="2026-08-06T10:00:00+05:30",
    time_in_trade_s=900.0,
    exit_reason="TARGET",
):
    return {
        "event_type": "EXIT",
        "symbol": symbol,
        "run_id": run_id,
        "timestamp": timestamp,
        "side": "LONG",
        "exit_reason": exit_reason,
        "pnl": pnl,
        "pnl_pct": pnl,
        "time_in_trade_s": time_in_trade_s,
        "entry_price": 100.0,
        "exit_price": 100.0,
        "stop_loss": 0.0,
        "take_profit": 0.0,
        "mfe": 0.0,
        "mae": 0.0,
        "tick_count": 0,
        "risk_check_passed": True,
        "risk_reject_reason": "",
    }


def _fixture(tmp_path):
    """4 real trades (2 win / 2 loss) + 3 harness-flagged exits (one run_id)."""
    real = [
        _exit(+100.0, run_id="20260806T000000Z-r1"),
        _exit(+50.0, run_id="20260806T000000Z-r2"),
        _exit(-25.0, run_id="20260806T000000Z-r3"),
        _exit(-50.0, run_id="20260806T000000Z-r4"),
    ]
    harness = [
        _exit(
            "-56.141",
            symbol="NIFTY",  # R1 underlying, no expiry/strike
            run_id="20260806T072944Z-774574ff9f83",  # R2 repeated run_id
            time_in_trade_s=17_568_447.6,  # R3 impossible time-in-trade
            exit_reason="WATCHDOG_Stop Loss",
        )
        for _ in range(3)
    ]
    records = [
        {"event_type": "SIGNAL_GENERATED", "symbol": "NIFTY", "run_id": "sig1"},
        {"event_type": "ENTRY_REJECTED", "symbol": "NIFTY", "run_id": "sig1"},
    ] + real + harness
    path = tmp_path / "journal_test.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    return path, records


def test_num_parses_string_none_and_blank():
    assert _num("-24864.3000") == -24864.3
    assert _num("1,234.5") == 1234.5
    assert _num(42) == 42.0
    assert _num(None) is None
    assert _num("") is None
    assert _num("not-a-number") is None


def test_is_underlying_symbol():
    assert is_underlying_symbol("NIFTY")
    assert is_underlying_symbol("BANKNIFTY")
    assert is_underlying_symbol("CRUDEOIL")
    assert not is_underlying_symbol("CRUDEOIL 17 AUG 7200 CALL")
    assert not is_underlying_symbol("NIFTY 21 AUG 24500 CALL")
    assert not is_underlying_symbol(None)


def test_harness_flags_all_synthetic_and_keeps_real(tmp_path):
    path, _ = _fixture(tmp_path)
    records, malformed = parse_journals([str(path)])
    exits = [r for r in records if r.get("event_type") == "EXIT"]
    assert malformed == 0
    assert len(exits) == 7

    harness = flag_harness_artifacts(exits)
    assert sum(harness["flagged"]) == 3
    assert sum(harness["r1"]) == 3
    assert sum(harness["r2"]) == 3
    assert sum(harness["r3"]) == 3

    clean = [ex for ex, f in zip(exits, harness["flagged"]) if not f]
    assert len(clean) == 4


def test_clean_metrics_match_expected_values(tmp_path):
    path, _ = _fixture(tmp_path)
    records, _ = parse_journals([str(path)])
    exits = [r for r in records if r.get("event_type") == "EXIT"]
    harness = flag_harness_artifacts(exits)
    clean = [ex for ex, f in zip(exits, harness["flagged"]) if not f]

    m = compute_metrics(clean, capital=10_000_000)
    assert m.trades == 4
    assert m.wins == 2
    assert m.losses == 2
    assert m.win_rate_pct == 50.0
    assert m.avg_win == 75.0
    assert m.avg_loss == 37.5
    assert m.avg_rr == 2.0
    assert m.total_pnl == 75.0
    # equity: 10M -> +100 -> +50(peak 10,000,150) -> -25 -> -50(end 10,000,075)
    assert m.max_drawdown == 75.0
    assert m.max_drawdown_pct == 75.0 / 10_000_000
    assert m.trades_per_session == 4.0
    assert m.sessions == 1


def test_all_metrics_include_harness_artifacts(tmp_path):
    path, _ = _fixture(tmp_path)
    records, _ = parse_journals([str(path)])
    exits = [r for r in records if r.get("event_type") == "EXIT"]

    m = compute_metrics(exits, capital=10_000_000)
    assert m.trades == 7
    assert m.wins == 2
    assert m.losses == 5
    # harness pnl stored as string -> parsed as -56.141
    assert m.exit_reasons == {"TARGET": 4, "WATCHDOG_Stop Loss": 3}
