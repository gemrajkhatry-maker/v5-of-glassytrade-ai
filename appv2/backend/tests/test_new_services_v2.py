"""Tests for new Fabio-alignment services."""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from datetime import date, datetime
from appv2.domain.services.session_strategy_selector import (
    SessionStrategySelector, SessionStrategyConfig, StrategyMode,
)
from appv2.domain.services.first_breakout_filter import (
    FirstBreakoutFilter, BreakoutState,
)
from appv2.domain.services.cross_index_correlation import CrossIndexCorrelation
from appv2.domain.services.gamma_acceleration import (
    GammaAccelerationDetector, GammaRiskLevel,
)
from appv2.domain.services.gate_pipeline import GateContext, run_gate_pipeline


# ── Session Strategy Selector ──────────────────────────────────────

def test_session_strategy_no_trade_opening():
    """Opening phase should not allow trades."""
    allowed, reason = SessionStrategySelector.can_enter_trade(
        session_phase="OPENING",
        direction="LONG",
        aggression_score=3.0,
        rr_ratio=2.0,
    )
    assert not allowed
    assert "NO_TRADE" in reason or "No trade" in reason


def test_session_strategy_trend_following_primary():
    """Primary phase allows trend following."""
    allowed, reason = SessionStrategySelector.can_enter_trade(
        session_phase="PRIMARY",
        direction="LONG",
        aggression_score=3.0,
        rr_ratio=2.0,
    )
    assert allowed


def test_session_strategy_mean_reversion_midday():
    """Midday should be mean reversion only."""
    config = SessionStrategySelector.get_config("MIDDAY")
    assert config.mode == StrategyMode.MEAN_REVERSION
    assert config.max_position_size_pct == 0.25  # Reduced size


def test_session_strategy_exit_only_close():
    """Close phase should only exit."""
    allowed, reason = SessionStrategySelector.can_enter_trade(
        session_phase="CLOSE",
        direction="LONG",
        aggression_score=3.0,
        rr_ratio=2.0,
    )
    assert not allowed
    assert "EXIT_ONLY" in reason or "Exit only" in reason


def test_session_strategy_low_aggression_rejected():
    """Low aggression should be rejected even in valid phase."""
    allowed, reason = SessionStrategySelector.can_enter_trade(
        session_phase="PRIMARY",
        direction="LONG",
        aggression_score=1.0,  # Below 2.0 minimum
        rr_ratio=2.0,
    )
    assert not allowed
    assert "Aggression" in reason


def test_session_strategy_low_rr_rejected():
    """Low R:R should be rejected."""
    allowed, reason = SessionStrategySelector.can_enter_trade(
        session_phase="PRIMARY",
        direction="LONG",
        aggression_score=3.0,
        rr_ratio=1.0,  # Below 1.5 minimum
    )
    assert not allowed
    assert "R:R" in reason or "ratio" in reason.lower()


# ── First Breakout Filter ──────────────────────────────────────────

def test_first_breakout_first_attempt():
    """First breakout should be detected but not confirmed."""
    fbf = FirstBreakoutFilter()

    # First attempt above VAH
    status = fbf.update(price=105.0, vah=103.0, val=97.0, volume=100, avg_volume=100)
    assert status.state == BreakoutState.FIRST_ATTEMPT
    assert status.direction == "UP"


def test_first_breakout_confirmation():
    """After 2 confirmation bars, breakout should be confirmed."""
    fbf = FirstBreakoutFilter(confirmation_bars=2, volume_multiplier=1.0)

    # First attempt
    fbf.update(price=105.0, vah=103.0, val=97.0, volume=100, avg_volume=100)

    # Second confirmed bar
    status = fbf.update(price=106.0, vah=103.0, val=97.0, volume=100, avg_volume=100)
    assert status.state == BreakoutState.CONFIRMED_BREAKOUT


def test_first_breakout_failure():
    """First breakout that snaps back should be marked failed."""
    fbf = FirstBreakoutFilter()

    # First attempt above VAH
    fbf.update(price=105.0, vah=103.0, val=97.0, volume=100, avg_volume=100)

    # Snap back inside
    status = fbf.update(price=101.0, vah=103.0, val=97.0, volume=80, avg_volume=100)
    assert status.state == BreakoutState.FIRST_FAILED
    assert status.failed_at_level == 103.0  # VAH


def test_first_breakout_retest():
    """After confirmed breakout, pullback inside = re-test mode."""
    fbf = FirstBreakoutFilter(confirmation_bars=2, volume_multiplier=1.0)

    # Confirm breakout
    fbf.update(price=105.0, vah=103.0, val=97.0, volume=100, avg_volume=100)
    fbf.update(price=106.0, vah=103.0, val=97.0, volume=100, avg_volume=100)

    # Pull back inside
    status = fbf.update(price=101.0, vah=103.0, val=97.0, volume=80, avg_volume=100)
    assert status.state == BreakoutState.RE_TESTING


