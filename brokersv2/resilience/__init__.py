"""
Platform package — canonical cross-cutting concerns.

All shared infrastructure policies (retry, rate limiting, resilience) live
here as single sources of truth.  Entry points (CLI, Gateway, workers) and
infrastructure adapters import from this package; they must NOT define their
own competing implementations.
"""
