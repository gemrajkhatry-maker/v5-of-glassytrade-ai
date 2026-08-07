"""Acceptance gate (§5.4) backtest-metrics CLI for live-trading journal JSONLs.

Parses the recorded event journals (``SIGNAL_GENERATED`` / ``ENTRY_REJECTED`` /
``EXIT`` records) and, from the ``EXIT`` events, computes the architecture
proposal's §5.4 acceptance metrics:

    - win rate      >= 55%
    - avg R:R       >= 1.5
    - max drawdown  <= 10% of equity
    - Sharpe        >= 1.0 (annualized on per-trade returns, rfr = 0)
    - trades/session  3-8

The tool is robust to string/``None`` numeric fields (journals sometimes store
``"pnl": "-24864.3000"`` or empty values).

Harness-artifact detection
--------------------------
The recorded journals contain synthetic-harness EXITs from determinism /
watchdog runs, NOT live trading. Three rules flag a record as a harness
artifact (reported separately, and excluded from the "clean" metrics):

    R1 underlying symbol   symbol is an index/commodity underlying without an
                           expiry/strike (e.g. ``NIFTY``, ``BANKNIFTY``,
                           ``CRUDEOIL``) — real paper trades carry a contract
                           (e.g. ``CRUDEOIL 17 AUG 7200 CALL``).
    R2 repeated run_id     the same ``run_id`` produced more than one EXIT
                           (determinism runs replay the same scripted exits).
    R3 impossible timing   ``time_in_trade_s`` < 0 or > 7 days (physically
                           impossible for intraday/paper sessions).

The gate verdict is evaluated on the CLEAN (harness-excluded) exits only. If
there are no clean exits the verdict is INCONCLUSIVE — the gate cannot be
assessed from harness output.

Usage::

    python scripts/acceptance_gate.py backend/live_trading_logs/journal_*.jsonl
    python scripts/acceptance_gate.py journal_a.jsonl journal_b.jsonl --json out.json

Exit code is 0 when the gate PASSES, 1 otherwise (FAIL or INCONCLUSIVE).
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Index/commodity underlyings traded by the platform. A journal symbol equal to
# one of these (no expiry/strike attached) indicates a harness replay rather
# than a real contract trade.
UNDERLYING_BASES = ("NIFTY", "BANKNIFTY", "FINNIFTY", "CRUDEOIL", "SILVERM", "GOLDM")

# Physical sanity cap for time-in-trade (seconds). Anything longer than a week,
# or negative, cannot come from a live/paper session.
MAX_REASONABLE_TIME_IN_TRADE_S = 7 * 24 * 3600

TRADING_DAYS_PER_YEAR = 252


def _num(value: Any) -> Optional[float]:
    """Coerce a possibly-string/None numeric field to float (or None)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _session_of(record: dict) -> str:
    """Calendar-day session bucket from the record timestamp."""
    ts = record.get("timestamp")
    if isinstance(ts, str) and len(ts) >= 10:
        return ts[:10]
    return "unknown"


def is_underlying_symbol(symbol: Any) -> bool:
    """True when the symbol is an underlying without an expiry/strike.

    ``NIFTY`` -> True; ``CRUDEOIL 17 AUG 7200 CALL`` -> False (has digits,
    i.e. a dated/struck contract).
    """
    if not symbol:
        return False
    normalized = str(symbol).strip().upper()
    if not normalized:
        return False
    if normalized in UNDERLYING_BASES:
        return True
    head = normalized.split()[0] if normalized.split() else normalized
    return head in UNDERLYING_BASES and not any(ch.isdigit() for ch in normalized)


def _repeated_run_ids(exits: list[dict]) -> set[str]:
    """run_ids observed on more than one EXIT record."""
    counts = Counter(ex.get("run_id") for ex in exits)
    return {rid for rid, n in counts.items() if n > 1}


def flag_harness_artifacts(exits: list[dict]) -> dict[str, list[bool]]:
    """Apply R1/R2/R3 harness heuristics; return per-rule bool lists."""
    repeated = _repeated_run_ids(exits)
    r1: list[bool] = []
    r2: list[bool] = []
    r3: list[bool] = []
    for ex in exits:
        r1.append(is_underlying_symbol(ex.get("symbol")))
        r2.append(bool(ex.get("run_id")) and ex.get("run_id") in repeated)
        time_in_trade = _num(ex.get("time_in_trade_s"))
        r3.append(
            time_in_trade is None
            or time_in_trade < 0
            or time_in_trade > MAX_REASONABLE_TIME_IN_TRADE_S
        )
    flagged = [a or b or c for a, b, c in zip(r1, r2, r3)]
    return {"r1": r1, "r2": r2, "r3": r3, "flagged": flagged}


