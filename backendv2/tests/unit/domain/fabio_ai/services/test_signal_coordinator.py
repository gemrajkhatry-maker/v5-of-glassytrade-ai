"""Tests for SignalCoordinator — the final gatekeeper before trade entries."""
import pytest

from app.domain.fabio_ai.services.signal_coordinator import (
    EntryEvaluation,
    SignalCoordinator,
)


class FakeAgentDecision:
    """Minimal fake agent decision for tests."""
    def __init__(self, direction: str, probability: float):
        self.direction = direction
        self.probability = probability


class FakeSessionInfo:
    """Minimal fake session info for tests."""
    def __init__(self, allow_entry: bool = True):
        self.allow_entry = allow_entry


class FakeAmtResult:
    """Minimal fake AMT result for tests."""
    def __init__(self, market_state: str = "TREND"):
        self.market_state = market_state


@pytest.fixture
def coordinator():
    return SignalCoordinator()


@pytest.fixture
def agent_decision_long_high():
    return FakeAgentDecision("LONG", 0.70)


@pytest.fixture
def agent_decision_flat():
    return FakeAgentDecision("FLAT", 0.30)


@pytest.fixture
def agent_decision_short():
    return FakeAgentDecision("SHORT", 0.60)


@pytest.fixture
def amt_result_trend():
    return FakeAmtResult("TREND")


@pytest.fixture
def amt_result_balanced():
    return FakeAmtResult("BALANCED")


@pytest.fixture
def session_allow():
    return FakeSessionInfo(allow_entry=True)


@pytest.fixture
def session_deny():
    return FakeSessionInfo(allow_entry=False)


# ---------------------------------------------------------------------------
# evaluate_entry() — early exits
# ---------------------------------------------------------------------------


class TestEvaluateEntryEarlyExits:
    """Test the early-exit gates in evaluate_entry()."""

    def test_position_already_open(self, coordinator, agent_decision_long_high, amt_result_trend, session_allow):
        """When a position is already open, entry is blocked."""
        result = coordinator.evaluate_entry(
            agent_decision=agent_decision_long_high,
            amt_result=amt_result_trend,
            tick=None,
            session_info=session_allow,
            confirmation_strong=True,
            is_new_candle=True,
            is_overseer_running=False,
            has_position=True,
            allow_short=False,
        )

        assert result.should_enter is False
        assert result.reason == "Position already open"
        assert result.direction == "FLAT"
        assert result.timing == "SKIP"

    def test_overseer_running(self, coordinator, agent_decision_long_high, amt_result_trend, session_allow):
        """When overseer is still processing, entry waits."""
        result = coordinator.evaluate_entry(
            agent_decision=agent_decision_long_high,
            amt_result=amt_result_trend,
            tick=None,
            session_info=session_allow,
            confirmation_strong=True,
            is_new_candle=True,
            is_overseer_running=True,
            has_position=False,
            allow_short=False,
        )

        assert result.should_enter is False
        assert result.reason == "Overseer processing"
        assert result.timing == "WAIT"

    def test_no_agent_decision(self, coordinator, amt_result_trend, session_allow):
        """When agent_decision is None, entry is skipped."""
        result = coordinator.evaluate_entry(
            agent_decision=None,
            amt_result=amt_result_trend,
            tick=None,
            session_info=session_allow,
            confirmation_strong=True,
            is_new_candle=True,
            is_overseer_running=False,
            has_position=False,
            allow_short=False,
        )

        assert result.should_enter is False
        assert result.reason == "No agent decision"

    def test_agent_says_flat(self, coordinator, agent_decision_flat, amt_result_trend, session_allow):
        """When the agent decision is FLAT, entry is blocked."""
        result = coordinator.evaluate_entry(
            agent_decision=agent_decision_flat,
            amt_result=amt_result_trend,
            tick=None,
            session_info=session_allow,
            confirmation_strong=True,
            is_new_candle=True,
            is_overseer_running=False,
            has_position=False,
            allow_short=False,
        )

        assert result.should_enter is False
        assert result.reason == "Agent says no edge"
        assert result.direction == "FLAT"


