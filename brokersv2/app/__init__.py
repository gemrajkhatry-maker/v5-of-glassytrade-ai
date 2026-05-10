"""
Application composition root.

All entry points (CLI, Gateway, workers) must obtain their runtime
dependencies through brokersv2.app.bootstrap, never by constructing
infrastructure classes directly or importing from broker_factory.
"""
