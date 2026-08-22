"""Architecture fitness checks (CI gates) — protect the dependency direction.

Cheap static scans (no import-linter dependency): they assert the structural
rules that keep the domain broker-free and mode forking confined to the
composition root. Run as part of the trading test suite.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[3]
DOMAIN = ROOT / "domain" / "src" / "tradex_domain"
BROKERS = ROOT / "brokers" / "src" / "tradex_brokers"
TRADING = ROOT / "trading" / "src" / "tradex_trading"


def _texts(root: pathlib.Path) -> list[tuple[str, str]]:
    return [(str(p), p.read_text()) for p in sorted(root.rglob("*.py"))]


def test_domain_never_imports_brokers_or_trading() -> None:
    offenders = [
        path
        for path, text in _texts(DOMAIN)
        if "tradex_brokers" in text or "tradex_trading" in text
    ]
    assert offenders == [], f"domain must not import brokers/trading: {offenders}"


def test_brokers_never_import_trading() -> None:
    offenders = [
        path for path, text in _texts(BROKERS) if "tradex_trading" in text
    ]
    assert offenders == [], f"brokers must not import trading: {offenders}"


def test_strategy_never_imports_brokers() -> None:
    offenders = [
        path
        for path, text in _texts(TRADING / "strategy")
        if "tradex_brokers" in text
    ]
    assert offenders == [], f"strategies must not import brokers: {offenders}"


def test_mode_branches_confined_to_composition_root() -> None:
    pattern = re.compile(r"\.mode\s*==")
    offenders = [
        path
        for path, text in _texts(TRADING)
        if "runtime/startup.py" not in path and pattern.search(text)
    ]
    assert (
        offenders == []
    ), f"mode branches belong only in runtime/startup.py: {offenders}"
