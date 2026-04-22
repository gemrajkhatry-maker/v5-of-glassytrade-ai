"""Event handler package.

Provides the event handler interface and resilient wrapper for
error-isolated event processing.
"""

from app.application.events.handler import IEventHandler
from app.application.events.resilient_wrapper import ResilientHandlerWrapper

__all__ = ["IEventHandler", "ResilientHandlerWrapper"]
