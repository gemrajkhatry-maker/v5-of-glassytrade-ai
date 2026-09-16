"""Verify journal subscriber consolidation."""

import inspect
from quant.runtime import QuantEngine


def test_journal_subscriber_helper_exists():
    """Ensure the _create_journal_subscriber helper method exists."""
    assert hasattr(QuantEngine, '_create_journal_subscriber')
    assert callable(getattr(QuantEngine, '_create_journal_subscriber'))


def test_journal_event_types_helper_exists():
    """Ensure the _get_journal_event_types helper method exists."""
    assert hasattr(QuantEngine, '_get_journal_event_types')
    assert callable(getattr(QuantEngine, '_get_journal_event_types'))


def test_no_duplicate_journal_subscriber_definitions():
    """Ensure journal subscriber logic is not duplicated inline."""
    source = inspect.getsource(QuantEngine)
    
    # Count how many times we define "def _journal_subscriber(event:" inline
    # (should be zero after consolidation — all use the helper)
    inline_count = source.count("def _journal_subscriber(event:")
    
    # The helper method itself contains this pattern once, so we expect
    # exactly 1 occurrence (inside _create_journal_subscriber)
    assert inline_count == 1, (
        f"Found {inline_count} inline subscriber definitions, expected 1 (in helper)"
    )


def test_no_duplicate_event_type_lists():
    """Ensure event type list is not duplicated inline."""
    source = inspect.getsource(QuantEngine)
    
    # Count how many times we define the event type tuple inline
    # (should be zero after consolidation — all use the helper)
    inline_count = source.count("BarClosed, DecisionProduced,")
    
    # The helper method itself contains this pattern once, so we expect
    # exactly 1 occurrence (inside _get_journal_event_types)
    assert inline_count == 1, (
        f"Found {inline_count} inline event type lists, expected 1 (in helper)"
    )
