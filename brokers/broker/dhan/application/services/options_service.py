"""
Options Service - Option chain and expiry operations.
"""

from datetime import datetime
from typing import Dict, List

from brokers.broker.entities import Instrument, OptionChain
from brokers.broker.entities import Option as BrokerOption
from brokers.broker.types import Exchange
from brokers.broker.dhan.domain import (
    DhanError,
    DhanNetworkError,
    OPTIONCHAIN,
    OPTIONCHAIN_EXPIRYLIST,
)
from brokers.broker.dhan.domain.segment_mapping import exchange_to_option_chain_api_segment
from brokers.broker.logging import get_logger
from .base import BaseDhanService

logger = get_logger("dhan.services.options")


class OptionsService(BaseDhanService):
    """Handles option chain and expiry operations."""

    @staticmethod
    def format_option_symbol(
        underlying: str, expiry: datetime, strike: float, option_type: str
    ) -> str:
        """Format a human-readable option symbol."""
        day = expiry.day
        month = expiry.strftime("%b").upper()
        strike_int = int(strike) if strike == int(strike) else strike
        opt_text = "CALL" if option_type.upper() in ("CE", "CALL") else "PUT"
        return f"{underlying} {day} {month} {strike_int} {opt_text}"

    async def get_option_chain_async(
        self, underlying: str, exchange: Exchange, expiry_index: int = 0
    ) -> OptionChain:
        """Async implementation of get_option_chain."""
        await self._ensure_initialized()
        await self._apply_rate_limit("option_chain")

        try:
            security_id = await self._resolve_security_id(
                Instrument(symbol=underlying, exchange=exchange, security_id="")
            )

            if underlying.upper() in self._INDEX_UNDERLYINGS:
                api_segment = "IDX_I"
            else:
                api_segment = exchange_to_option_chain_api_segment(exchange)

            expiry_response = await self._execute_with_cb(
                lambda: self._http_client.post(
                    OPTIONCHAIN_EXPIRYLIST,
                    {"UnderlyingScrip": int(security_id), "UnderlyingSeg": api_segment},
                )
            )

            if expiry_response.status_code not in (200, 201):
                raise DhanNetworkError(
                    message="Failed to get expiry list",
                    details=expiry_response.data,
                )

            expiries = expiry_response.data.get("data", [])
            if isinstance(expiries, dict):
                expiries = expiries.get("data", [])

            if not expiries or expiry_index >= len(expiries):
                raise DhanError(
                    message=f"No expiry found at index {expiry_index}",
                    code="EXPIRY_NOT_FOUND",
                )

            expiry = expiries[expiry_index]

            response = await self._execute_with_cb(
                lambda: self._http_client.post(
                    OPTIONCHAIN,
                    {
                        "UnderlyingScrip": int(security_id),
                        "UnderlyingSeg": api_segment,
                        "Expiry": expiry,
                    },
                )
            )

            if response.status_code not in (200, 201):
                raise DhanNetworkError(
                    message="Failed to get option chain",
                    details=response.data,
                )

            data = response.data.get("data", {})
            if isinstance(data, dict):
                data = data.get("data", data)

            oc_data = data.get("oc", {})

            calls: Dict[float, BrokerOption] = {}
            puts: Dict[float, BrokerOption] = {}
            spot_price = float(data.get("last_price", 0))
            expiry_dt = datetime.strptime(expiry, "%Y-%m-%d") if expiry else None

            for strike_str, opt_data in oc_data.items():
                try:
                    strike = float(strike_str)
                except (ValueError, TypeError):
                    continue

                ce_data = opt_data.get("ce", {}) if isinstance(opt_data, dict) else {}
                pe_data = opt_data.get("pe", {}) if isinstance(opt_data, dict) else {}

                if ce_data and ce_data.get("security_id"):
                    ce_sid = str(ce_data["security_id"])
                    ce_symbol = self.format_option_symbol(
                        underlying, expiry_dt or datetime.now(), strike, "CE"
                    )
                    self._option_symbol_cache[ce_symbol] = ce_sid
                    ce_greeks = ce_data.get("greeks") or {}
                    calls[strike] = BrokerOption(
                        symbol=ce_symbol,
                        security_id=ce_sid,
                        strike=strike,
                        option_type="CE",
                        expiry=expiry_dt or datetime.now(),
                        ltp=float(ce_data.get("last_price", 0)),
                        oi=int(ce_data.get("oi", 0)),
                        volume=int(ce_data.get("volume", 0)),
                        bid=float(ce_data.get("top_bid_price", 0)) if ce_data.get("top_bid_price") else None,
                        ask=float(ce_data.get("top_ask_price", 0)) if ce_data.get("top_ask_price") else None,
                        bid_qty=int(ce_data["top_bid_quantity"]) if ce_data.get("top_bid_quantity") else None,
                        ask_qty=int(ce_data["top_ask_quantity"]) if ce_data.get("top_ask_quantity") else None,
                        prev_oi=int(ce_data["previous_oi"]) if ce_data.get("previous_oi") is not None else None,
                        prev_volume=int(ce_data["previous_volume"]) if ce_data.get("previous_volume") is not None else None,
                        avg_price=float(ce_data["average_price"]) if ce_data.get("average_price") else None,
                        iv=float(ce_data.get("implied_volatility", 0)) if ce_data.get("implied_volatility") else None,
                        delta=float(ce_greeks.get("delta", 0)) if ce_greeks.get("delta") else None,
                        gamma=float(ce_greeks.get("gamma", 0)) if ce_greeks.get("gamma") else None,
                        theta=float(ce_greeks.get("theta", 0)) if ce_greeks.get("theta") else None,
                        vega=float(ce_greeks.get("vega", 0)) if ce_greeks.get("vega") else None,
                        prev_close=float(ce_data.get("previous_close_price", 0)) if ce_data.get("previous_close_price") else None,
                    )

                if pe_data and pe_data.get("security_id"):
                    pe_sid = str(pe_data["security_id"])
                    pe_symbol = self.format_option_symbol(
                        underlying, expiry_dt or datetime.now(), strike, "PE"
                    )
                    self._option_symbol_cache[pe_symbol] = pe_sid
                    pe_greeks = pe_data.get("greeks") or {}
                    puts[strike] = BrokerOption(
                        symbol=pe_symbol,
                        security_id=pe_sid,
                        strike=strike,
                        option_type="PE",
                        expiry=expiry_dt or datetime.now(),
                        ltp=float(pe_data.get("last_price", 0)),
                        oi=int(pe_data.get("oi", 0)),
                        volume=int(pe_data.get("volume", 0)),
                        bid=float(pe_data.get("top_bid_price", 0)) if pe_data.get("top_bid_price") else None,
                        ask=float(pe_data.get("top_ask_price", 0)) if pe_data.get("top_ask_price") else None,
                        bid_qty=int(pe_data["top_bid_quantity"]) if pe_data.get("top_bid_quantity") else None,
                        ask_qty=int(pe_data["top_ask_quantity"]) if pe_data.get("top_ask_quantity") else None,
                        prev_oi=int(pe_data["previous_oi"]) if pe_data.get("previous_oi") is not None else None,
                        prev_volume=int(pe_data["previous_volume"]) if pe_data.get("previous_volume") is not None else None,
                        avg_price=float(pe_data["average_price"]) if pe_data.get("average_price") else None,
                        iv=float(pe_data.get("implied_volatility", 0)) if pe_data.get("implied_volatility") else None,
                        delta=float(pe_greeks.get("delta", 0)) if pe_greeks.get("delta") else None,
                        gamma=float(pe_greeks.get("gamma", 0)) if pe_greeks.get("gamma") else None,
                        theta=float(pe_greeks.get("theta", 0)) if pe_greeks.get("theta") else None,
                        vega=float(pe_greeks.get("vega", 0)) if pe_greeks.get("vega") else None,
                        prev_close=float(pe_data.get("previous_close_price", 0)) if pe_data.get("previous_close_price") else None,
                    )

            underlying_inst = Instrument(
                symbol=underlying, exchange=exchange, security_id=""
            )

            all_strikes = sorted(set(calls.keys()) | set(puts.keys()))
            atm_strike = (
                min(all_strikes, key=lambda s: abs(s - spot_price))
                if all_strikes
                else 0.0
            )
            step_size = (
                all_strikes[1] - all_strikes[0] if len(all_strikes) > 1 else 50.0
            )

            return OptionChain(
                underlying=underlying_inst,
                expiry=datetime.strptime(expiry, "%Y-%m-%d") if expiry else None,
                spot_price=spot_price,
                atm_strike=atm_strike,
                step_size=step_size,
                calls=calls,
                puts=puts,
            )

        except DhanError:
            raise
        except Exception as e:
            self._handle_error(e, f"get_option_chain({underlying})")

    async def get_expiry_list_async(
        self, underlying: str, exchange: Exchange
    ) -> List[datetime]:
        """Async implementation of get_expiry_list."""
        await self._ensure_initialized()
        await self._apply_rate_limit("option_chain")

        try:
            security_id = await self._resolve_security_id(
                Instrument(symbol=underlying, exchange=exchange, security_id="")
            )
            if underlying.upper() in self._INDEX_UNDERLYINGS:
                api_segment = "IDX_I"
            else:
                api_segment = exchange_to_option_chain_api_segment(exchange)

            response = await self._execute_with_cb(
                lambda: self._http_client.post(
                    OPTIONCHAIN_EXPIRYLIST,
                    json={
                        "UnderlyingScrip": int(security_id),
                        "UnderlyingSeg": api_segment,
                    },
                )
            )

            if response.status_code not in (200, 201):
                raise DhanNetworkError(
                    message="Failed to get expiry list",
                    code=str(response.status_code),
                    details=response.data,
                )

            data = response.data.get("data", [])
            if isinstance(data, dict):
                data = data.get("data", data.get("expiries", []))
            expiries = []
            for exp_str in (data or []):
                try:
                    exp_dt = datetime.strptime(str(exp_str).strip(), "%Y-%m-%d")
                    expiries.append(exp_dt)
                except ValueError:
                    continue

            return expiries

        except DhanError:
            raise
        except Exception as e:
            self._handle_error(e, f"get_expiry_list({underlying})")