def parse_journals(paths: list[str]) -> tuple[list[dict], int]:
    """Parse JSONL journal files into a record list (skipping bad lines)."""
    records: list[dict] = []
    malformed = 0
    for pattern in paths:
        expanded = sorted(glob.glob(pattern))
        if not expanded and not any(c in pattern for c in "*?["):
            expanded = [pattern]
        for path in expanded:
            try:
                fh = open(path, "r", encoding="utf-8")
            except OSError:
                print(f"warning: cannot open {path} - skipping", file=sys.stderr)
                continue
            with fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        malformed += 1
    return records, malformed


def extract_exits(records: list[dict]) -> list[dict]:
    """Keep only EXIT events (each is a closed trade)."""
    return [r for r in records if r.get("event_type") == "EXIT"]


@dataclass
class Metrics:
    """§5.4 metrics over a set of closed trades."""

    trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate_pct: float = 0.0
    total_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_rr: Optional[float] = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe: float = 0.0
    trades_per_session: float = 0.0
    sessions: int = 0
    exit_reasons: dict[str, int] = field(default_factory=dict)
    per_symbol: dict[str, dict[str, float]] = field(default_factory=dict)


def compute_metrics(exits: list[dict], capital: float) -> Metrics:
    """Compute §5.4 metrics from a list of EXIT records."""
    m = Metrics()
    if not exits:
        return m

    m.trades = len(exits)
    pnls = []
    for ex in exits:
        pnl = _num(ex.get("pnl"))
        if pnl is None:
            pnl = 0.0
        pnls.append(pnl)

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    m.wins = len(wins)
    m.losses = len(losses)
    m.win_rate_pct = (m.wins / m.trades * 100.0) if m.trades else 0.0
    m.total_pnl = sum(pnls)
    m.avg_win = (sum(wins) / len(wins)) if wins else 0.0
    m.avg_loss = (abs(sum(losses)) / len(losses)) if losses else 0.0
    if m.avg_loss > 0:
        m.avg_rr = m.avg_win / m.avg_loss if wins else 0.0
    elif m.avg_win > 0:
        m.avg_rr = None  # wins with no losses -> unbounded
    else:
        m.avg_rr = 0.0

    # Equity curve from cumulative PnL for max drawdown.
    equity = capital
    peak = equity
    max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    m.max_drawdown = max_dd
    m.max_drawdown_pct = (max_dd / capital) if capital else 0.0

    # Sharpe: annualized on per-trade returns (rfr = 0).
    returns = [p / capital for p in pnls] if capital else []
    if len(returns) > 1:
        mean_r = sum(returns) / len(returns)
        std_r = (sum((r - mean_r) ** 2 for r in returns) / len(returns)) ** 0.5
        if std_r > 0:
            trades_per_year = (m.trades / m.sessions * TRADING_DAYS_PER_YEAR) if m.sessions else 0
            m.sharpe = (mean_r / std_r) * (trades_per_year ** 0.5)
    else:
        m.sharpe = 0.0

    # Sessions (calendar days) and trades/session.
    sessions = Counter(_session_of(ex) for ex in exits)
    m.sessions = len(sessions)
    m.trades_per_session = m.trades / m.sessions if m.sessions else 0.0
    m.exit_reasons = dict(Counter(ex.get("exit_reason") for ex in exits))

    # Per-symbol breakdown.
    by_symbol: dict[str, list[float]] = defaultdict(list)
    for ex, p in zip(exits, pnls):
        by_symbol[str(ex.get("symbol"))].append(p)
    for sym, sym_pnls in sorted(by_symbol.items()):
        sym_wins = [p for p in sym_pnls if p > 0]
        m.per_symbol[sym] = {
            "trades": len(sym_pnls),
            "wins": len(sym_wins),
            "losses": len(sym_pnls) - len(sym_wins),
            "win_rate_pct": (len(sym_wins) / len(sym_pnls) * 100.0) if sym_pnls else 0.0,
            "total_pnl": sum(sym_pnls),
        }
    return m


def _fmt(value: Optional[float], nd: int = 2) -> str:
    if value is None:
        return "unbounded"
    return f"{value:,.{nd}f}"