# ── Cross-Index Correlation ────────────────────────────────────────

def test_cross_index_basic_correlation():
    """Correlation should be calculated between indices."""
    corr = CrossIndexCorrelation(window_size=20)

    base_time = 1700000000.0
    bn_price = 48000.0
    nifty_price = 23400.0

    # Feed correlated prices
    for i in range(30):
        bn_price += 10 if i % 2 == 0 else -5
        nifty_price += 5 if i % 2 == 0 else -3
        corr.update("BANKNIFTY", bn_price, base_time + i)
        corr.update("NIFTY", nifty_price, base_time + i + 5)

    correlation = corr.get_correlation("BANKNIFTY", "NIFTY")
    # Positive correlation since both move in same direction
    assert correlation > 0.5


def test_cross_index_signal():
    """Signal should be returned when leader moves."""
    corr = CrossIndexCorrelation(window_size=20)

    base_time = 1700000000.0
    bn_price = 48000.0
    nifty_price = 23400.0

    # Feed prices with BANKNIFTY leading up
    for i in range(20):
        bn_price += 20  # Strong up move
        nifty_price += 3  # Slow follow
        corr.update("BANKNIFTY", bn_price, base_time + i)
        corr.update("NIFTY", nifty_price, base_time + i + 5)

    signal = corr.get_signal("BANKNIFTY", "NIFTY")
    assert signal is not None
    assert signal.leader == "BANKNIFTY"
    assert signal.follower == "NIFTY"
    assert signal.leader_direction == "UP"


# ── Gamma Acceleration ─────────────────────────────────────────────

def test_gamma_low_risk():
    """More than 3 days to expiry = LOW risk."""
    detector = GammaAccelerationDetector()
    expiry = date.today().replace(day=date.today().day + 7)  # 7 days out

    alert = detector.get_alert(expiry)
    assert alert.risk_level == GammaRiskLevel.LOW
    assert not alert.is_gamma_trap


def test_gamma_high_risk():
    """Expiry day before 14:30 = HIGH risk."""
    detector = GammaAccelerationDetector()
    expiry = date.today()  # Today is expiry

    from datetime import timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST).replace(hour=11, minute=0, second=0)

    alert = detector.get_alert(expiry, now)
    assert alert.risk_level == GammaRiskLevel.HIGH
    assert not alert.is_gamma_trap


def test_gamma_trap():
    """After 14:30 on expiry = EXTREME risk (gamma trap)."""
    detector = GammaAccelerationDetector()
    expiry = date.today()

    from datetime import timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST).replace(hour=15, minute=0, second=0)

    alert = detector.get_alert(expiry, now)
    assert alert.risk_level == GammaRiskLevel.EXTREME
    assert alert.is_gamma_trap
    assert alert.recommended_size_pct == 0.0


def test_gamma_next_expiry():
    """Should find next Thursday expiry."""
    detector = GammaAccelerationDetector()
    expiry = detector.get_next_expiry()

    assert expiry.weekday() == 3  # Thursday
    assert expiry >= date.today()


# ── Gate Pipeline: Theta Viability ─────────────────────────────────

def test_theta_gate_passes_when_low():
    """Theta gate should pass when theta cost is low."""
    ctx = GateContext(
        session_phase="PRIMARY",
        market_state="BALANCED",
        data_candles=50,
        is_risk_halted=False,
        price=100.0,
        entry_zone=100.0,
        aggression_score=3.0,
        opposing_level=100.4,
        r_r_ratio=2.0,
        tick_age_seconds=5,
        tick_size=0.05,
        theta_cost_pct=10.0,  # 10% < 20% threshold
    )

    passed, reason, detail = run_gate_pipeline(ctx)
    assert passed


def test_theta_gate_rejects_when_high():
    """Theta gate should reject when theta cost is too high."""
    ctx = GateContext(
        session_phase="PRIMARY",
        market_state="BALANCED",
        data_candles=50,
        is_risk_halted=False,
        price=100.0,
        entry_zone=100.0,
        aggression_score=3.0,
        opposing_level=100.4,
        r_r_ratio=2.0,
        tick_age_seconds=5,
        tick_size=0.05,
        theta_cost_pct=30.0,  # 30% > 20% threshold
    )

    passed, reason, detail = run_gate_pipeline(ctx)
    assert not passed
    assert "Theta" in reason
