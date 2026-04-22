"""Unit tests for session state manager (Task 2.2)."""

from __future__ import annotations

import pytest
from unittest.mock import Mock
from app.application.services.session_state_manager import SessionStateManager


class TestPriorPOCContamination:
    """Task 2.2: Prior POC should be isolated per instrument."""

    def test_prior_poc_nifty_contamination_for_crude(self):
        """Prior POC for CRUDEOIL should reject NIFTY-range values (Task 2.2)."""
        # Mock storage to return NIFTY prior POC (18000)
        mock_storage = Mock()
        mock_storage.get_previous_session_profile.return_value = {
            "poc": 18000.0,  # NIFTY range
            "vah": 18200.0,
            "val": 17800.0,
            "print_levels": [],
        }
        
        manager = SessionStateManager(storage=mock_storage)
        session = manager.get_or_create_session("CRUDEOIL 14 MAY 8300 PUT")
        
        # Prior profile should be cleared due to contamination
        # _prior_profile attribute should not exist or be None
        assert not hasattr(session, '_prior_profile') or session._prior_profile is None
        mock_storage.get_previous_session_profile.assert_called_once()

    def test_prior_poc_valid_for_crude(self):
        """Prior POC for CRUDEOIL should accept CRUDE-range values (Task 2.2)."""
        # Mock storage to return CRUDEOIL prior POC (800)
        mock_storage = Mock()
        mock_storage.get_previous_session_profile.return_value = {
            "poc": 820.0,  # CRUDEOIL range
            "vah": 830.0,
            "val": 810.0,
            "print_levels": [{"price": 825.0}],
        }
        
        manager = SessionStateManager(storage=mock_storage)
        session = manager.get_or_create_session("CRUDEOIL 14 MAY 8300 PUT")
        
        # Prior profile should be loaded
        assert session._prior_profile is not None
        assert session._prior_profile["poc"] == 820.0
        assert len(session._prior_print_levels) == 1

    def test_prior_poc_mcx_contamination_for_nifty(self):
        """Prior POC for NIFTY should reject MCX-range values (Task 2.2)."""
        # Mock storage to return CRUDEOIL prior POC (800)
        mock_storage = Mock()
        mock_storage.get_previous_session_profile.return_value = {
            "poc": 820.0,  # MCX range
            "vah": 830.0,
            "val": 810.0,
            "print_levels": [],
        }
        
        manager = SessionStateManager(storage=mock_storage)
        session = manager.get_or_create_session("NIFTY 26 JUN 24000 CALL")
        
        # Prior profile should be cleared due to contamination
        assert not hasattr(session, '_prior_profile') or session._prior_profile is None

    def test_prior_poc_goldm_accepts_correct_range(self):
        """Prior POC for GOLDM should accept GOLD-range values (Task 2.2)."""
        mock_storage = Mock()
        mock_storage.get_previous_session_profile.return_value = {
            "poc": 78500.0,  # GOLDM range
            "vah": 79000.0,
            "val": 78000.0,
            "print_levels": [],
        }
        
        manager = SessionStateManager(storage=mock_storage)
        session = manager.get_or_create_session("GOLDM 28 APR 78500 CALL")
        
        # Prior profile should be loaded
        assert hasattr(session, '_prior_profile') and session._prior_profile is not None
        assert session._prior_profile["poc"] == 78500.0
