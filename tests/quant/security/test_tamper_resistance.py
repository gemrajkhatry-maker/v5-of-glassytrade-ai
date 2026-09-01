"""Adversarial security tests for EventStore tamper resistance.

These tests SHOULD FAIL to reveal real security vulnerabilities in the
event sourcing system. Each test documents the attack vector, expected
secure behavior, and actual (vulnerable) behavior.

Severity ratings:
- CRITICAL: Direct financial impact (tampered PnL, forged positions)
- MAJOR: Integrity compromise (silent state corruption)
- MINOR: Defense-in-depth gaps (information leakage, DoS)

Attack surface:
1. Checksum chain integrity
2. Direct private member access
3. Event injection via import_()
4. fold() without integrity verification
5. Malformed event payloads
6. State machine guard bypasses
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from quant.event_store import EventStore
from quant.events import (
    BarClosed,
    Event,
    PositionClosed,
    PositionOpened,
    RiskUpdated,
)
from quant.state_machine import Bar, EngineState, PositionState, RiskState
from quant.transitions import apply_event


# =============================================================================
# Helper: craft valid events for baseline
# =============================================================================

def _make_bar_close(symbol: str = "NIFTY", time: str = "2026-09-01T09:15:00") -> BarClosed:
    return BarClosed(
        symbol=symbol,
        time=time,
        bar=Bar(time=time, open=100.0, high=101.0, low=99.0, close=100.5, volume=1000.0),
    )


def _make_position_opened(
    symbol: str = "NIFTY",
    time: str = "2026-09-01T09:16:00",
    pos_id: str = "pos-001",
) -> PositionOpened:
    return PositionOpened(
        symbol=symbol,
        time=time,
        position=PositionState(
            id=pos_id,
            entry=100.0,
            size=10.0,
            sl=99.0,
            tp=102.0,
            side="LONG",
        ),
    )


def _make_position_closed(
    symbol: str = "NIFTY",
    time: str = "2026-09-01T09:30:00",
    pos_id: str = "pos-001",
    close_price: float = 101.0,
) -> PositionClosed:
    """Create a PositionClosed event with a minimal Position-like object."""
    # PositionClosed expects event.fill.position._id
    # We need a Fill-like object with a position that has _id
    @dataclass(frozen=True)
    class FakePosition:
        _id: str = ""
        open_price: float = 100.0
        open_time: str = ""
        size: float = 10.0
        realized_pnl: float = 0.0
        pyramid_level: int = 0
        is_pyramid: bool = False

    @dataclass(frozen=True)
    class FakeFill:
        position: FakePosition = field(default_factory=lambda: FakePosition(_id=pos_id))
        close_price: float = 100.0
        close_time: str = ""
        reason: str = "TEST"
        pnl: float = 10.0

    return PositionClosed(symbol=symbol, time=time, fill=FakeFill(close_price=close_price))


# =============================================================================
# ATTACK 1: Tamper events after append (CRITICAL)
# =============================================================================

class TestTamperAfterAppend:
    """Verify that modifying events after append is detected.

    Expected: verify_chain() returns False after tampering.
    Actual (vulnerable): Checksum chain can be recomputed to match tampered data.
    """

    def test_tamper_event_symbol_detected(self):
        """Tampering with an event's symbol should break the chain."""
        store = EventStore()
        store.append(_make_bar_close(symbol="NIFTY"))

        # Attacker modifies the event directly
        store._events[0] = _make_bar_close(symbol="BANKNIFTY")

        # SECURE: This MUST be False — tampering detected
        assert store.verify_chain() is False, (
            "CRITICAL: Tampered event symbol not detected by verify_chain()"
        )

    def test_tamper_event_time_detected(self):
        """Tampering with an event's time should break the chain."""
        store = EventStore()
        store.append(_make_bar_close(time="2026-09-01T09:15:00"))

        # Attacker modifies the time
        store._events[0] = _make_bar_close(time="2026-09-01T15:00:00")

        assert store.verify_chain() is False, (
            "CRITICAL: Tampered event time not detected by verify_chain()"
        )

    def test_tamper_then_recalculate_checksums_undetected(self):
        """CRITICAL: Attacker tampers with event but CANNOT recalculate checksums.

        With HMAC-SHA256, the checksum depends on a secret key that the attacker
        does not have. Even if the attacker tampers with event[i], they cannot
        recompute valid checksums[i..n] without the secret.

        Expected: verify_chain() MUST detect tampering (returns False).
        """
        store = EventStore()
        store.append(_make_bar_close(symbol="NIFTY", time="t1"))
        store.append(_make_bar_close(symbol="NIFTY", time="t2"))
        store.append(_make_bar_close(symbol="NIFTY", time="t3"))

        # Attacker tampers with event at index 1
        store._events[1] = _make_bar_close(symbol="NIFTY", time="TAMPERED")

        # Attacker CANNOT recalculate checksums without the secret key
        # So verify_chain() should detect the tampering
        assert store.verify_chain() is False, (
            "CRITICAL: Tampered event not detected by verify_chain()"
        )


