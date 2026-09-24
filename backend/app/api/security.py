"""Operator authentication for mutating HTTP routes."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    subject: str
    roles: frozenset[str]
    claims: Mapping[str, Any]


def _error(status_code: int, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _mode() -> str:
    return os.environ.get("GLASSYTRADE_ENV", "paper").strip().lower()


def _roles(value: object) -> frozenset[str]:
    if isinstance(value, str):
        return frozenset({value})
    if isinstance(value, (list, tuple, set, frozenset)):
        return frozenset(str(item) for item in value)
    return frozenset()


def require_operator(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthContext:
    """Authenticate an operator or fail closed before a mutating action."""

    del request
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _error(401, "operator authentication required")
    token = credentials.credentials
    if not token:
        raise _error(401, "operator authentication required")

    mode = _mode()
    if mode == "paper":
        expected = os.environ.get("GLASSYTRADE_DEV_OPERATOR_TOKEN", "")
        if not expected or not secrets.compare_digest(token, expected):
            raise _error(403, "operator token is not authorized")
        return AuthContext(
            subject="development-operator",
            roles=frozenset({"operator"}),
            claims=MappingProxyType({"sub": "development-operator", "roles": ["operator"]}),
        )
    if mode != "live":
        raise _error(403, "operator authentication mode is not supported")

    secret = os.environ.get("GAMELOOP_JWT_SECRET", "")
    if not secret:
        raise _error(403, "live operator authentication is not configured")
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["exp"]},
        )
    except (jwt.InvalidTokenError, TypeError, ValueError) as exc:
        raise _error(401, "invalid operator token") from exc

    subject = str(claims.get("sub", ""))
    roles = _roles(claims.get("roles"))
    if not subject or not roles.intersection({"operator", "admin"}):
        raise _error(403, "operator role is required")
    return AuthContext(
        subject=subject,
        roles=roles,
        claims=MappingProxyType(dict(claims)),
    )