def _verdict_for(clean: Metrics, clean_exits: int) -> tuple[str, list[tuple[str, str, str, str]]]:
    """Evaluate §5.4 thresholds against clean metrics.

    Returns (overall_verdict, [(metric, value, threshold, pass_fail)]).
    Overall is PASS / FAIL / INCONCLUSIVE (the latter when no clean trades).
    """
    if clean_exits == 0:
        rows = [
            ("win rate", "n/a", ">= 55%", "UNMET"),
            ("avg R:R", "n/a", ">= 1.5", "UNMET"),
            ("max DD % of equity", "n/a", "<= 10%", "UNMET"),
            ("Sharpe (annualized)", "n/a", ">= 1.0", "UNMET"),
            ("trades / session", "n/a", "3 - 8", "UNMET"),
        ]
        return "INCONCLUSIVE", rows

    checks = [
        ("win rate", clean.win_rate_pct, ">= 55%", clean.win_rate_pct >= 55.0),
        ("avg R:R", clean.avg_rr if clean.avg_rr is not None else float("inf"),
         ">= 1.5", (clean.avg_rr is None) or (clean.avg_rr >= 1.5)),
        ("max DD % of equity", clean.max_drawdown_pct * 100.0, "<= 10%",
         clean.max_drawdown_pct * 100.0 <= 10.0),
        ("Sharpe (annualized)", clean.sharpe, ">= 1.0", clean.sharpe >= 1.0),
        ("trades / session", clean.trades_per_session, "3 - 8",
         3.0 <= clean.trades_per_session <= 8.0),
    ]
    rows = []
    passed = True
    for name, value, threshold, ok in checks:
        if isinstance(value, float) and value == float("inf"):
            shown = "unbounded"
        else:
            shown = f"{value:.2f}"
        rows.append((name, shown, threshold, "PASS" if ok else "FAIL"))
        passed = passed and ok
    return ("PASS" if passed else "FAIL"), rows


