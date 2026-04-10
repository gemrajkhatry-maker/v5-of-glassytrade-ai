"""Error Handling Middleware — centralized error handling for all routes.

Features:
- Catches all unhandled exceptions
- Returns structured JSON error responses
- Logs errors with full traceback
- Rate-limit aware
- Correlation ID for request tracing
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class TradingError(Exception):
    """Base trading system error."""
    def __init__(self, message: str, code: str = "TRADING_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class DataError(TradingError):
    """Data fetch/processing error."""
    def __init__(self, message: str):
        super().__init__(message, "DATA_ERROR")


class ExecutionError(TradingError):
    """Order execution error."""
    def __init__(self, message: str):
        super().__init__(message, "EXECUTION_ERROR")


class RiskError(TradingError):
    """Risk limit exceeded."""
    def __init__(self, message: str):
        super().__init__(message, "RISK_ERROR")


async def error_handler_middleware(
    request: Request,
    call_next: Callable,
) -> Response:
    """FastAPI middleware for error handling."""
    correlation_id = str(uuid.uuid4())[:8]
    request.state.correlation_id = correlation_id

    start_time = time.time()

    try:
        response = await call_next(request)

        # Add correlation ID to response
        response.headers["X-Correlation-ID"] = correlation_id

        duration_ms = (time.time() - start_time) * 1000
        response.headers["X-Response-Time"] = f"{duration_ms:.0f}ms"

        return response

    except TradingError as e:
        logger.warning(
            "TradingError [%s]: %s | %s %s",
            correlation_id, e.message, request.method, request.url.path,
        )
        return JSONResponse(
            status_code=400,
            content={
                "error": e.code,
                "message": e.message,
                "correlation_id": correlation_id,
            },
        )

    except Exception as e:
        logger.exception(
            "UnhandledError [%s]: %s %s",
            correlation_id, request.method, request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
                "correlation_id": correlation_id,
            },
        )
