"""Broker-verified, resumable end-of-day state machine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from enum import StrEnum
from typing import Any, Mapping

from glassytrade.domain.common.ids import ContractId


class EodState(StrEnum):
    IDLE = "IDLE"
    ENTRY_BLOCKED = "ENTRY_BLOCKED"
    VERIFYING = "VERIFYING"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class SessionKey:
    exchange: str
    trading_date: str

    @classmethod
    def from_value(cls, value: "SessionKey | tuple[str, str] | str") -> "SessionKey":
        if isinstance(value, cls):
            return value
        if isinstance(value, tuple):
            return cls(value[0], value[1])
        exchange, trading_date = value.split(":", 1)
        return cls(exchange, trading_date)


@dataclass(frozen=True, slots=True)
class EodReport:
    session: SessionKey
    state: EodState
    entries_allowed: bool
    unresolved_attempt_ids: tuple[str, ...]
    open_contract_ids: tuple[ContractId, ...]
    working_order_ids: tuple[str, ...]
    protective_order_ids: tuple[str, ...]


class EodService:
    def __init__(
        self,
        broker: Any,
        *,
        unresolved_cases: tuple[Any, ...] = (),
        state_path: str | Path | None = None,
    ) -> None:
        self.broker = broker
        self.unresolved_cases = tuple(unresolved_cases)
        self.state_path = Path(state_path) if state_path is not None else None
        self._sessions: dict[SessionKey, EodState] = {}
        self._load()

    @staticmethod
    def _session_id(session: SessionKey) -> str:
        return f"{session.exchange}|{session.trading_date}"

    def _load(self) -> None:
        if self.state_path is None or not self.state_path.exists():
            return
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        for key, value in data.items():
            exchange, trading_date = key.split("|", 1)
            self._sessions[SessionKey(exchange, trading_date)] = EodState(value)

    def _save(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {self._session_id(key): value.value for key, value in self._sessions.items()}
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        temporary.replace(self.state_path)

    def arm(self, session: SessionKey | tuple[str, str] | str, now: datetime) -> EodState:
        key = SessionKey.from_value(session)
        self._sessions[key] = EodState.ENTRY_BLOCKED
        self._save()
        return self._sessions[key]

    def _contract_id(self, value: Any) -> ContractId | None:
        if isinstance(value, ContractId):
            return value
        if isinstance(value, Mapping):
            raw = value.get("contract_id", value.get("contract"))
        else:
            raw = getattr(value, "contract_id", None)
        if raw is None:
            return None
        if isinstance(raw, ContractId):
            return raw
        return ContractId(
            str(getattr(value, "exchange", "UNKNOWN")),
            str(raw),
            str(getattr(value, "expiry", "unknown")),
            str(getattr(value, "instrument_type", "UNKNOWN")),
            None,
            str(getattr(value, "option_type", "UNKNOWN")),
            str(raw),
        )

    def advance(self, now: datetime) -> EodReport:
        if not self._sessions:
            session = SessionKey("UNKNOWN", "unknown")
            state = EodState.IDLE
        else:
            session, state = next(iter(self._sessions.items()))
        if state is EodState.IDLE:
            return EodReport(session, state, True, (), (), (), ())
        self._sessions[session] = EodState.VERIFYING
        self._save()
        try:
            positions = tuple(self.broker.list_positions())
            orders = tuple(self.broker.list_orders())
            _fills = tuple(self.broker.list_fills())
        except Exception:
            self._sessions[session] = EodState.BLOCKED
            self._save()
            return EodReport(session, EodState.BLOCKED, False, (), (), (), ())
        open_contracts = tuple(
            contract
            for position in positions
            if (contract := self._contract_id(position)) is not None
            and int(position.get("signed_quantity", 0) if isinstance(position, Mapping) else getattr(position, "signed_quantity", 0)) != 0
        )
        working_orders = tuple(
            str(order.get("broker_order_id", order.get("order_id", "")))
            if isinstance(order, Mapping)
            else str(getattr(order, "broker_order_id", ""))
            for order in orders
            if str(order.get("status", getattr(order, "status", "UNKNOWN"))).upper()
            not in {"CANCELLED", "REJECTED", "FILLED", "EXPIRED"}
        )
        protective_orders = tuple(
            str(order.get("broker_order_id", order.get("order_id", "")))
            if isinstance(order, Mapping)
            else str(getattr(order, "broker_order_id", ""))
            for order in orders
            if str(order.get("purpose", getattr(order, "purpose", ""))).upper() == "STOP"
        )
        unresolved = tuple(
            str(getattr(case, "discrepancy", case))
            for case in self.unresolved_cases
        )
        complete = not open_contracts and not working_orders and not protective_orders and not unresolved
        next_state = EodState.COMPLETE if complete else EodState.VERIFYING
        self._sessions[session] = next_state
        self._save()
        return EodReport(
            session=session,
            state=next_state,
            entries_allowed=next_state is EodState.COMPLETE,
            unresolved_attempt_ids=unresolved,
            open_contract_ids=open_contracts,
            working_order_ids=working_orders,
            protective_order_ids=protective_orders,
        )

    def resume(self, session: SessionKey | tuple[str, str] | str) -> EodState:
        key = SessionKey.from_value(session)
        return self._sessions.get(key, EodState.IDLE)
