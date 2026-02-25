"""Dhan live broker adapter — NOT YET ACTIVATED.

Activate only after 10+ day forward test passes acceptance criteria.
Set TRADING_MODE=LIVE in .env to switch from PaperBrokerAdapter.

Implementation checklist (when ready to activate):
- [ ] Map signal.symbol to Dhan security_id (requires symbol master lookup)
- [ ] Map signal.type (BUY/SELL) to Dhan transaction_type (BUY/SELL)
- [ ] Use product_type=MIS for intraday options
- [ ] Use order_type=MARKET for immediate entry
- [ ] Track order_id for subsequent cancel/modify
- [ ] Poll dhan.get_order_by_id() to confirm fill
- [ ] Handle REJECTED orders (margin, circuit limits)
- [ ] Cancel SL/TP bracket orders on position close
"""
from __future__ import annotations
import logging
from app.domain.ports.broker import BrokerPort

logger = logging.getLogger(__name__)


class DhanBrokerAdapter(BrokerPort):
    """Live order execution via DhanHQ dhanhq library.

    IMPORTANT: This adapter raises NotImplementedError until fully implemented
    and forward-test acceptance criteria are met.
    """

    def __init__(self, client_id: str, access_token: str) -> None:
        self._client_id = client_id
        self._access_token = access_token
        logger.warning(
            "DhanBrokerAdapter initialized — LIVE mode. "
            "Ensure forward test acceptance criteria met before deploying."
        )

    def execute_order(self, signal, portfolio, symbol: str):
        raise NotImplementedError(
            "DhanBrokerAdapter.execute_order() not yet implemented.\n"
            "Complete the checklist in the module docstring first.\n"
            "Current TRADING_MODE=LIVE requires implementation before use."
        )
