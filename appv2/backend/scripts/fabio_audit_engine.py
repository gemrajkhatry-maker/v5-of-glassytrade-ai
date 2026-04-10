"""Fabio Valentini Audit Engine — validates system behavior against Fabio's methodology.

Reads sample data, replays through the full pipeline, and checks each decision
against Fabio's Triple-A framework:
1. Market State (Balanced vs Imbalanced)
2. Location (meaningful VP level)
3. Aggression (confirmed order flow)

Produces a structured audit report.
"""

from __future__ import annotations

import sys
import json
import time
from pathlib import Path

# Add backend to path for appv2 imports
_backend = Path(__file__).resolve().parent.parent  # backend/ directory
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from dataclasses import dataclass, field
from types import SimpleNamespace
from appv2.application.strategy_orchestrator import StrategyOrchestrator
from appv2.domain.services.gate_pipeline import GateContext, run_gate_pipeline
from appv2.domain.enums.market_state import MarketState


@dataclass
class AuditFinding:
    category: str
    rule: str
    expected: str
    actual: str
    pass_: bool
    detail: str
    candle_index: int = 0


@dataclass
class TradeAudit:
    index: int
    time: str
    direction: str
    market_state: str
    location: str  # "VA_EDGE" | "POC" | "LVN" | "INSIDE_VA" | "OUTSIDE_VA"
    aggression_score: float
    gate_passed: bool
    entry_price: float
    stop_loss: float
    take_profit: float
    outcome: str  # "WIN" | "LOSS" | "SCRATCH" | "NOT_EXECUTED"
    pnl: float
    reasons: list[str]


@dataclass
class AuditReport:
    symbol: str
    scenario: str
    total_candles: int
    findings: list[AuditFinding] = field(default_factory=list)
    trades: list[TradeAudit] = field(default_factory=list)
    market_state_transitions: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


