"""Risk evaluation stage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import logging
from decimal import Decimal
from typing import Any

from app.domain.trading.service.risk_manager import DailyRiskState, RiskManager, KillSwitch
from app.runtime.pipeline import StageMetrics
from app.runtime.pipeline.events import (
    GateResult,
    RiskResult,
    Signal,
    GateResultType,
    PositionEvent,
)
from app.domain.trading.model.aggregates import Portfolio
from app.domain.trading.model.entities import Signal as DomainSignal
from app.domain.trading.model.entities import Position
from app.domain.trading.model.enums import SignalType, Source, SetupType, Side, PositionStatus
from app.domain.risk.service import CircuitBreakers, RiskTierEngine
from app.domain.risk.service import FlashCrashProtector, VelocityLevel, VelocityState
from app.domain.exit.service import LossTracker

logger = logging.getLogger(__name__)


@dataclass
class _SymbolRiskState:
    kill_switch: KillSwitch
    risk_manager: RiskManager
    portfolio: Portfolio
    flash_crash: FlashCrashProtector
    flash_state: VelocityState | None


class RiskEvaluation:
    """Evaluate whether approved gates can proceed."""

    def __init__(self):
        self._state: dict[str, _SymbolRiskState] = {}
        self._metrics = StageMetrics(stage_name="RiskEvaluation")
        self._loss_tracker = LossTracker()
        self._circuit_breakers = CircuitBreakers()
        self._risk_tiers: dict[str, RiskTierEngine] = {}

    @property
    def metrics(self) -> StageMetrics:
        return self._metrics

    def _state_for(self, symbol: str) -> _SymbolRiskState:
        if symbol not in self._state:
            portfolio = Portfolio.create_default()
            self._state[symbol] = _SymbolRiskState(
                kill_switch=KillSwitch(),
                risk_manager=RiskManager(),
                portfolio=portfolio,
                flash_crash=FlashCrashProtector(),
                flash_state=None,
            )
            self._state[symbol].risk_manager._daily.reset(float(portfolio.equity))
            return self._state[symbol]

        state = self._state[symbol]
        if (
            state.risk_manager._daily.current_equity <= 0.0
            and state.portfolio.equity > 0
        ):
            state.risk_manager._daily.reset(float(state.portfolio.equity))
        return state

    @staticmethod
    def _to_seconds(timestamp: float) -> float:
        """Normalize timestamps to seconds for windowed velocity checks."""
        if timestamp > 1_000_000_000_000:
            return timestamp / 1_000_000_000
        return timestamp

    def observe_price(self, symbol: str, price: float, timestamp: float) -> None:
        """Update flash crash protector state for a symbol with latest tick price."""
        if not symbol or price <= 0:
            return
        state = self._state_for(symbol)
        state.flash_state = state.flash_crash.update(
            float(price),
            self._to_seconds(float(timestamp)),
        )

    def process(self, gate: GateResult) -> list[RiskResult]:
        try:
            state = self._state_for(gate.symbol)
            symbol = gate.symbol
            approved = gate.result == GateResultType.APPROVED
            rejection_reason = gate.rejection_reason
            drawdown_ok = True
            consecutive_losses_ok = True
            position_limit_ok = True
            notional_ok = True
            kill_switch_active = state.kill_switch.is_halted
            circuit_breaker_triggered = False
            remaining_buying_power = 0.0
            if state.flash_state is not None and state.flash_state.is_halted:
                approved = False
                circuit_breaker_triggered = True
                kill_switch_active = True
                rejection_reason = (
                    f"{rejection_reason} | Flash crash protection: {state.flash_state.reason}"
                    if rejection_reason
                    else f"Flash crash protection: {state.flash_state.reason}"
                )
                logger.warning(
                    "Risk evaluation blocked by flash crash for %s: %s",
                    symbol,
                    state.flash_state.reason,
                )

            if approved:
                sig = gate.signal
                approved_signal, reason = state.risk_manager.check_signal(
                    _to_domain_signal(sig),
                    state.portfolio,
                )
                if not approved_signal:
                    approved = False
                    rejection_reason = reason
                else:
                    # Evaluate hard circuit breakers against today's realized PnL and loss streak.
                    consecutive_losses = int(
                        getattr(state.risk_manager._daily, "consecutive_losses", 0)
                    )
                    session_pnl = float(
                        getattr(state.risk_manager._daily, "realized_pnl", 0.0)
                    )
                    current_equity = float(
                        getattr(
                            state.risk_manager._daily,
                            "current_equity",
                            state.portfolio.equity,
                        )
                    )
                    portfolio_balance = float(getattr(state.portfolio, "balance", 0))
                    breaker = self._circuit_breakers.evaluate(
                        consecutive_losses=consecutive_losses,
                        session_pnl=session_pnl,
                        cumulative_account_pnl=float(current_equity - portfolio_balance),
                    )
                    circuit_breaker_triggered = breaker.is_locked
                    if circuit_breaker_triggered:
                        approved = False
                        rejection_reason = breaker.detail
                        kill_switch_active = True
                    else:
                        if (
                            state.flash_state is not None
                            and state.flash_state.level == VelocityLevel.ELEVATED
                        ):
                            notional_ok = False
                            remaining_buying_power = float(state.portfolio.equity) * 0.5
                            logger.info(
                                "Flash-crash elevated velocity: reducing sizing signal for %s",
                                symbol,
                            )
                        else:
                            remaining_buying_power = float(state.portfolio.equity)
                        # Initialize per-symbol risk tier if absent and advance tier on each accepted signal.
                        if symbol not in self._risk_tiers:
                            self._risk_tiers[symbol] = RiskTierEngine(
                                capital=float(state.portfolio.equity)
                            )

            self._metrics.record(0)
            return [RiskResult(
                symbol=symbol,
                timestamp=gate.timestamp,
                approved=approved,
                rejection_reason=rejection_reason,
                drawdown_ok=drawdown_ok,
                consecutive_losses_ok=consecutive_losses_ok,
                position_limit_ok=position_limit_ok,
                notional_ok=notional_ok,
                kill_switch_active=kill_switch_active,
                circuit_breaker_triggered=circuit_breaker_triggered,
                remaining_buying_power=remaining_buying_power,
            )]
        except Exception:
            self._metrics.record_error()
            logger.exception("Risk evaluation failed")
            return []

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {
            symbol: {
                "kill_switch": {
                    "is_halted": state.kill_switch.is_halted,
                    "reason": state.kill_switch.reason,
                    "triggered_at": (
                        state.kill_switch.triggered_at.isoformat()
                        if state.kill_switch.triggered_at is not None
                        else None
                    ),
                },
                "risk_manager": {
                    "daily": {
                        "trade_date": state.risk_manager._daily.trade_date.isoformat(),
                        "starting_equity": state.risk_manager._daily.starting_equity,
                        "peak_equity": state.risk_manager._daily.peak_equity,
                        "current_equity": state.risk_manager._daily.current_equity,
                        "realized_pnl": state.risk_manager._daily.realized_pnl,
                        "consecutive_losses": state.risk_manager._daily.consecutive_losses,
                        "total_trades": state.risk_manager._daily.total_trades,
                        "halted": state.risk_manager._daily.halted,
                        "halt_reason": state.risk_manager._daily.halt_reason,
                    },
                    "recent_outcomes": list(state.risk_manager._recent_outcomes),
                    "baseline_win_rate": state.risk_manager._baseline_win_rate,
                    "drift_alert": state.risk_manager._drift_alert,
                    "drift_message": state.risk_manager._drift_message,
                },
                "flash_crash": {
                    "is_halted": bool(
                        state.flash_state.is_halted if state.flash_state else False
                    ),
                    "level": (
                        state.flash_state.level.value
                        if state.flash_state is not None
                        else VelocityLevel.NORMAL.value
                    ),
                    "velocity_pct_per_sec": (
                        float(state.flash_state.velocity_pct_per_sec)
                        if state.flash_state is not None
                        else 0.0
                    ),
                    "reason": state.flash_state.reason if state.flash_state else "",
                },
                "portfolio": {
                    "balance": float(state.portfolio.balance),
                    "equity": float(state.portfolio.equity),
                    "leverage": state.portfolio.leverage,
                    "open_positions": [
                        _serialize_position(position)
                        for position in state.portfolio.positions
                        if position.status == PositionStatus.OPEN
                    ],
                },
            }
            for symbol, state in self._state.items()
        }

    def notify_trade_closed(self, symbol: str, pnl: float) -> None:
        state = self._state_for(symbol)
        state.risk_manager.record_trade_result(pnl)
        self._apply_trade_outcome(symbol, state, pnl)

    def _apply_trade_outcome(self, symbol: str, state: _SymbolRiskState, pnl: float) -> None:
        if pnl >= 0:
            self._loss_tracker.record_win(symbol)
        else:
            self._loss_tracker.record_loss(symbol, stop_price=0.0)
        if symbol in self._risk_tiers:
            pnl_r = pnl / max(float(state.portfolio.equity), 1.0)
            self._risk_tiers[symbol].record_trade(pnl_r)

    def sync_position_event(self, event: PositionEvent) -> None:
        """Mirror portfolio mutations from position lifecycle into risk-owned state."""
        if not event.position_id:
            return
        state = self._state_for(event.symbol)
        portfolio = state.portfolio

        if event.event_type == "OPENED":
            if any(
                position.id == event.position_id and position.status == PositionStatus.OPEN
                for position in portfolio.positions
            ):
                return
            side = Side.LONG
            if event.side == "SHORT":
                side = Side.SHORT
            portfolio.positions.append(Position(
                id=str(event.position_id),
                symbol=event.symbol,
                side=side,
                source=Source.AMT,
                entry_price=Decimal(str(event.entry_price)),
                size=Decimal(str(event.size)),
                stop_loss=Decimal(str(event.stop_loss)),
                take_profit=Decimal(str(event.take_profit)),
                pnl=Decimal(str(event.pnl or 0.0)),
                entry_time=str(event.timestamp),
                status=PositionStatus.OPEN,
            ))
            return

        if event.event_type == "UPDATED":
            # Conservative no-op for partial updates; explicit CLOSED event carries full settlement.
            return

        if event.event_type == "CLOSED":
            closed_pnl = float(event.pnl or 0.0)
            removed = False
            for index, position in enumerate(list(portfolio.positions)):
                if position.id == event.position_id and position.status == PositionStatus.OPEN:
                    portfolio.positions.pop(index)
                    position.pnl = Decimal(str(closed_pnl))
                    portfolio.balance += position.pnl
                    portfolio.closed_trades.append(position)
                    removed = True
                    break

            if removed:
                portfolio.equity = portfolio.balance + sum((p.pnl for p in portfolio.positions), Decimal("0"))
                state.risk_manager.record_trade_result(closed_pnl)
                self._apply_trade_outcome(event.symbol, state, closed_pnl)

    def retract_position(self, symbol: str, position_id: str) -> None:
        """Drop a pre-execution open position without accounting trade outcome.

        Used when broker-side execution fails (reject/cancel) and no realized PnL exists.
        """
        state = self._state_for(symbol)
        portfolio = state.portfolio
        for index, position in enumerate(list(portfolio.positions)):
            if position.id == position_id and position.status == PositionStatus.OPEN:
                portfolio.positions.pop(index)
                if portfolio.positions:
                    portfolio.equity = portfolio.balance + sum(
                        (p.pnl for p in portfolio.positions), Decimal("0")
                    )
                else:
                    portfolio.equity = portfolio.balance
                return

    def warmup(self) -> None:
        self._state = {}
        self._metrics.reset()

    def teardown(self) -> None:
        self.warmup()

    def reset(self) -> None:
        self.warmup()

    def restore(self, payload: dict[str, Any]) -> None:
        self._state = {}
        for symbol, state_payload in payload.items():
            if not isinstance(state_payload, dict):
                continue
            kill_payload = state_payload.get("kill_switch", {})
            risk_payload = state_payload.get("risk_manager", {})
            portfolio_payload = state_payload.get("portfolio", {})
            flash_payload = state_payload.get("flash_crash", {})

            portfolio = Portfolio.create_default()
            if "balance" in portfolio_payload:
                portfolio.balance = Decimal(str(portfolio_payload["balance"]))
            if "equity" in portfolio_payload:
                portfolio.equity = Decimal(str(portfolio_payload["equity"]))
            if "leverage" in portfolio_payload:
                portfolio.leverage = int(portfolio_payload["leverage"] or 1)
            raw_positions = portfolio_payload.get("open_positions")
            if isinstance(raw_positions, list):
                for item in raw_positions:
                    if isinstance(item, dict):
                        portfolio.positions.append(_deserialize_position(item))

            daily_payload = risk_payload.get("daily", {})
            try:
                trade_date = daily_payload.get("trade_date")
                if isinstance(trade_date, date):
                    parsed_trade_date = trade_date
                elif isinstance(trade_date, datetime):
                    parsed_trade_date = trade_date.date()
                elif isinstance(trade_date, str):
                    parsed_trade_date = datetime.fromisoformat(trade_date).date()
                else:
                    parsed_trade_date = DailyRiskState().trade_date
            except (TypeError, ValueError):
                parsed_trade_date = DailyRiskState().trade_date

            daily = DailyRiskState(
                trade_date=parsed_trade_date,
                starting_equity=float(daily_payload.get("starting_equity", portfolio.equity)),
                peak_equity=float(daily_payload.get("peak_equity", portfolio.equity)),
                current_equity=float(daily_payload.get("current_equity", portfolio.equity)),
                realized_pnl=float(daily_payload.get("realized_pnl", 0.0)),
                consecutive_losses=int(daily_payload.get("consecutive_losses", 0)),
                total_trades=int(daily_payload.get("total_trades", 0)),
                halted=bool(daily_payload.get("halted", False)),
                halt_reason=str(daily_payload.get("halt_reason", "")),
            )

            risk_manager = RiskManager()
            risk_manager._daily = daily
            risk_manager._recent_outcomes = list(risk_payload.get("recent_outcomes", []))
            risk_manager._baseline_win_rate = float(risk_payload.get("baseline_win_rate", 0.45))
            risk_manager._drift_alert = bool(risk_payload.get("drift_alert", False))
            risk_manager._drift_message = str(risk_payload.get("drift_message", ""))

            kill_switch = KillSwitch()
            if bool(kill_payload.get("is_halted", False)):
                reason = str(kill_payload.get("reason", "restored from snapshot"))
                kill_switch.trigger(reason)
            else:
                kill_switch.reset()
            triggered_at = kill_payload.get("triggered_at")
            if kill_payload.get("is_halted") and triggered_at:
                try:
                    kill_switch.triggered_at = datetime.fromisoformat(str(triggered_at))
                except (TypeError, ValueError):
                    pass

            self._state[symbol] = _SymbolRiskState(
                kill_switch=kill_switch,
                risk_manager=risk_manager,
                portfolio=portfolio,
                flash_crash=FlashCrashProtector(),
                flash_state=None,
            )
            if isinstance(flash_payload, dict):
                try:
                    level = VelocityLevel(flash_payload.get("level", VelocityLevel.NORMAL))
                except ValueError:
                    level = VelocityLevel.NORMAL
                self._state[symbol].flash_state = VelocityState(
                    level=level,
                    velocity_pct_per_sec=float(
                        flash_payload.get("velocity_pct_per_sec", 0.0)
                    ),
                    is_halted=bool(flash_payload.get("is_halted", False)),
                    reason=str(flash_payload.get("reason", "")),
                )


def _to_domain_signal(signal: Signal) -> DomainSignal:
    return DomainSignal(
        type=SignalType.BUY if signal.type == "LONG" else SignalType.SELL,
        price=signal.entry,
        reason=signal.reason,
        stop_loss=signal.sl,
        take_profit=signal.tp,
        timestamp=str(signal.timestamp),
        setup=SetupType.TREND_MODEL,
        source=Source.AMT,
        metadata={
            "symbol": signal.symbol,
            "confidence": "Medium" if signal.confidence < 0.7 else "High",
            "rr": signal.rr,
        },
    )


def _serialize_position(position: Position) -> dict[str, object]:
    return {
        "id": str(position.id),
        "symbol": position.symbol,
        "side": position.side.value,
        "status": position.status.value,
        "entry_price": float(position.entry_price),
        "size": float(position.size),
        "stop_loss": float(position.stop_loss),
        "take_profit": float(position.take_profit),
        "pnl": float(position.pnl),
        "entry_time": position.entry_time,
        "exit_price": float(position.exit_price) if position.exit_price is not None else None,
        "exit_time": position.exit_time,
        "close_reason": position.close_reason,
        "metadata": position.metadata,
    }


def _deserialize_position(raw: dict[str, object]) -> Position:
    side = Side.LONG
    try:
        side = Side(str(raw.get("side", Side.LONG)))
    except ValueError:
        side = Side.LONG

    status = PositionStatus.OPEN
    try:
        status = PositionStatus(str(raw.get("status", PositionStatus.OPEN)))
    except ValueError:
        status = PositionStatus.OPEN

    return Position(
        id=str(raw.get("id", "")),
        symbol=str(raw.get("symbol", "")),
        side=side,
        source=Source.AMT,
        entry_price=Decimal(str(raw.get("entry_price", 0.0))),
        size=Decimal(str(raw.get("size", 0.0))),
        stop_loss=Decimal(str(raw.get("stop_loss", 0.0))),
        take_profit=Decimal(str(raw.get("take_profit", 0.0))),
        pnl=Decimal(str(raw.get("pnl", 0.0))),
        entry_time=str(raw.get("entry_time", "")),
        status=status,
        exit_price=Decimal(str(raw["exit_price"])) if raw.get("exit_price") is not None else None,
        exit_time=str(raw["exit_time"]) if raw.get("exit_time") is not None else None,
        close_reason=raw.get("close_reason"),
        metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else None,
    )