class TestEvaluateEntryDirectionGates:
    """Test direction-specific gating logic."""

    def test_short_blocked_when_only_long_allowed(
        self, coordinator, agent_decision_short, amt_result_trend, session_allow
    ):
        """SHORT direction is blocked when allow_short=False."""
        result = coordinator.evaluate_entry(
            agent_decision=agent_decision_short,
            amt_result=amt_result_trend,
            tick=None,
            session_info=session_allow,
            confirmation_strong=True,
            is_new_candle=True,
            is_overseer_running=False,
            has_position=False,
            allow_short=False,
        )

        assert result.should_enter is False
        assert result.reason == "SHORT not allowed"


class TestEvaluateEntryConfirmation:
    """Test confirmation strength gating."""

    def test_weak_confirmation_blocks_entry(
        self, coordinator, agent_decision_long_high, amt_result_trend, session_allow
    ):
        """When confirmation is weak, entry returns with conviction LOW."""
        result = coordinator.evaluate_entry(
            agent_decision=agent_decision_long_high,
            amt_result=amt_result_trend,
            tick=None,
            session_info=session_allow,
            confirmation_strong=False,
            is_new_candle=True,
            is_overseer_running=False,
            has_position=False,
            allow_short=False,
        )

        assert result.should_enter is False
        assert result.reason == "Confirmation weak"
        assert result.conviction == "LOW"
        assert result.timing == "WAIT"


class TestEvaluateEntrySuccess:
    """Test the happy path — all gates pass."""

    def test_all_gates_pass_returns_ready_to_enter(
        self, coordinator, agent_decision_long_high, amt_result_trend, session_allow
    ):
        """When all gates pass, entry is approved with correct conviction."""
        result = coordinator.evaluate_entry(
            agent_decision=agent_decision_long_high,
            amt_result=amt_result_trend,
            tick=None,
            session_info=session_allow,
            confirmation_strong=True,
            is_new_candle=True,
            is_overseer_running=False,
            has_position=False,
            allow_short=False,
        )

        assert result.should_enter is True
        assert result.direction == "LONG"
        assert result.probability == 0.70
        assert result.timing == "ENTER_NOW"
        assert result.reason == "Ready to enter"
        assert result.conviction == "HIGH"

    def test_medium_conviction_when_prob_above_agent_threshold(
        self, coordinator, amt_result_trend, session_allow
    ):
        """Probability between AGENT_DECISION_THRESHOLD and CONFIDENCE_HIGH_THRESHOLD yields MEDIUM conviction."""
        agent = FakeAgentDecision("LONG", 0.60)
        result = coordinator.evaluate_entry(
            agent_decision=agent,
            amt_result=amt_result_trend,
            tick=None,
            session_info=session_allow,
            confirmation_strong=True,
            is_new_candle=True,
            is_overseer_running=False,
            has_position=False,
            allow_short=False,
        )

        assert result.should_enter is True
        assert result.conviction == "MEDIUM"

    def test_low_probability_blocked(
        self, coordinator, amt_result_trend, session_allow
    ):
        """Probability below AGENT_DECISION_THRESHOLD blocks entry entirely."""
        agent = FakeAgentDecision("LONG", 0.40)
        result = coordinator.evaluate_entry(
            agent_decision=agent,
            amt_result=amt_result_trend,
            tick=None,
            session_info=session_allow,
            confirmation_strong=True,
            is_new_candle=True,
            is_overseer_running=False,
            has_position=False,
            allow_short=False,
        )

        assert result.should_enter is False
        assert result.reason == "Low probability"

    def test_session_does_not_allow_entries(
        self, coordinator, agent_decision_long_high, amt_result_trend, session_deny
    ):
        """When session_info.allow_entry is False, entry is blocked."""
        result = coordinator.evaluate_entry(
            agent_decision=agent_decision_long_high,
            amt_result=amt_result_trend,
            tick=None,
            session_info=session_deny,
            confirmation_strong=True,
            is_new_candle=True,
            is_overseer_running=False,
            has_position=False,
            allow_short=False,
        )

        assert result.should_enter is False
        assert result.reason == "Session does not allow entries"

    def test_setup_type_trend_continuation(
        self, coordinator, agent_decision_long_high, amt_result_trend, session_allow
    ):
        """When market state is not BALANCED, setup type is TREND_CONTINUATION."""
        result = coordinator.evaluate_entry(
            agent_decision=agent_decision_long_high,
            amt_result=amt_result_trend,
            tick=None,
            session_info=session_allow,
            confirmation_strong=True,
            is_new_candle=True,
            is_overseer_running=False,
            has_position=False,
            allow_short=False,
        )

        assert result.setup_type == "TREND_CONTINUATION"

    def test_setup_type_mean_reversion(
        self, coordinator, agent_decision_long_high, amt_result_balanced, session_allow
    ):
        """When market state is BALANCED, setup type is MEAN_REVERSION."""
        result = coordinator.evaluate_entry(
            agent_decision=agent_decision_long_high,
            amt_result=amt_result_balanced,
            tick=None,
            session_info=session_allow,
            confirmation_strong=True,
            is_new_candle=True,
            is_overseer_running=False,
            has_position=False,
            allow_short=False,
        )

        assert result.setup_type == "MEAN_REVERSION"


