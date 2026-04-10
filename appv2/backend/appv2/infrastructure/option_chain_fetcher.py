"""Option Chain Fetcher — fetches and structures option chain data via BrokerGateway.

Uses the same gateway pattern as the original backend for broker communication.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from datetime import datetime

# Add project root for brokers import
_project_root = Path(__file__).resolve().parents[4]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from appv2.domain.models.option import OptionChain, OptionContract
from appv2.domain.services.blackscholes import implied_volatility

logger = logging.getLogger(__name__)


class OptionChainFetcher:
    """Fetches and processes option chain data via BrokerGateway."""

    def __init__(self, access_token: str = "", client_id: str = ""):
        self._access_token = access_token
        self._client_id = client_id
        self._gateway = None

    def _ensure_gateway(self):
        if self._gateway is not None:
            return
        try:
            from brokers.gateway import BrokerGateway
            from shared.entities.models import Exchange

            if self._access_token and self._client_id:
                self._gateway = BrokerGateway.dhan(
                    client_id=self._client_id,
                    access_token=self._access_token,
                )
            else:
                self._gateway = BrokerGateway.dhan()  # Loads from env

            self._Exchange = Exchange
        except Exception as e:
            logger.error("Failed to initialize BrokerGateway: %s", e)
            self._gateway = None

    async def fetch_chain(
        self,
        underlying: str,
        expiry: str = "",
        risk_free_rate: float = 0.065,
    ) -> OptionChain | None:
        """Fetch full option chain for an underlying + expiry.

        Args:
            underlying: e.g., "NIFTY", "BANKNIFTY"
            expiry: e.g., "2024-03-20" (empty = nearest)
            risk_free_rate: Risk-free rate for IV computation

        Returns:
            OptionChain object or None
        """
        self._ensure_gateway()
        if not self._gateway:
            logger.warning("Gateway unavailable — cannot fetch option chain")
            return None

        try:
            # Use NFO exchange for index options
            chain = self._gateway.get_option_chain(underlying, self._Exchange.NFO)

            spot_price = chain.spot_price
            expiry_date = str(chain.expiry) if chain.expiry else ""
            atm_strike = chain.atm_strike

            # Build option contracts from calls and puts
            options = []

            # Process CE (calls)
            if hasattr(chain, 'calls') and chain.calls:
                for call in chain.calls:
                    contract = self._build_contract(
                        underlying=underlying,
                        strike=call.strike_price if hasattr(call, 'strike_price') else call.get('strike_price', 0),
                        option_type="CE",
                        ltp=call.ltp if hasattr(call, 'ltp') else call.get('ltp', 0),
                        oi=call.oi if hasattr(call, 'oi') else call.get('oi', 0),
                        iv=call.iv if hasattr(call, 'iv') else call.get('iv', 0),
                        delta=call.delta if hasattr(call, 'delta') else call.get('delta', 0),
                        gamma=call.gamma if hasattr(call, 'gamma') else call.get('gamma', 0),
                        theta=call.theta if hasattr(call, 'theta') else call.get('theta', 0),
                        vega=call.vega if hasattr(call, 'vega') else call.get('vega', 0),
                        bid=call.bid if hasattr(call, 'bid') else call.get('bid', 0),
                        ask=call.ask if hasattr(call, 'ask') else call.get('ask', 0),
                        volume=call.volume if hasattr(call, 'volume') else call.get('volume', 0),
                        expiry_date=expiry_date,
                    )
                    options.append(contract)

            # Process PE (puts)
            if hasattr(chain, 'puts') and chain.puts:
                for put in chain.puts:
                    contract = self._build_contract(
                        underlying=underlying,
                        strike=put.strike_price if hasattr(put, 'strike_price') else put.get('strike_price', 0),
                        option_type="PE",
                        ltp=put.ltp if hasattr(put, 'ltp') else put.get('ltp', 0),
                        oi=put.oi if hasattr(put, 'oi') else put.get('oi', 0),
                        iv=put.iv if hasattr(put, 'iv') else put.get('iv', 0),
                        delta=put.delta if hasattr(put, 'delta') else put.get('delta', 0),
                        gamma=put.gamma if hasattr(put, 'gamma') else put.get('gamma', 0),
                        theta=put.theta if hasattr(put, 'theta') else put.get('theta', 0),
                        vega=put.vega if hasattr(put, 'vega') else put.get('vega', 0),
                        bid=put.bid if hasattr(put, 'bid') else put.get('bid', 0),
                        ask=put.ask if hasattr(put, 'ask') else put.get('ask', 0),
                        volume=put.volume if hasattr(put, 'volume') else put.get('volume', 0),
                        expiry_date=expiry_date,
                    )
                    options.append(contract)

            return OptionChain(
                underlying=underlying,
                expiry_date=expiry_date,
                spot_price=spot_price,
                options=options,
            )

        except Exception as e:
            logger.error("Option chain fetch error for %s: %s", underlying, e)
            return None

    def _build_contract(
        self, underlying, strike, option_type, ltp, oi, iv, delta, gamma,
        theta, vega, bid, ask, volume, expiry_date,
    ) -> OptionContract:
        """Build an OptionContract from raw data."""
        strike = float(strike) if strike else 0
        ltp = float(ltp) if ltp else 0
        oi = float(oi) if oi else 0
        iv = float(iv) if iv else 0
        volume = float(volume) if volume else 0

        # Compute IV if not provided
        if iv == 0 and ltp > 0:
            spot = float(oi) if oi > 0 else ltp  # Fallback
            days = self._days_to_expiry(expiry_date)
            T = days / 365.0
            if T > 0 and strike > 0:
                try:
                    iv = implied_volatility(ltp, ltp, strike, T, 0.065, option_type)
                except Exception:
                    iv = 0

        lot_size = 50  # Default NIFTY
        if "BANKNIFTY" in underlying.upper():
            lot_size = 25
        elif "CRUDEOIL" in underlying.upper():
            lot_size = 100

        return OptionContract(
            symbol=f"{underlying} {expiry_date[:10]} {int(strike)} {option_type}",
            underlying=underlying,
            strike_price=strike,
            expiry_date=expiry_date[:10] if expiry_date else "",
            option_type=option_type,
            lot_size=lot_size,
            ltp=ltp,
            volume=volume,
            oi=oi,
            bid=float(bid) if bid else 0,
            ask=float(ask) if ask else 0,
            delta=float(delta) if delta else 0,
            gamma=float(gamma) if gamma else 0,
            theta=float(theta) if theta else 0,
            vega=float(vega) if vega else 0,
            iv=iv,
        )

    @staticmethod
    def _days_to_expiry(expiry_str: str) -> float:
        """Calculate days to expiry from date string."""
        try:
            expiry_date = datetime.strptime(expiry_str[:10], "%Y-%m-%d").date()
            today = datetime.now().date()
            delta = expiry_date - today
            return max(0, delta.days)
        except (ValueError, TypeError):
            return 0

    def close(self) -> None:
        """Close gateway connection."""
        if self._gateway:
            try:
                self._gateway.close()
            except Exception:
                pass
            self._gateway = None