def print_report(
    records: list[dict],
    exits: list[dict],
    malformed: int,
    harness: dict[str, list[bool]],
    clean: Metrics,
    all_m: Metrics,
) -> None:
    """Print the full acceptance-gate report."""
    total = len(records)
    counts = Counter(r.get("event_type") for r in records)
    flagged = harness["flagged"]
    n_flagged = sum(flagged)
    n_clean = len(exits) - n_flagged
    verdict, rows = _verdict_for(clean, n_clean)

    print("=" * 72)
    print(" ACCEPTANCE GATE (§5.4) - journal metric report")
    print("=" * 72)
    print(f" EXIT events (trades):   {len(exits)}")
    print(f" Records parsed:         {total:,}  "
          f"(SIGNAL_GENERATED={counts.get('SIGNAL_GENERATED', 0):,}, "
          f"ENTRY_REJECTED={counts.get('ENTRY_REJECTED', 0):,})")
    print(f" Malformed lines:        {malformed}")
    print(f" Sessions (calendar d.): {all_m.sessions}")

    print()
    print(" HARNESS-ARTIFACT DETECTION")
    print(f"   R1 underlying symbol (no expiry/strike): {sum(harness['r1']):6d}")
    print(f"   R2 repeated run_id (>1 EXIT):            {sum(harness['r2']):6d}")
    print(f"   R3 impossible time-in-trade (<0 or >7d): {sum(harness['r3']):6d}")
    if exits:
        pct = n_flagged / len(exits) * 100.0
    else:
        pct = 0.0
    print(f"   Flagged exits (union):                   {n_flagged:6d}"
          f"  ({pct:.1f}% of exits)")
    print(f"   Clean (real) exits:                      {n_clean:6d}")

    def block(m: Metrics, title: str) -> None:
        print()
        print(f" {title}")
        print(f"   {'trades':<28} {m.trades}")
        print(f"   {'wins / losses':<28} {m.wins} / {m.losses}")
        print(f"   {'win rate':<28} {m.win_rate_pct:.2f}%")
        print(f"   {'total PnL':<28} {_fmt(m.total_pnl)}")
        print(f"   {'avg win':<28} {_fmt(m.avg_win)}")
        print(f"   {'avg loss (magnitude)':<28} {_fmt(m.avg_loss)}")
        print(f"   {'avg R:R (avg win/avg loss)':<28} {_fmt(m.avg_rr)}")
        print(f"   {'max drawdown':<28} {_fmt(m.max_drawdown)}"
              f"  ({m.max_drawdown_pct * 100.0:.4f}% of equity)")
        print(f"   {'Sharpe (annualized, rfr=0)':<28} {m.sharpe:.3f}")
        print(f"   {'trades / session':<28} {m.trades_per_session:.2f}")
        print(f"   {'exit reasons':<28} {m.exit_reasons}")

    block(all_m, "METRICS - ALL EXITS")
    if n_clean:
        block(clean, "METRICS - CLEAN (harness-flagged excluded)")
    else:
        print("\n METRICS - CLEAN (harness-flagged excluded): no real trades recorded.")

    print()
    print(" PER-SYMBOL BREAKDOWN (all exits)")
    print(f"   {'symbol':<32} {'n':>4} {'wins':>4} {'loss':>5} {'win%':>7} {'total PnL':>12}")
    for sym, d in all_m.per_symbol.items():
        flag = " *" if is_underlying_symbol(sym) else ""
        print(f"   {sym:<32}{d['trades']:>4}{d['wins']:>5}{d['losses']:>6}"
              f"{d['win_rate_pct']:>7.1f}{d['total_pnl']:>13,.2f}{flag}")
    if any(is_underlying_symbol(s) for s in all_m.per_symbol):
        print("   (* = harness-flagged underlying symbol)")

    print()
    print(" GATE CHECK (on clean, harness-excluded trades)")
    print(f"   {'metric':<26} {'value':>12} {'threshold':>10} {'result':>8}")
    for name, value, threshold, result in rows:
        print(f"   {name:<26} {value:>12} {threshold:>10} {result:>8}")

    print()
    print("=" * 72)
    if verdict == "PASS":
        print(" VERDICT: PASS - all §5.4 metrics satisfied on real trade data.")
    elif verdict == "FAIL":
        print(" VERDICT: FAIL - §5.4 thresholds not met on clean trade data.")
    else:
        print(" VERDICT: INCONCLUSIVE - no real (non-harness) trades recorded.")
        print("          All recorded EXITs are synthetic-harness artifacts; the")
        print("          gate cannot be assessed until real paper-week-1 data exists")
        print("          (QUANT_EXECUTION_MODE=paper, architecture §5.5).")
    print("=" * 72)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="§5.4 acceptance-gate metrics from journal JSONLs.",
    )
    parser.add_argument("journals", nargs="+", help="journal_*.jsonl path(s)/glob(s)")
    parser.add_argument(
        "--capital",
        type=float,
        default=1_000_000,
        help="starting equity for drawdown/sharpe (default 10,000,000)",
    )
    parser.add_argument("--json", default=None, help="write machine-readable result here")
    args = parser.parse_args(argv)

    records, malformed = parse_journals(args.journals)
    exits = extract_exits(records)
    harness = flag_harness_artifacts(exits)
    flagged = harness["flagged"]
    clean_exits = [ex for ex, f in zip(exits, flagged) if not f]

    all_m = compute_metrics(exits, args.capital)
    clean_m = compute_metrics(clean_exits, args.capital)

    print_report(records, exits, malformed, harness, clean_m, all_m)

    verdict, rows = _verdict_for(clean_m, len(clean_exits))
    if args.json:
        out = {
            "verdict": verdict,
            "capital": args.capital,
            "records_parsed": len(records),
            "malformed_lines": malformed,
            "exits_total": len(exits),
            "exits_clean": len(clean_exits),
            "harness_flagged": sum(flagged),
            "harness_rules": {
                "r1_underlying_symbol": sum(harness["r1"]),
                "r2_repeated_run_id": sum(harness["r2"]),
                "r3_impossible_time": sum(harness["r3"]),
            },
            "gate": {name: {"value": value, "threshold": threshold, "result": result}
                     for name, value, threshold, result in rows},
            "metrics_all": {
                "trades": all_m.trades, "wins": all_m.wins, "losses": all_m.losses,
                "win_rate_pct": all_m.win_rate_pct, "total_pnl": all_m.total_pnl,
                "avg_win": all_m.avg_win, "avg_loss": all_m.avg_loss,
                "avg_rr": all_m.avg_rr, "max_drawdown": all_m.max_drawdown,
                "max_drawdown_pct": all_m.max_drawdown_pct, "sharpe": all_m.sharpe,
                "trades_per_session": all_m.trades_per_session,
                "exit_reasons": all_m.exit_reasons,
            },
            "metrics_clean": {
                "trades": clean_m.trades, "wins": clean_m.wins, "losses": clean_m.losses,
                "win_rate_pct": clean_m.win_rate_pct, "total_pnl": clean_m.total_pnl,
                "avg_win": clean_m.avg_win, "avg_loss": clean_m.avg_loss,
                "avg_rr": clean_m.avg_rr, "max_drawdown": clean_m.max_drawdown,
                "max_drawdown_pct": clean_m.max_drawdown_pct, "sharpe": clean_m.sharpe,
                "trades_per_session": clean_m.trades_per_session,
                "exit_reasons": clean_m.exit_reasons,
            },
        }
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2)
        print(f"\nWrote {args.json}")

    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