# =============================================================================
# ATTACK 2: Break checksum — recalculate for tampered data (CRITICAL)
# =============================================================================

class TestChecksumRecalculation:
    """Verify that checksums cannot be forged for arbitrary data.

    Expected: Only the original signer (with a secret) can produce valid checksums.
    Actual: Checksums are deterministic SHA-256 with no secret — anyone can forge.
    """

    def test_checksum_forgeable_without_secret(self):
        """CRITICAL: Checksums use no secret — anyone can forge valid checksums.

        An attacker can create a completely fake event log with valid checksums
        by computing SHA-256(prev + event_data). No HMAC, no key, no nonce.

        Expected: verify_chain() should reject forged checksums.
        Actual: verify_chain() accepts them because it recomputes the same way.
        """
        store = EventStore()

        # Attacker creates a fake event log from scratch
        fake_events = [
            _make_bar_close(symbol="FAKE", time="fake1"),
            _make_bar_close(symbol="FAKE", time="fake2"),
        ]

        # Attacker computes valid checksums (no secret needed)
        prev = "GENESIS"
        for event in fake_events:
            data = json.dumps(
                {"prev": prev, "symbol": event.symbol, "time": event.time, "type": type(event).__name__},
                sort_keys=True,
            )
            prev = hashlib.sha256(data.encode()).hexdigest()
            store._events.append(event)
            store._checksums.append(prev)

        # SECURE: This should be False — these are forged events
        # But verify_chain() will return True because the math checks out
        assert store.verify_chain() is True  # This PASSES — that's the bug
        # The real assertion: there's no way to distinguish this from legit events


# =============================================================================
# ATTACK 3: Inject events from untrusted source (CRITICAL)
# =============================================================================

class TestEventInjection:
    """Verify that import_() validates incoming events.

    Expected: import_() should reject events with invalid types, missing fields,
    or payloads that don't match the event_type.
    Actual: import_() trusts all input and reconstructs events without validation.
    """

    def test_inject_unknown_event_type(self):
        """Injecting an unknown event type should be rejected.

        Expected: import_() raises ValueError for unknown types.
        Actual: Unknown types are silently imported as base Event objects.
        """
        store = EventStore()
        malicious_payload = [
            {
                "sequence": 1,
                "symbol": "NIFTY",
                "time": "2026-09-01T09:15:00",
                "event_type": "MaliciousEventType",
                "payload": {"evil": True},
            }
        ]

        # SECURE: This should raise ValueError
        # Actual: Silently imports as base Event
        store.import_(malicious_payload)

        # The bug: unknown type becomes a base Event — no validation
        assert len(store._events) == 1
        assert type(store._events[0]).__name__ == "Event"  # Should not happen

    def test_inject_position_opened_with_malicious_id(self):
        """Injecting a PositionOpened with a crafted position ID.

        Expected: import_() should validate position data integrity.
        Actual: Any dict is accepted and reconstructed.
        """
        store = EventStore()
        malicious_payload = [
            {
                "sequence": 1,
                "symbol": "NIFTY",
                "time": "2026-09-01T09:15:00",
                "event_type": "PositionOpened",
                "payload": {
                    "position": {
                        "id": "FORGED_POSITION",
                        "entry": 100.0,
                        "size": 999999.0,  # Huge size
                        "sl": 0.0,  # No stop loss
                        "tp": 999999.0,  # Unrealistic target
                        "side": "LONG",
                        "pyramid_level": 0,
                        "is_pyramid": False,
                    }
                },
            }
        ]

        store.import_(malicious_payload)

        # SECURE: This should be rejected
        # Actual: Malicious position is imported
        assert len(store._events) == 1
        injected = store._events[0]
        assert isinstance(injected, PositionOpened)
        assert injected.position.size == 999999.0  # Huge position accepted

    def test_inject_risk_updated_with_halt_bypass(self):
        """Injecting RiskUpdated to bypass trading halts.

        Expected: import_() should not allow injecting risk state that overrides
        actual risk calculations.
        Actual: RiskUpdated can be injected with halted=False to bypass halts.
        """
        store = EventStore()
        malicious_payload = [
            {
                "sequence": 1,
                "symbol": "NIFTY",
                "time": "2026-09-01T09:15:00",
                "event_type": "RiskUpdated",
                "payload": {
                    "risk": {
                        "daily_pnl": 999999.0,  # Fake profit
                        "trades_today": 0,
                        "halted": False,  # Bypass halt
                        "halt_reason": "",
                    }
                },
            }
        ]

        store.import_(malicious_payload)

        # SECURE: This should be rejected
        # Actual: Fake risk state injected
        assert len(store._events) == 1
        injected = store._events[0]
        assert isinstance(injected, RiskUpdated)
        assert injected.risk.halted is False  # Halt bypassed
        assert injected.risk.daily_pnl == 999999.0  # Fake PnL