# ---------------------------------------------------------------------------
# EntryEvaluation dataclass
# ---------------------------------------------------------------------------


class TestEntryEvaluation:
    """Test the EntryEvaluation dataclass structure and fields."""

    def test_all_fields_present(self):
        """EntryEvaluation has all required fields."""
        ev = EntryEvaluation(
            should_enter=True,
            direction="LONG",
            probability=0.75,
            timing="ENTER_NOW",
            reason="Ready to enter",
            conviction="HIGH",
            setup_type="TREND_CONTINUATION",
        )

        assert ev.should_enter is True
        assert ev.direction == "LONG"
        assert ev.probability == 0.75
        assert ev.timing == "ENTER_NOW"
        assert ev.reason == "Ready to enter"
        assert ev.conviction == "HIGH"
        assert ev.setup_type == "TREND_CONTINUATION"

    def test_conviction_high(self):
        """HIGH conviction evaluation."""
        ev = EntryEvaluation(
            should_enter=True, direction="LONG", probability=0.70,
            timing="ENTER_NOW", reason="Ready", conviction="HIGH",
            setup_type="TREND_CONTINUATION",
        )
        assert ev.conviction == "HIGH"
        assert ev.should_enter is True

    def test_conviction_medium(self):
        """MEDIUM conviction evaluation."""
        ev = EntryEvaluation(
            should_enter=True, direction="SHORT", probability=0.60,
            timing="ENTER_NOW", reason="Ready", conviction="MEDIUM",
            setup_type="MEAN_REVERSION",
        )
        assert ev.conviction == "MEDIUM"

    def test_conviction_low_blocks_entry(self):
        """LOW conviction evaluations have should_enter=False."""
        ev = EntryEvaluation(
            should_enter=False, direction="FLAT", probability=0.55,
            timing="WAIT", reason="Confirmation weak", conviction="LOW",
            setup_type="NONE",
        )
        assert ev.conviction == "LOW"
        assert ev.should_enter is False

    def test_rejected_entry_has_no_setup_type(self):
        """Rejected entries have setup_type='NONE'."""
        ev = EntryEvaluation(
            should_enter=False, direction="FLAT", probability=0.0,
            timing="SKIP", reason="Position already open", conviction="NONE",
            setup_type="NONE",
        )
        assert ev.setup_type == "NONE"
        assert ev.conviction == "NONE"
