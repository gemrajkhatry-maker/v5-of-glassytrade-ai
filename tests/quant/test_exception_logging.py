"""Verify silent exception handlers now log at DEBUG level."""

import inspect
import re
from quant.engine.decision_loop import DecisionLoop
from quant.runtime import QuantEngine


def test_no_bare_pass_in_except_blocks():
    """Ensure no bare 'except: pass' patterns exist in QuantEngine."""
    source = inspect.getsource(QuantEngine)
    
    # Pattern: "except" followed by "pass" on the next line (with optional whitespace)
    # This is a heuristic — may have false positives, but catches the main issue
    pattern = r"except\s+.*?:\s*\n\s*pass\s*\n"
    matches = re.findall(pattern, source)
    
    # We expect zero bare "except: pass" patterns after remediation
    # (all should have at least a debug log)
    assert len(matches) == 0, (
        f"Found {len(matches)} bare 'except: pass' patterns. "
        "All exception handlers should log at DEBUG level."
    )


def test_exception_handlers_have_logging():
    """Verify exception handlers in critical paths have logging."""
    engine_source = inspect.getsource(QuantEngine)
    loop_source = inspect.getsource(DecisionLoop)

    # QuantEngine still owns the runtime-level certification handler.
    assert "Certification record append failed" in engine_source

    # Certification decision + advisor notification handlers now live in the
    # decomposed DecisionLoop (quant/engine/decision_loop.py).
    assert "Certification decision record failed" in loop_source
    assert "Advisor context notification failed" in loop_source