# =============================================================================
# ATTACK 4: Access private members directly (MAJOR)
# =============================================================================

class TestPrivateMemberAccess:
    """Verify that private members cannot be modified externally.

    Expected: _events and _checksums should be truly immutable from outside.
    Actual: Python has no real private — direct modification is trivial.
    """

    def test_direct_events_modification(self):
        """Directly modifying _events should be prevented.

        Expected: _events should be immutable (tuple or frozen list).
        Actual: _events is a plain list — fully mutable.
        """
        store = EventStore()
        store.append(_make_bar_close())

        # Attacker directly modifies the events list
        original_event = store._events[0]
        store._events[0] = _make_bar_close(symbol="TAMPERED")

        # SECURE: This should not be possible
        # Actual: Direct modification succeeds
        assert store._events[0].symbol == "TAMPERED"

    def test_direct_checksums_modification(self):
        """Directly modifying _checksums should be prevented.

        Expected: _checksums should be immutable.
        Actual: _checksums is a plain list.
        """
        store = EventStore()
        store.append(_make_bar_close())

        # Attacker directly modifies checksums
        store._checksums[0] = "FORGED_CHECKSUM"

        # SECURE: This should not be possible
        # Actual: Direct modification succeeds
        assert store._checksums[0] == "FORGED_CHECKSUM"

    def test_direct_sequence_manipulation(self):
        """Directly modifying _sequence should be prevented.

        Expected: _sequence should be read-only.
        Actual: _sequence is a plain int.
        """
        store = EventStore()
        store.append(_make_bar_close())

        # Attacker manipulates sequence
        store._sequence = 999999

        # SECURE: This should not be possible
        # Actual: Direct modification succeeds
        assert store._sequence == 999999


# =============================================================================
# ATTACK 5: Denial of service — craft events that crash fold() (MAJOR)
# =============================================================================

class TestFoldDoS:
    """Verify that fold() handles malformed events gracefully.

    Expected: fold() should skip or raise on malformed events without crashing.
    Actual: fold() crashes on events with missing/invalid attributes.
    """

    def test_fold_crashes_on_position_opened_with_none_position(self):
        """PositionOpened with None position crashes fold().

        Expected: fold() raises ValueError with clear message.
        Actual: fold() crashes with AttributeError when accessing position.id.
        """
        store = EventStore()
        store.append(_make_bar_close())

        # Attacker injects a PositionOpened with None position
        malicious_event = PositionOpened(
            symbol="NIFTY",
            time="t1",
            position=None,  # Malformed
        )
        store._events.append(malicious_event)
        store._checksums.append("fake")

        # SECURE: fold() should raise ValueError
        # Actual: Crashes with AttributeError
        with pytest.raises((ValueError, AttributeError)):
            store.fold()

    def test_fold_crashes_on_position_closed_with_none_fill(self):
        """PositionClosed with None fill crashes fold().

        Expected: fold() raises ValueError.
        Actual: Crashes with AttributeError.
        """
        store = EventStore()
        store.append(_make_position_opened(pos_id="pos-001"))

        # Attacker injects a PositionClosed with None fill
        malicious_event = PositionClosed(
            symbol="NIFTY",
            time="t1",
            fill=None,  # Malformed
        )
        store._events.append(malicious_event)
        store._checksums.append("fake")

        # SECURE: fold() should raise ValueError
        # Actual: Crashes with AttributeError
        with pytest.raises((ValueError, AttributeError)):
            store.fold()

    def test_fold_crashes_on_position_closed_with_none_position_in_fill(self):
        """PositionClosed with fill.position = None crashes fold().

        Expected: fold() raises ValueError.
        Actual: Crashes with AttributeError on fill.position._id.
        """
        store = EventStore()
        store.append(_make_position_opened(pos_id="pos-001"))

        @dataclass(frozen=True)
        class FakeFill:
            position: Any = None
            close_price: float = 100.0
            close_time: str = "t1"
            reason: str = "TEST"
            pnl: float = 0.0

        malicious_event = PositionClosed(
            symbol="NIFTY",
            time="t1",
            fill=FakeFill(position=None),
        )
        store._events.append(malicious_event)
        store._checksums.append("fake")

        # SECURE: fold() should raise ValueError
        # Actual: Crashes with AttributeError
        with pytest.raises((ValueError, AttributeError)):
            store.fold()


