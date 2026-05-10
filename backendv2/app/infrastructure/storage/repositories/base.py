"""Base repository pattern — common CRUD operations."""
from __future__ import annotations

from typing import Any, Protocol, TypeVar

T = TypeVar("T")


class BaseRepository(Protocol):
    """Common repository interface for type safety."""

    def save(self, entity: dict[str, Any]) -> None:
        """Persist an entity."""
        ...

    def find_by_id(self, entity_id: str) -> dict[str, Any] | None:
        """Find entity by ID."""
        ...

    def find_all(self) -> list[dict[str, Any]]:
        """Find all entities."""
        ...

    def delete(self, entity_id: str) -> bool:
        """Delete entity by ID."""
        ...
