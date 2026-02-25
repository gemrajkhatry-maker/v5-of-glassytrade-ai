"""
Dhan HTTP Client - Synchronous Implementation

Synchronous HTTP client for Dhan API using requests.
This provides a simple dict-based interface for backward compatibility.
Includes correlation ID support for request tracing.
"""

import json
import time
from typing import Any, Dict, Optional

import requests

from brokers.broker.logging import get_logger, get_correlation_id

logger = get_logger("dhan.http_sync")


class DhanHttpClientSync:
    """
    Synchronous HTTP client for Dhan API.

    Simple client that returns dict responses for backward compatibility.
    This is a temporary solution until the broker is fully migrated to async.

    Attributes:
        client_id: Dhan client ID
        access_token: Dhan access token
        base_url: API base URL
        session: requests.Session instance

    Example:
        >>> client = DhanHttpClientSync(
        ...     client_id="1100001234",
        ...     access_token="eyJ0eXAiOiJKV1Qi..."
        ... )
        >>> response = client.get("/market/v1/quote", params={"security_id": "12345"})
        >>> if response["status"] == "success":
        ...     data = response["data"]
    """

    def __init__(
        self,
        client_id: str,
        access_token: str,
        base_url: str = "https://api.dhan.co/v2",
    ):
        """
        Initialize HTTP client.

        Args:
            client_id: Dhan client ID
            access_token: Dhan access token
            base_url: API base URL (default: https://api.dhan.co/v2)
        """
        self._client_id = client_id
        self._access_token = access_token
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()

        # Set default headers
        self._session.headers.update(
            {
                "access-token": access_token,
                "client-id": client_id,
                "Content-type": "application/json",
                "Accept": "application/json",
            }
        )

        logger.debug(f"DhanHttpClientSync initialized for client {client_id[:6]}...")

    def set_access_token(self, access_token: str) -> None:
        """Update the access token (e.g. after auth refresh)."""
        self._access_token = access_token
        self._session.headers["access-token"] = access_token

    def _add_client_id(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Add dhanClientId to payload."""
        payload = payload.copy()
        payload["dhanClientId"] = self._client_id
        return payload

    def get(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute GET request with correlation ID tracking.

        Args:
            endpoint: API endpoint
            params: Query parameters

        Returns:
            Dict with status, data, and optionally remarks
        """
        url = self._base_url + endpoint
        corr_id = get_correlation_id()
        start_time = time.time()

        # Add correlation ID to headers if available
        headers = {}
        if corr_id:
            headers["X-Correlation-ID"] = corr_id

        try:
            logger.debug(
                f"HTTP GET {endpoint}",
                extra={
                    "correlation_id": corr_id,
                    "http_method": "GET",
                    "endpoint": endpoint,
                    "params": params,
                },
            )

            response = self._session.get(
                url, params=params, timeout=60, headers=headers if headers else None
            )

            duration_ms = (time.time() - start_time) * 1000

            if 200 <= response.status_code < 300:
                logger.debug(
                    f"HTTP GET {endpoint} SUCCESS ({response.status_code}) in {duration_ms:.1f}ms",
                    extra={
                        "correlation_id": corr_id,
                        "http_method": "GET",
                        "endpoint": endpoint,
                        "status_code": response.status_code,
                        "duration_ms": duration_ms,
                    },
                )
                return {
                    "status": "success",
                    "data": response.json(),
                }
            else:
                try:
                    error_data = response.json()
                    logger.warning(
                        f"HTTP GET {endpoint} FAILED ({response.status_code}) in {duration_ms:.1f}ms",
                        extra={
                            "correlation_id": corr_id,
                            "http_method": "GET",
                            "endpoint": endpoint,
                            "status_code": response.status_code,
                            "duration_ms": duration_ms,
                            "error": error_data,
                        },
                    )
                    return {
                        "status": "failure",
                        "remarks": {
                            "error_code": error_data.get("errorCode"),
                            "error_type": error_data.get("errorType"),
                            "error_message": error_data.get(
                                "errorMessage", f"HTTP {response.status_code}"
                            ),
                        },
                        "data": error_data,
                    }
                except (ValueError, KeyError, AttributeError):
                    return {
                        "status": "failure",
                        "remarks": {"error_message": response.text},
                        "data": {},
                    }

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(
                f"HTTP GET {endpoint} ERROR in {duration_ms:.1f}ms: {e}",
                extra={
                    "correlation_id": corr_id,
                    "http_method": "GET",
                    "endpoint": endpoint,
                    "duration_ms": duration_ms,
                    "error": str(e),
                },
            )
            return {
                "status": "failure",
                "remarks": str(e),
                "data": {},
            }

    def post(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute POST request with correlation ID tracking.

        Args:
            endpoint: API endpoint
            payload: Request body (will have dhanClientId added)

        Returns:
            Dict with status, data, and optionally remarks
        """
        url = self._base_url + endpoint
        corr_id = get_correlation_id()
        start_time = time.time()

        # Add dhanClientId to payload
        payload = self._add_client_id(payload)

        # Add correlation ID to headers if available
        headers = {}
        if corr_id:
            headers["X-Correlation-ID"] = corr_id

        try:
            logger.debug(
                f"HTTP POST {endpoint}",
                extra={
                    "correlation_id": corr_id,
                    "http_method": "POST",
                    "endpoint": endpoint,
                },
            )

            response = self._session.post(
                url,
                data=json.dumps(payload),
                timeout=60,
                headers=headers if headers else None,
            )

            duration_ms = (time.time() - start_time) * 1000

            if 200 <= response.status_code < 300:
                logger.debug(
                    f"HTTP POST {endpoint} SUCCESS ({response.status_code}) in {duration_ms:.1f}ms",
                    extra={
                        "correlation_id": corr_id,
                        "http_method": "POST",
                        "endpoint": endpoint,
                        "status_code": response.status_code,
                        "duration_ms": duration_ms,
                    },
                )
                return {
                    "status": "success",
                    "data": response.json(),
                }
            else:
                try:
                    error_data = response.json()
                    logger.warning(
                        f"HTTP POST {endpoint} FAILED ({response.status_code}) in {duration_ms:.1f}ms",
                        extra={
                            "correlation_id": corr_id,
                            "http_method": "POST",
                            "endpoint": endpoint,
                            "status_code": response.status_code,
                            "duration_ms": duration_ms,
                            "error": error_data,
                        },
                    )
                    return {
                        "status": "failure",
                        "remarks": {
                            "error_code": error_data.get("errorCode"),
                            "error_type": error_data.get("errorType"),
                            "error_message": error_data.get(
                                "errorMessage", f"HTTP {response.status_code}"
                            ),
                        },
                        "data": error_data,
                    }
                except (ValueError, KeyError, AttributeError):
                    return {
                        "status": "failure",
                        "remarks": {"error_message": response.text},
                        "data": {},
                    }

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(
                f"HTTP POST {endpoint} ERROR in {duration_ms:.1f}ms: {e}",
                extra={
                    "correlation_id": corr_id,
                    "http_method": "POST",
                    "endpoint": endpoint,
                    "duration_ms": duration_ms,
                    "error": str(e),
                },
            )
            return {
                "status": "failure",
                "remarks": str(e),
                "data": {},
            }

    def close(self) -> None:
        """Close the HTTP client."""
        try:
            self._session.close()
            logger.debug("DhanHttpClientSync closed")
        except Exception as e:
            logger.warning(f"Error closing HTTP client: {e}")
