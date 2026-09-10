"""Sole scanner-settings vocabulary. (REF-08)

Centralizes the five scanner settings consumed at the lifespan scan block
(``backend/app/main.py``), the rescan endpoint
(``backend/app/api/routers/health.py``), and — via the settings adapter — the
``QuantCoordinator`` config (``composition_root._create_quant_coordinator``).

``from_settings()`` is the ONLY construction path (D-23): it reads the settings
adapter, which already encapsulates the YAML mode-config branch and the raw env
fallback. Every knob is read defensively through ``getattr`` so a present-but-
falsy value falls back to a class-level default; ``DEFAULT_TOP_N`` is the single
authority for ``SCANNER_TOP_N``.

Parsing mirrors the env branch of
``backend/app/config_models/settings_adapter.py`` exactly (verified
2026-09-03; notably the strikes key has NO ``SCANNER_`` prefix and
underlyings parsing is strip-only — no upper(), no empty-filter).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

DEFAULT_UNDERLYINGS: tuple[str, ...] = (
    "CRUDEOIL",
    "NATURALGAS",
    "GOLDM",
    "SILVERM",
)


def _split_underlyings(raw: Any) -> tuple[str, ...]:
    """Normalize an underlyings value from the settings adapter or a default.

    The settings adapter yields a list of stripped strings; the class default is
    already a tuple; a raw comma string is split strip-only to mirror
    ``SettingsAdapter.SCANNER_UNDERLYINGS`` (no upper(), no empty-filter).
    """
    if isinstance(raw, str):
        return tuple(s.strip() for s in raw.split(","))
    return tuple(str(s).strip() for s in raw)


@dataclass(frozen=True)
class ScannerConfig:
    DEFAULT_TOP_N: ClassVar[int] = 8
    top_n: int = DEFAULT_TOP_N
    underlyings: tuple[str, ...] = field(default_factory=lambda: DEFAULT_UNDERLYINGS)
    option_type: str = ""
    expiry_index: int = 0
    strikes_around_atm: int = 2

    @classmethod
    def from_settings(cls, settings: Any) -> "ScannerConfig":
        """Copy the live settings values (preserves the YAML mode-config branch).

        The settings adapter is the single source of truth for the scanner
        knobs; each value is read with a defensive default so missing or falsy
        settings degrade to the class-level defaults instead of raising.
        """
        top_n = int(getattr(settings, "SCANNER_TOP_N", None) or cls.DEFAULT_TOP_N)
        underlyings = _split_underlyings(
            getattr(settings, "SCANNER_UNDERLYINGS", None) or DEFAULT_UNDERLYINGS
        )
        option_type = getattr(settings, "SCANNER_OPTION_TYPE", "") or ""
        expiry_index = int(getattr(settings, "SCANNER_EXPIRY_INDEX", None) or 0)
        strikes_around_atm = int(getattr(settings, "STRIKES_AROUND_ATM", None) or 2)
        return cls(
            top_n=top_n,
            underlyings=underlyings,
            option_type=option_type,
            expiry_index=expiry_index,
            strikes_around_atm=strikes_around_atm,
        )

    @property
    def preferred_option_type(self) -> str | None:
        """Scanner-facing option filter: empty config means no preference."""
        return self.option_type or None

    def to_scan_kwargs(self, exchange: str) -> dict[str, Any]:
        """Keyword args for ``OptionScannerService.scan_top_n``."""
        return {
            "n": self.top_n,
            "underlyings": list(self.underlyings),
            "preferred_option_type": self.preferred_option_type,
            "exchange": exchange,
            "expiry_index": self.expiry_index,
            "strikes_around_atm": self.strikes_around_atm,
        }
