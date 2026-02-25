"""
Historical Data Service - Historical OHLCV data operations.
"""

from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from brokers.broker.entities import Instrument, BulkHistoricalResult
from brokers.broker.types import Exchange
from brokers.broker.dhan.domain import (
    DhanError,
    DhanNetworkError,
    DhanHistoricalDataError,
    HISTORICAL_MAX_DAYS,
    CHARTS_HISTORICAL,
    CHARTS_INTRADAY,
    CHARTS_ROLLING_OPTION,
)
from brokers.broker.dhan.domain.segment_mapping import (
    exchange_to_segment_name,
    resolve_dhan_instrument_type,
)
from brokers.broker.logging import get_logger
from .base import BaseDhanService

logger = get_logger("dhan.services.historical")


class HistoricalService(BaseDhanService):
    """Handles historical OHLCV data operations."""

    async def get_historical_async(
        self,
        instrument: Instrument,
        from_date: datetime,
        to_date: datetime,
        interval: str,
        include_oi: bool = False,
    ) -> pd.DataFrame:
        """Async implementation of get_historical. Auto-batches ranges > 90 days."""
        await self._ensure_initialized()

        if from_date > to_date:
            raise DhanHistoricalDataError(
                message=f"Invalid date range: from_date ({from_date.strftime('%Y-%m-%d')}) "
                f"cannot be after to_date ({to_date.strftime('%Y-%m-%d')})",
                code="INVALID_DATE_RANGE",
                details={
                    "from_date": from_date.strftime("%Y-%m-%d"),
                    "to_date": to_date.strftime("%Y-%m-%d"),
                },
            )

        date_diff = (to_date - from_date).days

        if date_diff <= HISTORICAL_MAX_DAYS:
            return await self._fetch_historical_batch(
                instrument, interval, from_date, to_date, include_oi
            )

        batches = self._split_date_range(from_date, to_date, HISTORICAL_MAX_DAYS)
        all_dfs: List[pd.DataFrame] = []
        for batch_from, batch_to in batches:
            df = await self._fetch_historical_batch(
                instrument, interval, batch_from, batch_to, include_oi
            )
            if not df.empty:
                all_dfs.append(df)

        if not all_dfs:
            return pd.DataFrame()

        merged = pd.concat(all_dfs, ignore_index=True)
        if "timestamp" in merged.columns:
            merged = merged.drop_duplicates(subset=["timestamp"], keep="first")
            merged = merged.sort_values("timestamp").reset_index(drop=True)
        return merged

    def _split_date_range(
        self, from_date: datetime, to_date: datetime, max_days: int
    ) -> List[Tuple[datetime, datetime]]:
        """Split a date range into batches of max_days each."""
        batches: List[Tuple[datetime, datetime]] = []
        current_from = from_date

        while current_from <= to_date:
            current_to = min(current_from + timedelta(days=max_days - 1), to_date)
            batches.append((current_from, current_to))
            current_from = current_to + timedelta(days=1)

        return batches

    async def _fetch_historical_batch(
        self,
        instrument: Instrument,
        interval: str,
        from_date: datetime,
        to_date: datetime,
        include_oi: bool = False,
    ) -> pd.DataFrame:
        """Fetch a single batch of historical data (max HISTORICAL_MAX_DAYS)."""
        await self._apply_rate_limit("historical")

        try:
            security_id = await self._resolve_security_id(instrument)
            segment = exchange_to_segment_name(instrument.exchange)
            dhan_instrument = resolve_dhan_instrument_type(
                exchange=instrument.exchange,
                symbol=instrument.symbol,
                is_option=instrument.is_option() or None,
            )

            is_intraday = interval not in ("1d", "daily", "D")

            if is_intraday:
                import re

                match = re.match(r"(\d+)", interval)
                minutes = str(match.group(1)) if match else "1"
                payload = {
                    "securityId": str(security_id),
                    "exchangeSegment": segment,
                    "instrument": dhan_instrument,
                    "interval": minutes,
                    "oi": include_oi,
                    "fromDate": from_date.strftime("%Y-%m-%d %H:%M:%S"),
                    "toDate": to_date.strftime("%Y-%m-%d %H:%M:%S"),
                }
                response = await self._execute_with_cb(
                    lambda: self._http_client.post(CHARTS_INTRADAY, json=payload)
                )
            else:
                to_date_exclusive = to_date + timedelta(days=1)
                payload = {
                    "securityId": str(security_id),
                    "exchangeSegment": segment,
                    "instrument": dhan_instrument,
                    "expiryCode": 0,
                    "oi": include_oi,
                    "fromDate": from_date.strftime("%Y-%m-%d"),
                    "toDate": to_date_exclusive.strftime("%Y-%m-%d"),
                }
                response = await self._execute_with_cb(
                    lambda: self._http_client.post(CHARTS_HISTORICAL, json=payload)
                )

            if response.status_code != 200:
                raise DhanNetworkError(
                    message=f"Historical request failed with status {response.status_code}",
                    code=str(response.status_code),
                    details=response.data,
                )

            payload_data = response.data if isinstance(response.data, dict) else {}
            data = payload_data.get("data", payload_data) if isinstance(payload_data.get("data"), dict) else payload_data
            opens = data.get("open", [])
            highs = data.get("high", [])
            lows = data.get("low", [])
            closes = data.get("close", [])
            volumes = data.get("volume", [])
            timestamps = data.get("timestamp", [])
            oi_list = data.get("open_interest", [])

            n = len(opens)
            if n == 0:
                return pd.DataFrame()

            df = pd.DataFrame({
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": volumes,
                "timestamp": timestamps,
            })
            if oi_list and len(oi_list) == n:
                df["oi"] = oi_list
            return df

        except DhanError:
            raise
        except Exception as e:
            self._handle_error(e, f"get_historical({instrument.symbol})")

    async def get_expired_options_historical_async(
        self,
        security_id: str,
        exchange: Exchange,
        instrument_type: str,
        expiry_code: int,
        from_date: datetime,
        to_date: datetime,
        interval: str = "1d",
        strike: Optional[float] = None,
        option_type: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get historical data for expired option contracts via POST /charts/rollingoption.

        This endpoint allows fetching OHLCV data for option contracts that have
        already expired, which is not available through the standard historical endpoint.

        Args:
            security_id: The security ID of the underlying instrument.
            exchange: The exchange (NSE, BSE).
            instrument_type: Dhan instrument type (e.g., "OPTIDX", "OPTSTK", "OPTFUT").
            expiry_code: Expiry code (0=current, 1=near, 2=far, 3=far+1).
            from_date: Start date for historical data.
            to_date: End date for historical data.
            interval: Time interval - "1d" for daily, or minutes ("1", "5", "15", "25", "60").
            strike: Strike price of the option.
            option_type: "CALL" or "PUT".

        Returns:
            DataFrame with columns: open, high, low, close, volume, timestamp, [oi].
        """
        await self._ensure_initialized()
        await self._apply_rate_limit("historical")

        try:
            segment = exchange_to_segment_name(exchange)

            is_intraday = interval not in ("1d", "daily", "D")
            if is_intraday:
                import re
                match = re.match(r"(\d+)", interval)
                interval_val = int(match.group(1)) if match else 1
            else:
                interval_val = 1  # Daily

            payload: Dict[str, Any] = {
                "exchangeSegment": segment,
                "securityId": int(security_id),
                "instrument": instrument_type,
                "interval": interval_val,
                "expiryFlag": 0,
                "expiryCode": expiry_code,
                "fromDate": from_date.strftime("%Y-%m-%d"),
                "toDate": to_date.strftime("%Y-%m-%d"),
            }

            if strike is not None:
                payload["strike"] = float(strike)
            if option_type is not None:
                payload["drvOptionType"] = option_type.upper()

            # Use requiredData to specify what data we need
            payload["requiredData"] = "default"

            response = await self._execute_with_cb(
                lambda: self._http_client.post(CHARTS_ROLLING_OPTION, json=payload)
            )

            if response.status_code != 200:
                raise DhanNetworkError(
                    message=f"Rolling option request failed with status {response.status_code}",
                    code=str(response.status_code),
                    details=response.data,
                )

            payload_data = response.data if isinstance(response.data, dict) else {}
            data = payload_data.get("data", payload_data) if isinstance(payload_data.get("data"), dict) else payload_data
            opens = data.get("open", [])
            highs = data.get("high", [])
            lows = data.get("low", [])
            closes = data.get("close", [])
            volumes = data.get("volume", [])
            timestamps = data.get("timestamp", [])
            oi_list = data.get("open_interest", [])

            n = len(opens)
            if n == 0:
                return pd.DataFrame()

            df = pd.DataFrame({
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": volumes,
                "timestamp": timestamps,
            })
            if oi_list and len(oi_list) == n:
                df["oi"] = oi_list
            return df

        except DhanError:
            raise
        except Exception as e:
            self._handle_error(e, f"get_expired_options_historical({security_id})")

    @staticmethod
    def parse_historical_date(date_val: Any) -> datetime:
        """Parse date value for historical request."""
        if isinstance(date_val, datetime):
            return date_val
        elif isinstance(date_val, date):
            return datetime.combine(date_val, datetime.min.time())
        elif isinstance(date_val, str):
            return datetime.strptime(date_val, "%Y-%m-%d")
        else:
            raise ValueError(f"Invalid date format: {date_val}")
