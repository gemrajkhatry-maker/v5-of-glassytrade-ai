"""Shared instrument-loading and resolution utilities for broker adapters.

This module is the single home for broker-side instrument utilities: loading
master instrument files (CSV or JSON), parsing master rows into typed domain
``Instrument`` objects, deriving future/option chains from a loaded master,
and resolving provider keys through the domain ``InstrumentRegistry``.

The authoritative registry and instrument types live in the domain layer
(``tradex_domain.wire`` / ``tradex_domain.instruments``); this module only
delegates to them and never re-implements resolution.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from tradex_domain import InstrumentNotFoundError, SDKError
from tradex_domain.instruments import Equity, Future, Index, Instrument, Option
from tradex_domain.options import OptionChain
from tradex_domain.value_objects import InstrumentId, Price
from tradex_domain.wire import InstrumentRegistry

log = logging.getLogger(__name__)


def as_decimal(value: str | float | int) -> Decimal:
    """Convert a value to ``Decimal`` safely.

    Handles strings with commas, currency symbols, and whitespace.

    Parameters
    ----------
    value:
        The value to convert.

    Returns
    -------
    Decimal
        The numeric value as a ``Decimal``.

    Raises
    ------
    SDKError
        If the value cannot be converted.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("₹", "").replace("$", "")
        if not cleaned:
            return Decimal("0")
        try:
            return Decimal(cleaned)
        except InvalidOperation as exc:
            raise SDKError(f"Cannot convert {value!r} to Decimal") from exc
    raise SDKError(f"Cannot convert {type(value).__name__} to Decimal")


def as_price(value: object, default: str = "0") -> Price:
    """Convert a value to ``Price`` safely."""
    if value is None or value == "":
        return Price(value=Decimal(default))
    return Price(value=as_decimal(str(value)))


def parse_date(value: object) -> date | None:
    """Parse a date from various formats."""
    if value is None or value == "":
        return None
    text = str(value)
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_iso_date(value: str) -> date:
    """Strict ISO date parse; raises ``ValueError`` on malformed input."""
    return date.fromisoformat(value.strip()[:10])


def _coerce_date(value: date | str | None) -> date | None:
    """Coerce a date-or-string expiry to a date (None when malformed)."""
    if value is None or isinstance(value, date):
        return value
    try:
        return _parse_iso_date(str(value))
    except ValueError:
        return None


#: NSE/BSE cash equities trade on a uniform ₹0.05 tick. Dhan's master
#: ``SEM_TICK_SIZE`` for the cash segment carries junk values (RELIANCE=10.0,
#: GOLDSTAR=5.0, bonds=1.0) that are not the exchange tick, so cash equities
#: always use the exchange rule instead of the master column.
_CASH_EQUITY_TICK = Decimal("0.05")


def _coerce_tick_size(value: object) -> Decimal | None:
    """Parse a master tick-size column to ``Decimal``; ``None`` when absent/invalid.

    The Dhan master's ``SEM_TICK_SIZE`` is a string (e.g. ``"0.05"``); some
    rows are empty or malformed. Return ``None`` for those so callers fall
    back to the exchange default instead of bucketing on a bogus tick.
    """
    if value in (None, ""):
        return None
    try:
        tick = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return tick if tick > 0 else None


def _effective_tick(instrument: Instrument, raw: object) -> Decimal | None:
    """Master tick for *instrument*, sanitized for cash equities.

    Derivatives keep whatever the master says (real per-contract ticks); NSE/
    BSE cash equities are forced to the exchange rule ``0.05`` because Dhan's
    cash-segment ``SEM_TICK_SIZE`` is unreliable (RELIANCE=10.0, GOLDSTAR=5.0,
    bonds=1.0 — none are the actual tick).
    """
    tick = _coerce_tick_size(raw)
    if tick is None:
        return None
    from tradex_domain.enums import AssetClass

    if instrument.asset_class is AssetClass.EQUITY:
        return _CASH_EQUITY_TICK
    return tick


