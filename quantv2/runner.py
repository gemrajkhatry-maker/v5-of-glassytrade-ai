from __future__ import annotations
from dataclasses import dataclass, field
from quantv2.coordinator import Coordinator
from quantv2.engine import Engine
from quantv2.oms import PaperOMS
from quantv2.broker import BrokerAdapter
from quantv2.clock import SessionClock
from quantv2.session_risk import RiskLimits, SessionRisk
from quantv2.dhan_feed import DhanFeed
from quantv2.store import save
from quantv2.snapshot import snapshot
from quantv2.exits import ExitConfig
from quantv2.amt import SessionAMT
from quantv2.journal import Journal


@dataclass
class RunnerConfig:
    symbols: list[str]
    interval_sec: int = 300
    mode: str = "paper"
    equity: float = 100000.0
    risk_cap: float = 100000.0
    risk_limits: RiskLimits = field(default_factory=RiskLimits)
    store_path: str = "quantv2_state.json"
    state_interval_s: float = 30.0
    tick: float = 0.05


class Runner:
    def __init__(self, config: RunnerConfig, coordinator: Coordinator, feed: DhanFeed, clock: SessionClock, broker: BrokerAdapter, journal: Journal | None = None) -> None:
        self.config = config
        self.coordinator = coordinator
        self.feed = feed
        self.clock = clock
        self.broker = broker
        self.journal = journal
        self.halted = False
        self.security_ids = feed.by_id_inverted()
        self._since_save = 0.0
        self._logged: dict[str, object] = {}

    @classmethod
    def build(cls, config: RunnerConfig, transport=None, security_ids: dict[str, int] | None = None, journal: Journal | None = None) -> "Runner":
        clock = SessionClock()
        c = Coordinator(risk_cap=config.risk_cap)
        for sym in config.symbols:
            eng = Engine(symbol=sym, interval_sec=config.interval_sec, oms=PaperOMS(), equity=config.equity, clock=clock, risk=SessionRisk(config.risk_limits), exit_cfg=ExitConfig(), on_fill=(lambda f, sym=sym: journal.log_fill(sym, f)) if journal else None)
            eng.amt = SessionAMT(tick=config.tick)
            c.add(eng)
        broker = BrokerAdapter(mode=config.mode, oms=PaperOMS(), live_port=None)
        feed = DhanFeed(c, security_ids or {s: i + 1 for i, s in enumerate(config.symbols)}, transport, clock=clock)
        return cls(config, c, feed, clock, broker, journal)

    def step(self, frame: dict) -> int:
        n = self.feed.handle_frame(frame)
        if self.journal is not None:
            for sym, eng in self.coordinator.engines.items():
                d = eng.last_decision
                if d is not None and d is not self._logged.get(sym):
                    self.journal.log_decision(sym, d)
                    self._logged[sym] = d
        return n

    def tick_watchdog(self, now: float) -> None:
        if not self.halted and self.clock.force_exit(now):
            self.coordinator.eod_flatten("SESSION_CLOSE")
            self.halted = True
            for eng in self.coordinator.engines.values():
                eng.can_trade = False

    def maybe_save(self, dt: float) -> None:
        self._since_save += dt
        if self._since_save >= self.config.state_interval_s:
            self.save_state()
            self._since_save = 0.0

    def save_state(self) -> None:
        save(self.coordinator, self.config.store_path)

    def snapshot(self) -> dict:
        return snapshot(self.coordinator)