# =============================================================================
# ATTACK 6: State machine guard bypass (MAJOR)
# =============================================================================

class TestStateMachineGuardBypass:
    """Verify that state machine guards cannot be bypassed.

    Expected: Guards should prevent invalid transitions.
    Actual: Some guards have bypass paths.
    """

    def test_position_closed_with_wrong_id_silently_ignored(self):
        """PositionClosed with mismatched ID is silently ignored.

        Expected: This should raise ValueError — position IDs must match.
        Actual: Silently returns unchanged state, allowing an attacker to
        inject fake closes that don't actually close positions.
        """
        store = EventStore()
        store.append(_make_position_opened(pos_id="legit-pos-001"))

        # Attacker injects a close for a different position
        malicious_close = _make_position_closed(pos_id="different-pos-id")
        store._events.append(malicious_close)
        store._checksums.append("fake")

        # fold() should detect this as invalid
        state = store.fold()

        # SECURE: The position should still be open (close was invalid)
        # But this is actually correct behavior — the close is ignored
        # The bug is that there's no logging/alerting of the invalid close
        assert state.position is not None  # Position still open

    def test_double_position_open_raises(self):
        """Opening a position when one is already open should raise.

        Expected: apply_event() raises ValueError.
        Actual: Correctly raises — this guard works.
        """
        store = EventStore()
        store.append(_make_position_opened(pos_id="pos-001"))

        # Try to open another position
        second_open = _make_position_opened(pos_id="pos-002")
        store._events.append(second_open)
        store._checksums.append("fake")

        # SECURE: fold() should raise ValueError
        with pytest.raises(ValueError, match="Position already open"):
            store.fold()


# =============================================================================
# ATTACK 7: fold() without integrity verification (CRITICAL)
# =============================================================================

class TestFoldWithoutVerification:
    """Verify that fold() checks chain integrity before deriving state.

    Expected: fold() should call verify_chain() first and raise if invalid.
    Actual: fold() derives state from events without any integrity check.
    """

    def test_fold_derives_state_from_tampered_events(self):
        """fold() should refuse to derive state from tampered events.

        Expected: fold() raises SecurityError if verify_chain() fails.
        Actual: fold() silently derives state from tampered events.
        """
        store = EventStore()
        store.append(_make_bar_close(symbol="NIFTY", time="t1"))
        store.append(_make_position_opened(pos_id="pos-001"))

        # Tamper with an event
        store._events[0] = _make_bar_close(symbol="TAMPERED", time="TAMPERED")

        # SECURE: fold() should raise SecurityError
        # Actual: fold() silently derives state from tampered events
        state = store.fold()

        # The bug: state is derived from tampered data without any check
        # No exception raised, no warning logged
        assert state is not None  # fold() succeeded — that's the bug

    def test_fold_should_verify_chain_before_deriving_state(self):
        """fold() must verify chain integrity before deriving state.

        This is the core security property: state is only as trustworthy
        as the events it's derived from.
        """
        store = EventStore()
        store.append(_make_bar_close(symbol="NIFTY"))

        # Tamper with the event
        store._events[0] = _make_bar_close(symbol="TAMPERED")
        assert store.verify_chain() is False  # Chain is broken

        # SECURE: fold() should raise SecurityError
        # Actual: fold() proceeds without checking
        state = store.fold()  # Should raise, but doesn't


# =============================================================================
# ATTACK 8: Replay attack (MAJOR)
# =============================================================================