def build_instrument_from_row(row: Mapping[str, Any]) -> Instrument:
    """Build the typed domain Instrument for a normalized master row.

    Prefers derivatives structure (right + expiry + strike → ``Option``;
    ``FUT*``/``FUT`` right + expiry → ``Future``) and falls back to
    ``Equity`` for plain rows or rows whose structure fails to parse.

    When the row carries a tick size (Dhan master ``SEM_TICK_SIZE``) it is
    stamped onto the ``Instrument`` so per-contract tick math (NSE equities
    0.05, other contracts whatever the exchange says) flows with the
    instrument into analytics instead of a hardcoded default.
    """
    exchange = str(row.get("exchange", "NSE")).strip().upper()
    symbol = str(row.get("symbol", "")).strip().upper()
    underlying = str(row.get("underlying") or "").strip()
    if not underlying:
        # Dhan symbols are dash-delimited (SILVER-04Sep2026-FUT); Upstox are
        # space-delimited (SILVER 226000 PE 26 MAY 27). Split on whichever the
        # symbol uses so the root is never the full trading symbol.
        underlying = symbol.split("-", 1)[0] if "-" in symbol else symbol.split(" ", 1)[0]
    right = str(row.get("right") or "").strip().upper() or None
    instrument_type = str(row.get("instrument_type") or "").strip().upper()
    expiry_text = str(row.get("expiry") or "").strip()
    strike_raw = row.get("strike")
    if right in ("CE", "PE") and expiry_text and strike_raw not in (None, ""):
        try:
            expiry = _parse_iso_date(expiry_text)
            strike = Decimal(str(strike_raw))
            instrument: Instrument = Option.of(exchange, underlying, expiry, strike, right)
        except (ValueError, InvalidOperation):
            instrument = Equity.of(exchange, symbol)
    elif (instrument_type.startswith("FUT") or right == "FUT") and expiry_text:
        try:
            instrument = Future.of(exchange, underlying, _parse_iso_date(expiry_text))
        except ValueError:
            instrument = Equity.of(exchange, symbol)
    else:
        instrument = Equity.of(exchange, symbol)
    tick = _effective_tick(instrument, row.get("tick_size"))
    if tick is not None:
        instrument = replace(instrument, tick_size=tick)
    return instrument


def instrument_from_id(instrument_id: InstrumentId) -> Instrument:
    """Build a domain Instrument from an InstrumentId."""
    if instrument_id.right in {"CE", "PE"} and instrument_id.expiry is not None:
        if instrument_id.strike is None:
            raise ValueError(f"option id has no strike: {instrument_id}")
        return Option.of(
            instrument_id.exchange,
            instrument_id.underlying,
            instrument_id.expiry,
            instrument_id.strike,
            instrument_id.right,
        )
    if instrument_id.right == "FUT" and instrument_id.expiry is not None:
        return Future.of(instrument_id.exchange, instrument_id.underlying, instrument_id.expiry)
    if instrument_id.exchange == "IDX":
        return Index.of(instrument_id.exchange, instrument_id.underlying)
    return Equity.of(instrument_id.exchange, instrument_id.underlying)


def provider_key(registry: InstrumentRegistry, instrument_id: InstrumentId) -> str:
    """Get provider key for an instrument, raising if not found."""
    key = registry.provider_key(instrument_id)
    if key is None:
        raise InstrumentNotFoundError(f"no provider key for {instrument_id}")
    return key


def instrument_from_registry(
    registry: InstrumentRegistry, instrument_id: InstrumentId
) -> Instrument:
    """Master-backed Instrument for *instrument_id*, applying contract metadata.

    ``instrument_from_id`` rebuilds a bare instrument from the id alone; the
    registry additionally holds contract metadata parsed from the exchange
    master (``SEM_TICK_SIZE`` via ``_extra_row_meta``). Applying it keeps
    per-contract tick math on the instrument that flows into live quotes and
    analytics — without it every contract falls back to a hardcoded tick.
    """
    instrument = instrument_from_id(instrument_id)
    tick = _effective_tick(
        instrument, registry.meta(instrument_id).get("tick_size")
    )
    if tick is not None:
        instrument = replace(instrument, tick_size=tick)
    return instrument


