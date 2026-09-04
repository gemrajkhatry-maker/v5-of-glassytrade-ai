from __future__ import annotations
from datetime import datetime, timezone, timedelta
from quantv2.types import Bar, Context, Decision
from quantv2.pipeline import decide
from quantv2.exits import ExitConfig, evaluate_exit
from quantv2.oms import PaperOMS, Position
from quantv2.risk import size
from quantv2.clock import SessionClock
from quantv2.session_risk import SessionRisk

_IST = timezone(timedelta(hours=5, minutes=30))


class Engine:
    def __init__(self, symbol: str, interval_sec: int = 300, oms=None, equity: float = 100000.0, risk_pct: float = 0.005, lot: float = 1.0, exit_cfg: ExitConfig | None = None, clock: SessionClock | None = None, risk: SessionRisk | None = None) -> None:
        self.symbol = symbol
        self.interval_sec = interval_sec
        self.oms = oms or PaperOMS()
        self.equity = equity
        self.risk_pct = risk_pct
        self.lot = lot
        self.exit_cfg = exit_cfg or ExitConfig()
        self.position = None
        self.trail: dict = {}
        self.open_risk = 0.0
        self.risk_cap = float("inf")
        self._bucket = None
        self._ticks: list = []
        self.amt = None
        self.session_open = True
        self.can_trade = True
        self.cooldown_s = 0.0
        self.last_decision = None
        self.clock = clock
        self.risk = risk

    def _flush_bar(self) -> Bar:
        ts = self._ticks[0][0]
        prices = [t[1] for t in self._ticks]
        vols = [t[2] for t in self._ticks]
        deltas = [t[3] for t in self._ticks]
        iso = datetime.fromtimestamp(ts, tz=_IST).isoformat()
        bar = Bar(time=iso, open=prices[0], high=max(prices), low=min(prices), close=prices[-1], volume=sum(vols), delta=sum(deltas))
        self._ticks = []
        return bar

    def on_tick(self, ts: float, price: float, volume: float = 0.0, delta: float = 0.0):
        bucket = int(ts // self.interval_sec)
        if self._bucket is None:
            self._bucket = bucket
        if bucket != self._bucket:
            bar = self._flush_bar()
            self._bucket = bucket
            self._ticks.append((ts, price, volume, delta))
            return self.on_bar(bar)
        self._ticks.append((ts, price, volume, delta))
        return None

    def _context(self, bar: Bar) -> Context:
        extra: dict = {}
        if self.amt is not None:
            snap = self.amt.update(bar)
            extra = snap.get("extra", {})
            return Context(symbol=self.symbol, bar=bar, tick=snap.get("tick", 0.05), vah=snap.get("vah"), val=snap.get("val"), poc=snap.get("poc"), cvd_slope=snap.get("cvd_slope", 0.0), extra=extra)
        return Context(symbol=self.symbol, bar=bar, extra=extra)

    def on_bar(self, bar: Bar) -> Decision:
        epoch = self._epoch(bar.time)
        if self.clock is not None:
            self.session_open = self.clock.is_open(epoch) if epoch is not None else True
        if self.position is not None:
            if self.clock is not None and epoch is not None and self.clock.force_exit(epoch):
                try:
                    fill = self.oms.close(self.position, bar.close, "SESSION_CLOSE")
                except Exception:
                    return Decision(False, "EXIT_RETRY")
                if self.risk is not None:
                    self.risk.record_fill(fill.pnl, epoch)
                self.position = None
                self.trail = {}
                self.open_risk = 0.0
                return Decision(False, "EXITED_SESSION_CLOSE")
            elapsed_min = self._elapsed_min(bar.time, self.position.opened_at)
            d, self.trail = evaluate_exit(self.position, bar, self.trail, self.exit_cfg, elapsed_min=elapsed_min)
            if d.should_exit:
                try:
                    fill = self.oms.close(self.position, d.price, d.reason)
                except Exception:
                    return Decision(False, "EXIT_RETRY")
                if self.risk is not None and epoch is not None:
                    self.risk.record_fill(fill.pnl, epoch)
                self.position = None
                self.trail = {}
                self.open_risk = 0.0
                return Decision(False, f"EXITED_{d.reason}")
            return Decision(False, "HOLDING")
        ctx = self._context(bar)
        can_trade, cooldown_s = self.can_trade, self.cooldown_s
        if self.risk is not None:
            if epoch is None:
                return Decision(False, "HALTED")
            ok, why = self.risk.can_trade(epoch)
            if not ok:
                return Decision(False, why)
            can_trade, cooldown_s = True, self.risk.cooldown_s(epoch)
        out = decide(ctx, session_open=self.session_open, can_trade=can_trade, cooldown_s=cooldown_s, position_open=False, equity=self.equity, oms=self.oms, risk_pct=self.risk_pct, lot=self.lot, open_risk=self.open_risk, risk_cap=self.risk_cap)
        if out.approved:
            if out.position is None:
                return Decision(False, "SUBMIT_FAILED")
            self.position = out.position
            self.trail = {}
            self.open_risk = abs(out.position.entry - out.position.sl) * float(out.position.qty)
        return out

    @staticmethod
    def _epoch(iso: str) -> float | None:
        try:
            return datetime.fromisoformat(iso).timestamp()
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _elapsed_min(now_iso: str, opened_iso: str) -> float | None:
        try:
            t0 = datetime.fromisoformat(opened_iso)
            t1 = datetime.fromisoformat(now_iso)
            return (t1 - t0).total_seconds() / 60.0
        except (ValueError, TypeError):
            return None
