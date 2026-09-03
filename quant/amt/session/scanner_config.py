"""Sole scanner-settings vocabulary. (REF-08)

Centralizes the five scanner settings consumed at the lifespan scan block
(``backend/app/main.py``), the rescan endpoint
(``backend/app/api/routers/health.py``), and — via the settings adapter — the
``QuantCoordinator`` config (``composition_root._create_quant_coordinator``).

Defaults and parsing mirror the env branch of
``backend/app/config_models/settings_adapter.py`` exactly (verified
2026-09-03; notably the strikes key has NO ``SCANNER_`` prefix and
underlyings parsing is strip-only — no upper(), no empty-filter).
``from_settings()`` exists so call sites keep the YAML mode-config branch of
the settings adapter (behavior-identical delegation); ``from_env()`` owns the
raw env defaults and is pinned by contract tests.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


def _parse_underlyings(raw: str) -> tuple[str, ...]:
    # Mirrors SettingsAdapter.SCANNER_UNDERLYINGS env branch: strip-only.
    return tuple(s.strip() for s in raw.split(","))


@dataclass(frozen=True)
class ScannerConfig:
    top_n: int = 4
    underlyings: tuple[str, ...] = field(
        default_factory=lambda: ("CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM")
    )
    option_type: str = ""
    expiry_index: int = 0
    strikes_around_atm: int = 2

    @classmethod
    def from_env(cls) -> "ScannerConfig":
        """Read scanner env with the legacy settings-adapter defaults."""
        return cls(
            top_n=int(os.getenv("SCANNER_TOP_N", "4")),
            underlyings=_parse_underlyings(
                os.getenv(
                    "SCANNER_UNDERLYINGS", "CRUDEOIL,NATURALGAS,GOLDM,SILVERM"
                )
            ),
            option_type=os.getenv("SCANNER_OPTION_TYPE", ""),
            expiry_index=int(os.getenv("SCANNER_EXPIRY_INDEX", "0")),
            strikes_around_atm=int(os.getenv("STRIKES_AROUND_ATM", "2")),
        )

    @classmethod
    def from_settings(cls, settings: Any) -> "ScannerConfig":
        """Copy the live settings values (preserves the YAML mode-config branch)."""
        return cls(
            top_n=int(settings.SCANNER_TOP_N),
            underlyings=tuple(settings.SCANNER_UNDERLYINGS or ()),
            option_type=settings.SCANNER_OPTION_TYPE,
            expiry_index=int(settings.SCANNER_EXPIRY_INDEX),
            strikes_around_atm=int(settings.STRIKES_AROUND_ATM),
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