def resolve_instrument(
    registry: InstrumentRegistry,
    native_key: object,
) -> Instrument:
    """Resolve a provider-native key to a domain Instrument."""
    key = str(native_key)
    instrument_id = registry.resolve(key)
    if instrument_id is None:
        raise InstrumentNotFoundError(f"unknown provider instrument key: {key!r}")
    return instrument_from_registry(registry, instrument_id)


def _underlying_matches(inst: Instrument, underlying: Instrument) -> bool:
    """True when *inst* is a derivative on the same underlying *and* product.

    The underlying root must match; the exchange must match too, except when
    the caller passes an index (``IDX``) underlying — index options/futures
    live on product exchanges (NFO/BFO) so an index underlying spans them.
    Scoping by exchange keeps e.g. ``NSE_COM`` SILVER futures out of an MCX
    SILVER chain.
    """
    inst_id = inst.instrument_id
    if inst_id.underlying != underlying.instrument_id.underlying:
        return False
    if underlying.instrument_id.exchange == "IDX":
        return True
    return inst_id.exchange == underlying.instrument_id.exchange


def future_chain_from_master(
    instruments: Iterable[Instrument], underlying: Instrument
) -> list[Instrument]:
    """Future contracts on *underlying* derived from a loaded instrument master."""
    from tradex_domain.enums import AssetClass

    matches = [
        inst
        for inst in instruments
        if inst.asset_class is AssetClass.FUTURE and _underlying_matches(inst, underlying)
    ]
    matches.sort(key=lambda inst: inst.instrument_id.expiry or date.max)
    return matches


def option_chain_from_master(
    instruments: Iterable[Instrument],
    underlying: Instrument,
    expiry: date | str | None = None,
) -> OptionChain:
    """Option chain for *underlying* derived from a loaded instrument master.

    Groups loaded ``Option`` instruments by expiry and strike, pairing the CE
    and PE legs at each strike. Serves exchanges without a REST chain endpoint
    (MCX) and acts as an offline fallback when the transport is unavailable.
    """
    from tradex_domain.options import Expiry, OptionPair

    requested = _coerce_date(expiry)
    options = [
        inst
        for inst in instruments
        if isinstance(inst, Option)
        and _underlying_matches(inst, underlying)
        and (requested is None or inst.instrument_id.expiry == requested)
    ]
    by_expiry: dict[date, dict[Decimal, dict[str, Option]]] = {}
    for inst in options:
        iid = inst.instrument_id
        if iid.expiry is None or iid.strike is None or iid.right not in ("CE", "PE"):
            continue
        by_expiry.setdefault(iid.expiry, {}).setdefault(iid.strike, {})[iid.right] = inst
    expiries: list[Expiry] = []
    for expiry_date in sorted(by_expiry):
        pairs: list[OptionPair] = []
        for strike in sorted(by_expiry[expiry_date]):
            ce = by_expiry[expiry_date][strike].get("CE")
            pe = by_expiry[expiry_date][strike].get("PE")
            if ce is None or pe is None:
                continue
            pairs.append(OptionPair(call=ce, put=pe, strike=Price(value=strike)))
        if pairs:
            expiries.append(
                Expiry(underlying=underlying, expiry_date=expiry_date, pairs=tuple(pairs))
            )
    return OptionChain(underlying=underlying, _expiries=tuple(expiries))


__all__ = [
    "as_decimal",
    "as_price",
    "build_instrument_from_row",
    "future_chain_from_master",
    "instrument_from_id",
    "instrument_from_registry",
    "option_chain_from_master",
    "parse_date",
    "provider_key",
    "resolve_instrument",
]
