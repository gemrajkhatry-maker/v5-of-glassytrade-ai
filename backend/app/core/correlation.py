"""Correlation ID management for request tracing."""

import contextvars
import uuid

# Context variable to store correlation ID per request
_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)


def generate_correlation_id() -> str:
    """Generate a new correlation ID using UUID7-like format (time-ordered)."""
    # Use uuid4 with timestamp prefix for ordering
    return f"{int(uuid.uuid4().time * 1e7):016x}-{uuid.uuid4().hex[:8]}"


def get_correlation_id() -> str:
    """Get the current correlation ID, generating one if missing."""
    cid = _correlation_id.get()
    if cid is None:
        cid = generate_correlation_id()
        _correlation_id.set(cid)
    return cid


def set_correlation_id(cid: str | None) -> None:
    """Set the correlation ID for the current context."""
    if cid:
        _correlation_id.set(cid)
    else:
        _correlation_id.set(generate_correlation_id())


def clear_correlation_id() -> None:
    """Clear the correlation ID (for cleanup between requests)."""
    _correlation_id.set(None)


class CorrelationIdMiddleware:
    """FastAPI middleware to manage correlation IDs per request."""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            # Extract from header or generate
            headers = dict(scope.get("headers", []))
            header_bytes = headers.get(b"x-correlation-id")
            cid = header_bytes.decode() if header_bytes else generate_correlation_id()
            set_correlation_id(cid)
        
        await self.app(scope, receive, send)
        clear_correlation_id()