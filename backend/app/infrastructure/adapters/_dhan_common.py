"""Shared plumbing for the two Dhan adapters (market data + broker).

Importing this module bootstraps sys.path so the repository-root ``brokers``
package is importable from backend code.
"""

from __future__ import annotations

import logging
import pathlib
import re
import sys

# Discovers the root by walking up until we find the brokers/ directory.
_here = pathlib.Path(__file__).resolve()
for _ancestor in _here.parents:
    if (_ancestor / "brokers").is_dir():
        if str(_ancestor) not in sys.path:
            sys.path.insert(0, str(_ancestor))
        break

logger = logging.getLogger(__name__)


def _exchange_enum(exchange_str: str | None):
    """Convert exchange string to brokers Exchange enum."""
    from brokers.broker.types import Exchange

    mapping = {
        "NSE": Exchange.NSE,
        "NFO": Exchange.NFO,
        "MCX": Exchange.MCX,
        "BSE": Exchange.NSE,  # fallback
        "INDEX": Exchange.NSE,
    }
    result = mapping.get((exchange_str or "NSE").upper())
    if result is None:
        logger.warning("Unknown exchange '%s', defaulting to NSE", exchange_str)
        result = Exchange.NSE
    return result


def classify_symbol(symbol: str) -> tuple[bool, bool, bool, bool]:
    """Classify a symbol into ``(is_option, is_call, is_put, is_mcx)``.

    Uses ANCHORED detection — a trailing CALL/PUT word, or a digit-suffixed
    CE/PE — so an underlying name containing CALL/PUT/CE/PE as a substring
    can never mislabel the contract or misroute the exchange segment.
    """
    from quant.contracts.exchange_config import ExchangeConfig

    sym_upper = symbol.upper()
    is_call = sym_upper.endswith("CALL") or bool(re.search(r"\d+\s*CE$", sym_upper))
    is_put = sym_upper.endswith("PUT") or bool(re.search(r"\d+\s*PE$", sym_upper))
    is_option = is_call or is_put
    is_mcx = ExchangeConfig.for_exchange("MCX").is_underlying(sym_upper)
    return is_option, is_call, is_put, is_mcx