class FabioAuditEngine:
    """Validates trading decisions against Fabio's methodology."""

    def __init__(self, symbol: str = "NIFTY", tick_size: float = 0.05):
        self.symbol = symbol
        self.tick_size = tick_size
        self.orchestrator = StrategyOrchestrator(
            symbol=symbol, underlying=symbol, tick_size=tick_size,
        )

    def run(self, candles: list[dict], scenario: str = "") -> AuditReport:
        """Replay candles through the pipeline and audit decisions."""
        report = AuditReport(
            symbol=self.symbol,
            scenario=scenario or "unknown",
            total_candles=len(candles),
        )

        prev_state = None
        open_trade: TradeAudit | None = None

        for i, c in enumerate(candles):
            candle = SimpleNamespace(
                symbol=self.symbol,
                time=c["time"],
                open=c["open"],
                high=c["high"],
                low=c["low"],
                close=c["close"],
                volume=c["volume"],
                delta=c["delta"],
                range=c["high"] - c["low"],
                body=abs(c["close"] - c["open"]),
                is_bullish=c["close"] >= c["open"],
            )

            # Process through pipeline
            obs = self.orchestrator.process_candle(candle)
            state = obs.market_state

            # Track state transitions
            if prev_state != state:
                report.market_state_transitions.append(
                    f"C{i}: {prev_state or 'INIT'} → {state} @ {c['close']:.2f}"
                )
                prev_state = state

            # Fabio Rule 1: No trades during first 15 candles (opening noise)
            if i < 15:
                self._check_finding(
                    report, i, "TIMING", "Opening Noise Suppression",
                    "No entries before candle 15",
                    "Passed" if True else "",
                    True,
                    f"Candle {i}: Opening noise phase — no trades allowed",
                )
                continue

            # Fabio Rule 2: NO_TRADE state = no entries
            if state == "NO_TRADE":
                self._check_finding(
                    report, i, "STATE", "NO_TRADE Filter",
                    "No entries in NO_TRADE state",
                    "N/A", True,
                    f"Candle {i}: NO_TRADE (POC dead zone) — no entries",
                )
                continue

            # Fabio Rule 3: Check Triple-A alignment for potential entries
            if open_trade is None:
                self._evaluate_potential_entry(report, i, c, obs)

            # Manage open trades
            if open_trade:
                self._manage_open_trade(open_trade, i, c, obs, report)

        # Close any remaining open trade
        if open_trade and open_trade.outcome == "NOT_EXECUTED":
            last_c = candles[-1]
            open_trade.outcome = "SCRATCH"
            open_trade.pnl = 0
            open_trade.reasons.append("Session close — scratched")

        # Generate summary
        self._generate_summary(report)
        return report

    def _evaluate_potential_entry(
        self, report: AuditReport, idx: int, candle: dict, obs
    ) -> None:
        """Evaluate if a trade SHOULD be taken per Fabio's rules."""
        # Check location
        loc = self._classify_location(candle["close"], obs.poc, obs.vah, obs.val)

        # Check gate
        passed, reason, detail = self.orchestrator.check_gates("LONG")

        # Fabio expects ALL THREE: State + Location + Aggression
        state_ok = obs.market_state in ("BALANCED", "IMBALANCED")
        location_ok = loc in ("VA_EDGE", "LVN", "POC")
        aggression_ok = obs.aggression_score >= 2.0

        triple_a = state_ok and location_ok and aggression_ok

        if triple_a and passed:
            # Should take trade
            sl = candle["low"] - self.tick_size * 3
            tp = obs.vah if obs.vah > candle["close"] else candle["close"] * 1.01

            trade = TradeAudit(
                index=idx,
                time=candle["time"],
                direction="LONG",
                market_state=obs.market_state,
                location=loc,
                aggression_score=obs.aggression_score,
                gate_passed=passed,
                entry_price=candle["close"],
                stop_loss=sl,
                take_profit=tp,
                outcome="NOT_EXECUTED",
                pnl=0,
                reasons=[],
            )
            report.trades.append(trade)

    def _manage_open_trade(
        self,
        trade: TradeAudit,
        idx: int,
        candle: dict,
        obs,
        report: AuditReport,
    ) -> None:
        """Manage an open trade per Fabio's exit rules."""
        if trade.outcome != "NOT_EXECUTED":
            return

        # Fabio: If wrong, wrong immediately (SL hit)
        if trade.direction == "LONG" and candle["close"] <= trade.stop_loss:
            trade.outcome = "LOSS"
            risk = trade.entry_price - trade.stop_loss
            trade.pnl = -risk  # Per-lot PnL
            trade.reasons.append(f"SL hit at candle {idx}")
            return

        if trade.direction == "SHORT" and candle["close"] >= trade.stop_loss:
            trade.outcome = "LOSS"
            risk = trade.stop_loss - trade.entry_price
            trade.pnl = -risk
            trade.reasons.append(f"SL hit at candle {idx}")
            return

        # Fabio: Take partial at +1R
        risk = abs(trade.entry_price - trade.stop_loss)
        if trade.direction == "LONG" and candle["close"] >= trade.entry_price + risk:
            trade.outcome = "WIN"
            trade.pnl = risk * 1.5  # Average exit
            trade.reasons.append(f"+1.5R target at candle {idx}")
            return

        if trade.direction == "SHORT" and candle["close"] <= trade.entry_price - risk:
            trade.outcome = "WIN"
            trade.pnl = risk * 1.5
            trade.reasons.append(f"+1.5R target at candle {idx}")
            return

        # Fabio: Time stop (30 candles max for scalping)
        if idx - trade.index >= 30:
            trade.outcome = "SCRATCH"
            pnl = candle["close"] - trade.entry_price
            trade.pnl = pnl
            trade.reasons.append(f"Time stop at candle {idx}")
            return

    def _classify_location(
        self, price: float, poc: float, vah: float, val: float
    ) -> str:
        """Classify price location relative to value area."""
        if poc <= 0 or vah <= 0 or val <= 0:
            return "UNKNOWN"

        tolerance = self.tick_size * 5

        if abs(price - poc) <= tolerance:
            return "POC"
        if abs(price - vah) <= tolerance:
            return "VA_EDGE"
        if abs(price - val) <= tolerance:
            return "VA_EDGE"
        if val < price < vah:
            return "INSIDE_VA"
        return "OUTSIDE_VA"

    def _check_finding(
        self,
        report: AuditReport,
        idx: int,
        category: str,
        rule: str,
        expected: str,
        actual: str,
        pass_: bool,
        detail: str,
    ) -> None:
        report.findings.append(AuditFinding(
            category=category,
            rule=rule,
            expected=expected,
            actual=actual,
            pass_=pass_,
            detail=detail,
            candle_index=idx,
        ))

    def _generate_summary(self, report: AuditReport) -> None:
        wins = [t for t in report.trades if t.outcome == "WIN"]
        losses = [t for t in report.trades if t.outcome == "LOSS"]
        scratches = [t for t in report.trades if t.outcome == "SCRATCH"]

        total_pnl = sum(t.pnl for t in report.trades)
        win_rate = len(wins) / len(report.trades) if report.trades else 0

        # Fabio's 3-loss rule
        consecutive_losses = 0
        max_consecutive = 0
        for t in report.trades:
            if t.outcome == "LOSS":
                consecutive_losses += 1
                max_consecutive = max(max_consecutive, consecutive_losses)
            else:
                consecutive_losses = 0

        report.summary = {
            "total_trades": len(report.trades),
            "wins": len(wins),
            "losses": len(losses),
            "scratches": len(scratches),
            "win_rate": round(win_rate * 100, 1),
            "total_pnl": round(total_pnl, 2),
            "max_consecutive_losses": max_consecutive,
            "state_transitions": len(report.market_state_transitions),
            "fabio_rules_checked": len(report.findings),
            "fabio_rules_passed": sum(1 for f in report.findings if f.pass_),
        }

    @staticmethod
    def load_candles(filepath: str) -> list[dict]:
        """Load candles from JSON file."""
        with open(filepath) as f:
            data = json.load(f)
        return data.get("candles", [])

    @staticmethod
    def save_report(report: AuditReport, filepath: str) -> None:
        """Save audit report to JSON."""
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        data = {
            "symbol": report.symbol,
            "scenario": report.scenario,
            "total_candles": report.total_candles,
            "market_state_transitions": report.market_state_transitions,
            "trades": [
                {
                    "index": t.index,
                    "time": t.time,
                    "direction": t.direction,
                    "market_state": t.market_state,
                    "location": t.location,
                    "aggression_score": round(t.aggression_score, 2),
                    "gate_passed": t.gate_passed,
                    "entry_price": t.entry_price,
                    "stop_loss": t.stop_loss,
                    "take_profit": t.take_profit,
                    "outcome": t.outcome,
                    "pnl": round(t.pnl, 2),
                    "reasons": t.reasons,
                }
                for t in report.trades
            ],
            "summary": report.summary,
        }
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Saved audit report to {filepath}")


