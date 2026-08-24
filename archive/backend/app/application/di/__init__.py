"""Dependency Injection package.

Provides a lightweight DI container with factory registration,
circular dependency detection, and singleton/transient scopes.
"""

from app.application.di.container import (
    DIContainer,
    CircularDependencyError,
    DependencyNotFoundError,
)
from app.application.di.composition_root import compose_container

__all__ = [
    "DIContainer",
    "CircularDependencyError",
    "DependencyNotFoundError",
    "compose_container",
]
