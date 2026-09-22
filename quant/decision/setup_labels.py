"""Canonical SetupType labels for the money path.

Display labels on Signal.model_label stay human-readable for the UI. Everything
that routes exits, OMS setup mapping, or Gate-3 approval goes through
canonical_setup_type() so VA_Fade and VA_FADE are the same playbook and an
empty key never becomes Triple-A.
"""

from __future__ import annotations

from typing import Literal

# Matches quant.decision.setup_state.SetupType plus legacy Gate-3 paths.
CanonicalSetup = Literal[
    "TRIPLE_A",
    "SECOND_DRIVE",
    "LVN_SNIPER",
    "VA_FADE",
    "INITIATIVE",
    "SQUEEZE",
    "",
]

_KEY_TO_LABEL: dict[str, str] = {
    "TRIPLE_A": "Triple-A",
    "SECOND_DRIVE": "Second_Drive",
    "LVN_SNIPER": "LVN_Sniper",
    "VA_FADE": "VA_Fade",
    "INITIATIVE": "Initiative",
    "SQUEEZE": "Squeeze",
}

_LABEL_TO_KEY: dict[str, str] = {
    "TRIPLE-A": "TRIPLE_A",
    "TRIPLE_A": "TRIPLE_A",
    "SECOND_DRIVE": "SECOND_DRIVE",
    "SECOND-DRIVE": "SECOND_DRIVE",
    "LVN_SNIPER": "LVN_SNIPER",
    "LVN-SNIPER": "LVN_SNIPER",
    "VA_FADE": "VA_FADE",
    "VA-FADE": "VA_FADE",
    "INITIATIVE": "INITIATIVE",
    "SQUEEZE": "SQUEEZE",
}

_TERMINAL_TP: frozenset[str] = frozenset({"VA_FADE"})


def label_from_setup_key(setup_key: str) -> str:
    """Map a Gate-3 setup_key to Signal.model_label. Empty key → empty label."""
    key = str(setup_key or "").strip().upper().replace("-", "_").replace(" ", "_")
    return _KEY_TO_LABEL.get(key, "")


def canonical_setup_type(label_or_key: str) -> str:
    """Normalize display label or setup_key to a SetupType-like key, or ''."""
    raw = str(label_or_key or "").strip()
    if not raw:
        return ""
    normalized = raw.upper().replace("-", "_").replace(" ", "_")
    if normalized in _KEY_TO_LABEL:
        return normalized
    return _LABEL_TO_KEY.get(normalized, "")


def is_terminal_setup(label_or_key: str) -> bool:
    """True when the playbook exits full at first TP (mean-reversion fade)."""
    return canonical_setup_type(label_or_key) in _TERMINAL_TP
