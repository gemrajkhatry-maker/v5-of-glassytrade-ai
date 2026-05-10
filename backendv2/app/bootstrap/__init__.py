"""Bootstrap package for application initialization.

Splits the monolithic api/main.py lifespan into testable,
layer-specific bootstrap modules.
"""

from app.bootstrap.container import bootstrap_container
from app.bootstrap.lifespan import create_lifespan

__all__ = [
    "bootstrap_container",
    "create_lifespan",
]
