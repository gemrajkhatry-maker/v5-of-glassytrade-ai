"""JWT authentication for the gameloop WebSocket (review finding P1-12).

Before this module existed, ``/api/trading/ws/gameloop`` accepted any client:
anything on the network could stream the live position book, working stop
levels, risk counters and engine health.

Policy
------
``GAMELOOP_JWT_SECRET`` is the single source of truth. It is deliberately NOT
falling back to other secrets in the environment — the Dhan API secret must not
double as a session-signing key.

* secret configured  -> a valid HS256 JWT is REQUIRED, whatever the mode;
* live mode, no secret -> the connection is REFUSED (fail-closed);
* paper/development, no secret -> allowed with a loud warning, because the
  design specification's invariant 2 requires paper mode to stay operational
  during the migration.

Verification is HS256-only with a required ``exp`` claim: an explicit algorithm
allowlist defeats the ``alg=none`` and algorithm-confusion forgeries, and
requiring expiry stops a token from being valid forever.

Rejection contract
------------------
The socket is accepted and then sent ``{"error": "unauthorized", "reason": ...}``
before closing with code 4401. Accepting first is what lets a client tell an
auth failure apart from a dead backend, which a bare HTTP 403 cannot express.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import WebSocket
from fastapi.websockets import WebSocketState

logger = logging.getLogger(__name__)

SECRET_ENV_VAR = "GAMELOOP_JWT_SECRET"
ALLOWED_ALGORITHMS = ("HS256",)
WS_UNAUTHORIZED_CODE = 4401
_BEARER_PREFIX = "bearer "
_SUBPROTOCOL_PREFIX = "bearer."


class WebSocketAuthError(Exception):
    """The presented credential is missing, malformed, expired or forged."""


@dataclass(frozen=True)
class AuthDecision:
    """Outcome of a gameloop authentication attempt."""

    authenticated: bool
    subject: Optional[str]
    reason: str
    enforced: bool  # True when a credential was required


def resolve_secret() -> Optional[str]:
    """Return the configured gameloop signing secret, or ``None``.

    A blank/whitespace value counts as unset so an empty env var can never
    silently disable verification.
    """
    import os

    raw = (os.getenv(SECRET_ENV_VAR, "") or "").strip()
    return raw or None


def verify_token(token: str, secret: str) -> dict[str, Any]:
    """Decode and verify an HS256 JWT. Raises ``WebSocketAuthError`` on failure."""
    if not token:
        raise WebSocketAuthError("empty token")
    if not secret:
        raise WebSocketAuthError("no signing secret configured")

    import jwt

    try:
        return jwt.decode(
            token,
            secret,
            algorithms=list(ALLOWED_ALGORITHMS),
            options={"require": ["exp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise WebSocketAuthError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise WebSocketAuthError(f"invalid token: {exc}") from exc
    except Exception as exc:  # pragma: no cover - defensive: never leak a 500
        raise WebSocketAuthError(f"token verification failed: {exc}") from exc


def token_from_authorization(header: Optional[str]) -> Optional[str]:
    """Extract a token from an ``Authorization: Bearer <token>`` header."""
    if not header:
        return None
    value = header.strip()
    if value.lower().startswith(_BEARER_PREFIX):
        return value[len(_BEARER_PREFIX):].strip() or None
    return None


def token_from_subprotocol(protocol: Optional[str]) -> Optional[str]:
    """Extract a token from a ``bearer.<token>`` WebSocket subprotocol."""
    if not protocol:
        return None
    value = protocol.strip()
    if value.lower().startswith(_SUBPROTOCOL_PREFIX):
        return value[len(_SUBPROTOCOL_PREFIX):].strip() or None
    return None


def extract_token(ws: WebSocket) -> Optional[str]:
    """Find a token in the query string, then headers, then subprotocols.

    Browsers cannot set headers on a WebSocket, so the query parameter and the
    subprotocol form are the ones a browser frontend will actually use.
    """
    query_token = (ws.query_params.get("token") or "").strip()
    if query_token:
        # Accept both ``?token=<jwt>`` and ``?token=bearer <jwt>``.
        return token_from_authorization(query_token) or query_token

    header = ws.headers.get("authorization")
    from_header = token_from_authorization(header)
    if from_header:
        return from_header

    protocols = ws.headers.get("sec-websocket-protocol") or ""
    for protocol in protocols.split(","):
        from_protocol = token_from_subprotocol(protocol)
        if from_protocol:
            return from_protocol
    return None


async def _reject(ws: WebSocket, reason: str) -> None:
    """Tell the client why, then close. Never raises."""
    logger.warning("Gameloop WebSocket rejected: %s", reason)
    try:
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.send_json({"error": "unauthorized", "reason": reason})
            await ws.close(code=WS_UNAUTHORIZED_CODE)
        else:
            await ws.close(code=WS_UNAUTHORIZED_CODE)
    except Exception:  # silent-except - client may already be gone; nothing to do
        pass


async def authenticate_websocket(ws: WebSocket) -> AuthDecision:
    """Authenticate an accepted gameloop socket.

    Returns an ``AuthDecision``. On rejection it has already sent the error
    frame and closed the socket, so the caller must simply return.
    """
    from app.shared.mode import resolve_runtime_mode

    secret = resolve_secret()
    token = extract_token(ws)

    if secret is not None:
        if not token:
            await _reject(ws, f"missing token (send ?token=<jwt>); {SECRET_ENV_VAR} is configured")
            return AuthDecision(False, None, "missing token", enforced=True)
        try:
            claims = verify_token(token, secret)
        except WebSocketAuthError as exc:
            await _reject(ws, str(exc))
            return AuthDecision(False, None, str(exc), enforced=True)
        subject = claims.get("sub")
        return AuthDecision(True, subject, "verified", enforced=True)

    try:
        mode = resolve_runtime_mode()
    except ValueError:
        # An invalid mode is a configuration error, not a reason to expose the
        # position book: treat it as the strictest case.
        reason = "runtime mode could not be resolved; refusing unauthenticated connection"
        await _reject(ws, reason)
        return AuthDecision(False, None, reason, enforced=True)

    if mode == "live":
        reason = (
            f"{SECRET_ENV_VAR} is not configured; refusing an unauthenticated "
            f"live websocket (position book and stop levels would be exposed)"
        )
        await _reject(ws, reason)
        return AuthDecision(False, None, reason, enforced=True)

    logger.warning(
        "Gameloop WebSocket is UNAUTHENTICATED: set %s to require a JWT. "
        "Allowed only because runtime mode is %r.",
        SECRET_ENV_VAR,
        mode,
    )
    return AuthDecision(True, None, f"unauthenticated {mode} mode", enforced=False)
