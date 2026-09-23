"""Shared plumbing for the two Dhan adapters (market data + broker).

Importing this module bootstraps sys.path so the repository-root ``brokers``
package is importable from backend code.
"""

from __future__ import annotations

import logging
import pathlib
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
    """Convert exchange string to brokers Exchange enum.

    Re-audit (D-EXCH-07 sibling): BSE used to silently fall back to
    Exchange.NSE and BFO was not mapped at all — a SENSEX/BANKEX *cash*
    exchange hint would route as plain NSE and a BFO hint would hit the
    "unknown exchange" warning path. Both are now first-class.
    """
    from brokers.broker.types import Exchange

    mapping = {
        "NSE": Exchange.NSE,
        "NFO": Exchange.NFO,
        "MCX": Exchange.MCX,
        "BSE": Exchange.BSE,
        "BFO": Exchange.BFO,
        "INDEX": Exchange.NSE,
    }
    result = mapping.get((exchange_str or "NSE").upper())
    if result is None:
        logger.warning("Unknown exchange '%s', defaulting to NSE", exchange_str)
        result = Exchange.NSE
    return result


def classify_symbol(symbol: str):
    """Classify a symbol into ``(is_option, is_call, is_put, dhan_exchange)``.

    Uses ANCHORED detection — a trailing CALL/PUT word, or a digit-suffixed
    CE/PE — so an underlying name containing CALL/PUT/CE/PE as a substring
    can never mislabel the contract or misroute the exchange segment.

    ``dhan_exchange`` (re-audit, D-EXCH-07 sibling) used to be a binary
    ``is_mcx`` bool, forcing every non-MCX option onto NFO — structurally
    unable to route a SENSEX/BANKEX order to BFO. Delegates to
    ``DhanExchangeResolver`` (already BSE/BFO-aware) instead of
    re-implementing a narrower binary classifier here.
    """
    from quant.contracts.instrument_registry import DEFAULT_REGISTRY, is_option_contract
    from quant.contracts.vocabulary import is_call_symbol, is_put_symbol
    from brokers.broker.dhan.application.exchange_resolver import DhanExchangeResolver

    is_option = is_option_contract(symbol)
    is_call = is_call_symbol(symbol)
    is_put = is_put_symbol(symbol)
    dhan_exchange = DhanExchangeResolver.resolve(symbol.upper()).exchange
    spec = DEFAULT_REGISTRY.try_resolve(symbol)
    if spec is not None:
        from brokers.broker.types import Exchange
        mapped = {
            "NFO": Exchange.NFO,
            "BFO": Exchange.BFO,
            "MCX": Exchange.MCX,
            "NSE": Exchange.NSE,
        }.get(spec.dhan_exchange)
        if mapped is not None:
            dhan_exchange = mapped
    return is_option, is_call, is_put, dhan_exchange