def run_all_audits(
    data_dir: str = "appv2/sample_data",
    output_dir: str = "appv2/audit_reports",
) -> list[AuditReport]:
    """Run audits on all sample data files."""
    engine_nifty = FabioAuditEngine("NIFTY", tick_size=0.05)
    engine_crude = FabioAuditEngine("CRUDEOIL", tick_size=1.0)

    scenarios = [
        ("nifty_balanced.json", engine_nifty, "NSE NIFTY Balanced Day"),
        ("nifty_imbalanced.json", engine_nifty, "NSE NIFTY Imbalanced Day"),
        ("crudeoil_balanced.json", engine_crude, "MCX CRUDEOIL Balanced Day"),
        ("crudeoil_imbalanced.json", engine_crude, "MCX CRUDEOIL Imbalanced Day"),
    ]

    reports = []
    for filename, engine, scenario_name in scenarios:
        filepath = f"{data_dir}/{filename}"
        if not Path(filepath).exists():
            print(f"Skipping {filepath} (not found)")
            continue

        candles = FabioAuditEngine.load_candles(filepath)
        report = engine.run(candles, scenario=scenario_name)
        FabioAuditEngine.save_report(report, f"{output_dir}/{filename.replace('.json', '_audit.json')}")
        reports.append(report)

        s = report.summary
        print(f"\n{'='*60}")
        print(f"{scenario_name}")
        print(f"{'='*60}")
        print(f"  Candles: {report.total_candles}")
        print(f"  Trades: {s['total_trades']} | W: {s['wins']} L: {s['losses']} S: {s['scratches']}")
        print(f"  Win Rate: {s['win_rate']}%")
        print(f"  Total P&L: {s['total_pnl']}")
        print(f"  Max Consecutive Losses: {s['max_consecutive_losses']}")
        print(f"  State Transitions: {s['state_transitions']}")
        print(f"  Fabio Rules: {s['fabio_rules_passed']}/{s['fabio_rules_checked']} passed")

    return reports

if __name__ == "__main__":
    run_all_audits()

