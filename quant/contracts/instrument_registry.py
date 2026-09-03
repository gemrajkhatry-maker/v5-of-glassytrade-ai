"""Single InstrumentRegistry — exact-match root → exchange/tick/lot/session.

Unknown roots raise. Prefix matching is forbidden: ``NIFTYNXT50`` must never
resolve as ``NIFTY``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class UnknownInstrumentError(ValueError):
    """Raised when a symbol root is not registered. Never default an exchange."""


@dataclass(frozen=True)
class InstrumentSpec:
    root: str
    exchange: str          # NSE | BSE | MCX
    dhan_exchange: str     # NFO | BFO | MCX | NSE
    segment: str           # NSE_FNO | BSE_FNO | MCX_COMM | NSE
    tick_size: float
    lot_size: int
    strike_interval: float
    freeze_limit: int
    min_oi: int
    session_profile: str   # NSE | MCX  (hours table key)
    is_index: bool = True


def _spec(
    root: str,
    *,
    exchange: str,
    dhan_exchange: str,
    segment: str,
    tick: float,
    lot: int,
    strike: float,
    freeze: int,
    min_oi: int,
    session: str,
    is_index: bool = True,
) -> InstrumentSpec:
    return InstrumentSpec(
        root=root,
        exchange=exchange,
        dhan_exchange=dhan_exchange,
        segment=segment,
        tick_size=tick,
        lot_size=lot,
        strike_interval=strike,
        freeze_limit=freeze,
        min_oi=min_oi,
        session_profile=session,
        is_index=is_index,
    )


_SPECS: dict[str, InstrumentSpec] = {
    spec.root: spec
    for spec in (
        _spec("NIFTY", exchange="NSE", dhan_exchange="NFO", segment="NSE_FNO",
              tick=0.05, lot=65, strike=50, freeze=1800, min_oi=50_000, session="NSE"),
        _spec("BANKNIFTY", exchange="NSE", dhan_exchange="NFO", segment="NSE_FNO",
              tick=0.05, lot=30, strike=100, freeze=900, min_oi=150_000, session="NSE"),
        _spec("FINNIFTY", exchange="NSE", dhan_exchange="NFO", segment="NSE_FNO",
              tick=0.05, lot=60, strike=50, freeze=1800, min_oi=30_000, session="NSE"),
        _spec("MIDCPNIFTY", exchange="NSE", dhan_exchange="NFO", segment="NSE_FNO",
              tick=0.05, lot=120, strike=25, freeze=4200, min_oi=20_000, session="NSE"),
        _spec("SENSEX", exchange="BSE", dhan_exchange="BFO", segment="BSE_FNO",
              tick=0.05, lot=20, strike=100, freeze=1000, min_oi=20_000, session="NSE"),
        _spec("BANKEX", exchange="BSE", dhan_exchange="BFO", segment="BSE_FNO",
              tick=0.05, lot=30, strike=100, freeze=1000, min_oi=20_000, session="NSE"),
        _spec("CRUDEOIL", exchange="MCX", dhan_exchange="MCX", segment="MCX_COMM",
              tick=1.0, lot=100, strike=50, freeze=10000, min_oi=200, session="MCX"),
        _spec("CRUDEOILM", exchange="MCX", dhan_exchange="MCX", segment="MCX_COMM",
              tick=1.0, lot=10, strike=50, freeze=10000, min_oi=200, session="MCX"),
        _spec("NATURALGAS", exchange="MCX", dhan_exchange="MCX", segment="MCX_COMM",
              tick=0.1, lot=1250, strike=5, freeze=100000, min_oi=500, session="MCX"),
        _spec("GOLD", exchange="MCX", dhan_exchange="MCX", segment="MCX_COMM",
              tick=1.0, lot=100, strike=100, freeze=10000, min_oi=0, session="MCX"),
        _spec("GOLDM", exchange="MCX", dhan_exchange="MCX", segment="MCX_COMM",
              tick=1.0, lot=100, strike=100, freeze=10000, min_oi=50, session="MCX"),
        _spec("GOLDPETAL", exchange="MCX", dhan_exchange="MCX", segment="MCX_COMM",
              tick=1.0, lot=1, strike=50, freeze=10000, min_oi=0, session="MCX"),
        _spec("SILVER", exchange="MCX", dhan_exchange="MCX", segment="MCX_COMM",
              tick=1.0, lot=30, strike=500, freeze=10000, min_oi=0, session="MCX"),
        _spec("SILVERM", exchange="MCX", dhan_exchange="MCX", segment="MCX_COMM",
              tick=1.0, lot=5, strike=500, freeze=10000, min_oi=20, session="MCX"),
        _spec("COPPER", exchange="MCX", dhan_exchange="MCX", segment="MCX_COMM",
              tick=0.05, lot=2500, strike=5, freeze=10000, min_oi=0, session="MCX"),
        _spec("ZINC", exchange="MCX", dhan_exchange="MCX", segment="MCX_COMM",
              tick=0.05, lot=5000, strike=5, freeze=10000, min_oi=0, session="MCX"),
        _spec("ALUMINIUM", exchange="MCX", dhan_exchange="MCX", segment="MCX_COMM",
              tick=0.05, lot=5000, strike=5, freeze=10000, min_oi=0, session="MCX"),
        _spec("LEAD", exchange="MCX", dhan_exchange="MCX", segment="MCX_COMM",
              tick=0.05, lot=5000, strike=5, freeze=10000, min_oi=0, session="MCX"),
        _spec("NICKEL", exchange="MCX", dhan_exchange="MCX", segment="MCX_COMM",
              tick=1.0, lot=1500, strike=5, freeze=10000, min_oi=0, session="MCX"),
        _spec("COTTONCANDY", exchange="MCX", dhan_exchange="MCX", segment="MCX_COMM",
              tick=1.0, lot=25, strike=50, freeze=10000, min_oi=0, session="MCX"),
    )
}


_PREFIX_RE = re.compile(r"^(?:NSE|NFO|MCX|BSE|BFO):", re.IGNORECASE)

# Dhan display names that are not the registry root. Longest first.
_DISPLAY_ALIASES: tuple[tuple[str, str], ...] = (
    ("NIFTY MID SELECT", "MIDCPNIFTY"),
    ("NIFTY FIN SERVICE", "FINNIFTY"),
    ("NIFTY BANK", "BANKNIFTY"),
    ("NIFTY 50", "NIFTY"),
    ("BANK NIFTY", "BANKNIFTY"),
)

_OPTION_SPACED = re.compile(r"(?:[\s\-])(?:CALL|PUT)$")
_OPTION_COMPACT = re.compile(r"(?:\d+[-\s]?)(?:CE|PE)$")
_FUT_COMPACT = re.compile(r"(?:FUT(?:URES)?$)|(?:-I$)|(?:-\d{1,2}[A-Z]{3}\d{0,4}$)")


def _clean_symbol(symbol: str) -> str:
    return _PREFIX_RE.sub("", str(symbol or "").strip()).upper()


def is_option_contract(symbol: str) -> bool:
    """True for spaced CALL/PUT, compact CE/PE, and hyphenated -CE/-PE."""
    s = _clean_symbol(symbol)
    if not s:
        return False
    return bool(_OPTION_SPACED.search(s) or _OPTION_COMPACT.search(s) or s.endswith(("-CE", "-PE")))


def is_futures_contract(symbol: str) -> bool:
    """True for broker futures formats: ``FUT``, ``-I``, ``ROOT-19MAR2026``, compact FUT."""
    if is_option_contract(symbol):
        return False
    s = _clean_symbol(symbol)
    if not s:
        return False
    if s.endswith("FUT") or s.endswith("FUTURES"):
        return True
    return bool(_FUT_COMPACT.search(s))


def root_token(symbol: str) -> str:
    """Canonical registry root. Aliases and longest-root, never first-token prefix."""
    clean = _clean_symbol(symbol)
    if not clean:
        return ""
    for alias, root in _DISPLAY_ALIASES:
        if clean == alias or clean.startswith(alias + " ") or clean.startswith(alias + "-"):
            return root
    for u in sorted(_SPECS, key=len, reverse=True):
        if clean == u or (clean.startswith(u) and (len(clean) == len(u) or not clean[len(u)].isalpha())):
            return u
    return re.split(r"[-_\s]+", clean)[0]


class InstrumentRegistry:
    def __init__(self, specs: dict[str, InstrumentSpec] | None = None) -> None:
        self._specs = dict(specs or _SPECS)

    def resolve(self, symbol_or_root: str) -> InstrumentSpec:
        spec = self.try_resolve(symbol_or_root)
        if spec is None:
            root = root_token(symbol_or_root)
            raise UnknownInstrumentError(
                f"Unknown instrument root {root!r} from {symbol_or_root!r}. "
                f"Registered: {sorted(self._specs)}"
            )
        return spec

    def try_resolve(self, symbol_or_root: str) -> InstrumentSpec | None:
        return self._specs.get(root_token(symbol_or_root))

    def specs(self) -> tuple[InstrumentSpec, ...]:
        return tuple(self._specs.values())

    def all_roots(self) -> frozenset[str]:
        return frozenset(self._specs)

    def nse_session_roots(self) -> frozenset[str]:
        return frozenset(s.root for s in self._specs.values() if s.session_profile == "NSE")

    def mcx_roots(self) -> frozenset[str]:
        return frozenset(s.root for s in self._specs.values() if s.exchange == "MCX")


DEFAULT_REGISTRY = InstrumentRegistry()


def get_lot_size(root: str) -> int:
    return DEFAULT_REGISTRY.resolve(root).lot_size


def get_tick_size(root: str) -> float:
    return DEFAULT_REGISTRY.resolve(root).tick_size