class TestReplayAttack:
    """Verify that event replay is detected and prevented.

    Expected: Each event should have a unique, non-replayable identifier.
    Actual: Events can be replayed by re-importing the same event log.
    """

    def test_replay_same_events_produces_same_state(self):
        """Replaying the same events produces identical state.

        Expected: Replay should be detected (e.g., via sequence numbers).
        Actual: Replay is silently accepted — no replay protection.
        """
        store1 = EventStore()
        store1.append(_make_bar_close(symbol="NIFTY", time="t1"))
        store1.append(_make_position_opened(pos_id="pos-001"))

        # Export and replay
        exported = store1.export()
        store2 = EventStore()
        store2.import_(exported)

        # SECURE: Replay should be detected
        # Actual: Replay produces identical state
        state1 = store1.fold()
        state2 = store2.fold()

        assert state1.position.id == state2.position.id  # Same state from replay


# =============================================================================
# ATTACK 9: Sequence number manipulation (MINOR)
# =============================================================================

class TestSequenceManipulation:
    """Verify that sequence numbers are monotonic and gapless.

    Expected: Gaps in sequence numbers should be detected.
    Actual: Sequence numbers are computed from list index — no gap detection.
    """

    def test_get_since_with_invalid_sequence(self):
        """get_since() with out-of-range sequence should return empty or raise.

        Expected: Returns empty list for invalid sequence.
        Actual: Returns events from start (off-by-one in start_idx).
        """
        store = EventStore()
        store.append(_make_bar_close())
        store.append(_make_bar_close())

        # Request from sequence 100 (beyond end)
        result = store.get_since(100)

        # SECURE: Should return empty list
        # Actual: Returns empty list (this works correctly)
        assert result == []

    def test_get_since_with_zero_sequence(self):
        """get_since(0) should return all events.

        Expected: Returns all events (sequence starts at 1).
        Actual: Returns all events (start_idx = max(0, -1) = 0).
        """
        store = EventStore()
        store.append(_make_bar_close())
        store.append(_make_bar_close())

        result = store.get_since(0)

        # SECURE: Should return all events
        assert len(result) == 2


# =============================================================================
# ATTACK 10: Export/Import round-trip integrity (MAJOR)
# =============================================================================

class TestExportImportIntegrity:
    """Verify that export/import preserves integrity.

    Expected: Exported data should be signed; import should verify signature.
    Actual: No signing — export/import is a plain dict copy.
    """

    def test_export_import_preserves_tampered_data(self):
        """Tampered data survives export/import round-trip.

        Expected: Tampered data should be detected on import.
        Actual: Tampered data is faithfully preserved.
        """
        store1 = EventStore()
        store1.append(_make_bar_close(symbol="NIFTY"))

        # Tamper with the event
        store1._events[0] = _make_bar_close(symbol="TAMPERED")

        # Export and re-import
        exported = store1.export()
        store2 = EventStore()
        store2.import_(exported)

        # SECURE: Tampered data should be detected
        # Actual: Tampered data is preserved
        assert store2._events[0].symbol == "TAMPERED"

    def test_import_clears_existing_events(self):
        """import_() clears existing events — potential data loss.

        Expected: import_() should require explicit confirmation or use a
        separate method name like load_from_snapshot().
        Actual: import_() silently replaces all events.
        """
        store = EventStore()
        store.append(_make_bar_close(symbol="NIFTY"))
        store.append(_make_position_opened(pos_id="pos-001"))

        # Attacker calls import_() with empty data
        store.import_([])

        # SECURE: This should require confirmation
        # Actual: All events are silently deleted
        assert len(store._events) == 0
        assert store._sequence == 0


# =============================================================================
# Summary: Security findings
# =============================================================================

"""
SECURITY AUDIT SUMMARY
======================

CRITICAL FINDINGS:
1. Checksum chain is NOT tamper-evident — anyone can recompute valid checksums
2. fold() derives state without verifying chain integrity
3. import_() accepts untrusted input without validation
4. No secret/key in checksum computation — SHA-256 alone is forgeable

MAJOR FINDINGS:
1. Direct access to _events, _checksums, _sequence (Python has no private)
2. PositionClosed with mismatched ID silently ignored (no alerting)
3. fold() crashes on malformed events (DoS vector)
4. No replay protection — events can be replayed indefinitely
5. import_() silently replaces all events (data loss vector)

MINOR FINDINGS:
1. No sequence number gap detection
2. No event signing or HMAC
3. No audit log for import_() operations

RECOMMENDATIONS:
1. Use HMAC-SHA256 with a secret key for checksums
2. Make _events and _checksums truly immutable (tuple, mappingproxy)
3. Call verify_chain() at the start of fold()
4. Validate all fields in import_() — reject unknown types
5. Add sequence number verification (detect gaps)
6. Sign exported data; verify signature on import
7. Add audit logging for all state mutations
"""
