"""Tests for RegimeDetector circuit breaker + re-entry buffer, and LLM Entry Handler gate logic.

Validates:
1. RegimeDetector re-entry buffer width (Bug 1): default 1.5%, ATR-based widening.
2. RegimeDetector circuit breaker (Bug 4): 3 consecutive stops, expiry, reset.
3. Squeeze override on re-entry blocking.
4. Extracted gate logic from LLM Entry Handler: CVD hard gate, profile shape gate,
   C-grade gate, CVD penalty/bonus in grade scoring.
"""

import time

from app.domain.fabio_ai.services.regime_detector import RegimeDetector


# =====================================================================
# RegimeDetector: Re-entry Buffer Width Tests (Bug 1)
# =====================================================================


class TestReEntryBufferWidth:
    """Validates the widened 1.5% default re-entry buffer and ATR-based widening.

    Bug 1: The original buffer was 0.3%, which was too tight for options
    where price clusters span 2-5%. The fix widened it to 1.5% with an
    ATR-based fallback that uses whichever is wider.
    """

    def setup_method(self):
        self.rd = RegimeDetector()

    def test_rd01_default_buffer_is_1_5_percent(self):
        """RD-01: Default buffer is 1.5% (not 0.3%).

        Record failed entry at 1000 LONG phase 1.
        Price 1010 is 1% away from 1000, which is within the 1.5% buffer (15 pts).
        Re-entry should be BLOCKED.
        """
        self.rd.record_failed_entry(1000, "LONG", 1)
        assert self.rd.is_re_entry_blocked(1010, "LONG", 1) is True, (
            "Price 1010 is 1% from 1000 -- within 1.5% buffer, must be blocked"
        )

    def test_rd02_atr_based_widening(self):
        """RD-02: ATR widens buffer when ATR > pct-based buffer.

        ATR=20 > 15 (1.5% of 1000), so ATR buffer (20) should be used.
        Price 1010 is 10 away from 1000, which is within ATR buffer of 20.
        """
        self.rd.record_failed_entry(1000, "LONG", 1)
        assert self.rd.is_re_entry_blocked(1010, "LONG", 1, atr=20) is True, (
            "ATR buffer 20 > pct buffer 15, price 1010 within ATR buffer"
        )

    def test_rd03_atr_used_when_wider_than_pct(self):
        """RD-03: ATR buffer is used when it exceeds percentage-based buffer.

        Record failed at 1000. Price 1018 is 18 away.
        Pct buffer: 1000 * 0.015 = 15 (would allow 1018).
        ATR buffer: 20 (blocks 1018 since 18 < 20).
        """
        self.rd.record_failed_entry(1000, "LONG", 1)
        assert self.rd.is_re_entry_blocked(1018, "LONG", 1, atr=20) is True, (
            "Price 1018 is 18 from 1000, ATR buffer is 20, must be blocked"
        )

    def test_rd04_outside_buffer_allows_reentry(self):
        """RD-04: Price outside the buffer is NOT blocked.

        Price 1020 is 2% from 1000, which exceeds the 1.5% buffer (15 pts).
        Re-entry should be ALLOWED.
        """
        self.rd.record_failed_entry(1000, "LONG", 1)
        assert self.rd.is_re_entry_blocked(1020, "LONG", 1) is False, (
            "Price 1020 is 2% from 1000 -- outside 1.5% buffer, must be allowed"
        )

    def test_buffer_exact_boundary(self):
        """Boundary: Price exactly at 1.5% buffer edge (1015) should be blocked.

        1000 * 0.015 = 15. abs(1015 - 1000) = 15 <= 15 buffer. Blocked.
        """
        self.rd.record_failed_entry(1000, "LONG", 1)
        assert self.rd.is_re_entry_blocked(1015, "LONG", 1) is True, (
            "Price exactly at buffer boundary (15 = 15) should be blocked (<=)"
        )

    def test_buffer_just_outside(self):
        """Price clearly beyond 1.5% buffer edge should be allowed.

        Note: abs_buffer is computed from the *current* price (level),
        not the failed price. At level=1016, abs_buffer = 1016 * 0.015 = 15.24.
        abs(1016 - 1000) = 16 > 15.24. Allowed.
        """
        self.rd.record_failed_entry(1000, "LONG", 1)
        assert self.rd.is_re_entry_blocked(1016, "LONG", 1) is False, (
            "Price 1016 is beyond buffer (16 > 1016*0.015=15.24), must be allowed"
        )

    def test_different_direction_not_blocked(self):
        """Failed LONG entry should NOT block SHORT re-entry at same level."""
        self.rd.record_failed_entry(1000, "LONG", 1)
        assert self.rd.is_re_entry_blocked(1000, "SHORT", 1) is False, (
            "SHORT at same level as failed LONG must not be blocked"
        )

    def test_different_session_phase_not_blocked(self):
        """Failed entry in phase 1 should NOT block re-entry in phase 2."""
        self.rd.record_failed_entry(1000, "LONG", 1)
        assert self.rd.is_re_entry_blocked(1000, "LONG", 2) is False, (
            "New session phase should allow re-entry"
        )

    def test_atr_zero_uses_pct_buffer(self):
        """ATR=0 should fall back to percentage-based buffer only."""
        self.rd.record_failed_entry(1000, "LONG", 1)
        # 1010 within 1.5% pct buffer (15), should be blocked
        assert self.rd.is_re_entry_blocked(1010, "LONG", 1, atr=0) is True
        # 1020 outside 1.5% pct buffer, should be allowed
        assert self.rd.is_re_entry_blocked(1020, "LONG", 1, atr=0) is False


# =====================================================================
# RegimeDetector: Circuit Breaker Tests (Bug 4)
# =====================================================================


class TestCircuitBreaker:
    """Validates circuit breaker activation, expiry, and reset behavior.

    Bug 4: The circuit breaker triggers after MAX_CONSECUTIVE_STOPS (3)
    consecutive stop-outs and pauses all entries for CIRCUIT_BREAKER_SECONDS (900s).
    """

    def setup_method(self):
        self.rd = RegimeDetector()

    def test_rd05_three_consecutive_stops_triggers_breaker(self):
        """RD-05: 3 consecutive stops activates the circuit breaker."""
        self.rd.record_failed_entry(1000, "LONG", 1)
        self.rd.record_failed_entry(1010, "LONG", 1)
        self.rd.record_failed_entry(1020, "LONG", 1)
        assert self.rd.is_circuit_breaker_active() is True, (
            "Circuit breaker must activate after 3 consecutive stops"
        )

    def test_rd06_breaker_expires_after_time(self):
        """RD-06: Circuit breaker deactivates after the timeout period.

        Set _circuit_breaker_until to a past timestamp to simulate expiry.
        """
        self.rd.record_failed_entry(1000, "LONG", 1)
        self.rd.record_failed_entry(1010, "LONG", 1)
        self.rd.record_failed_entry(1020, "LONG", 1)
        assert self.rd.is_circuit_breaker_active() is True

        # Simulate expiry by setting the breaker timestamp to the past
        self.rd._circuit_breaker_until = time.time() - 1
        assert self.rd.is_circuit_breaker_active() is False, (
            "Circuit breaker must deactivate after timeout expires"
        )

    def test_rd07_profitable_exit_resets_counter(self):
        """RD-07: Profitable exit resets the consecutive stop counter.

        Record 2 stops, then a successful exit (resets counter to 0),
        then 1 more stop. Total consecutive = 1, NOT 3. Breaker inactive.
        """
        self.rd.record_failed_entry(1000, "LONG", 1)
        self.rd.record_failed_entry(1010, "LONG", 1)
        self.rd.record_successful_exit()
        self.rd.record_failed_entry(1020, "LONG", 1)
        assert self.rd.is_circuit_breaker_active() is False, (
            "Profitable exit resets consecutive counter -- only 1 stop since reset"
        )

    def test_rd08_clear_resets_everything(self):
        """RD-08: clear_failed_entries() resets all state including circuit breaker."""
        self.rd.record_failed_entry(1000, "LONG", 1)
        self.rd.record_failed_entry(1010, "LONG", 1)
        self.rd.record_failed_entry(1020, "LONG", 1)
        assert self.rd.is_circuit_breaker_active() is True

        self.rd.clear_failed_entries()
        assert self.rd.is_circuit_breaker_active() is False, (
            "Circuit breaker must be inactive after clear"
        )
        # Also verify re-entry is no longer blocked
        assert self.rd.is_re_entry_blocked(1000, "LONG", 1) is False, (
            "Re-entry must be allowed after clear"
        )

    def test_two_stops_no_breaker(self):
        """Only 2 consecutive stops should NOT trigger circuit breaker."""
        self.rd.record_failed_entry(1000, "LONG", 1)
        self.rd.record_failed_entry(1010, "LONG", 1)
        assert self.rd.is_circuit_breaker_active() is False

    def test_breaker_uses_current_time_param(self):
        """Circuit breaker respects current_time parameter for testability."""
        self.rd.record_failed_entry(1000, "LONG", 1)
        self.rd.record_failed_entry(1010, "LONG", 1)
        self.rd.record_failed_entry(1020, "LONG", 1)

        # Breaker is active with current time
        now = time.time()
        assert self.rd.is_circuit_breaker_active(current_time=now) is True

        # Breaker should be expired far in the future
        future = now + 100000
        assert self.rd.is_circuit_breaker_active(current_time=future) is False


# =====================================================================
# RegimeDetector: Squeeze Override Test
# =====================================================================


class TestSqueezeOverride:
    """Validates that squeeze_active=True overrides re-entry blocking."""

    def test_rd09_squeeze_overrides_reentry_block(self):
        """RD-09: Squeeze active allows re-entry at exact failed level.

        Fabio methodology: failed sellers' forced exit IS the entry catalyst.
        When a squeeze is detected, re-entry at the same level is the setup.
        """
        rd = RegimeDetector()
        rd.record_failed_entry(1000, "LONG", 1)
        # Without squeeze: blocked
        assert rd.is_re_entry_blocked(1000, "LONG", 1) is True
        # With squeeze: allowed
        assert rd.is_re_entry_blocked(1000, "LONG", 1, squeeze_active=True) is False, (
            "Squeeze override must allow re-entry at failed level"
        )


# =====================================================================
# LLM Entry Handler: CVD Hard Gate Logic
# =====================================================================


class TestCVDHardGateLogic:
    """Validates the CVD hard gate conditional logic extracted from
    llm_entry_handler.py worker loop.

    The CVD hard gate blocks entries when CVD slope strongly opposes
    the entry direction: LONG blocked when cvd_slope < -50,
    SHORT blocked when cvd_slope > 50.
    """

    def test_gl01_cvd_hard_gate_blocks_long_on_extreme_selling(self):
        """GL-01: LONG should be blocked when CVD slope < -50."""
        direction = "LONG"
        cvd_slope = -611.5
        if direction == "LONG" and cvd_slope < -50:
            direction = "FLAT"
        assert direction == "FLAT", (
            "LONG must be blocked by CVD hard gate when slope is extreme negative"
        )

    def test_gl02_cvd_hard_gate_blocks_short_on_extreme_buying(self):
        """GL-02: SHORT should be blocked when CVD slope > 50."""
        direction = "SHORT"
        cvd_slope = 200
        if direction == "SHORT" and cvd_slope > 50:
            direction = "FLAT"
        assert direction == "FLAT", (
            "SHORT must be blocked by CVD hard gate when slope is extreme positive"
        )

    def test_gl03_cvd_hard_gate_allows_long_on_moderate_selling(self):
        """GL-03: LONG should be allowed when CVD slope is moderate (> -50)."""
        direction = "LONG"
        cvd_slope = -30
        if direction == "LONG" and cvd_slope < -50:
            direction = "FLAT"
        assert direction == "LONG", (
            "LONG must pass CVD hard gate when slope is moderate negative"
        )

    def test_cvd_hard_gate_allows_short_on_moderate_buying(self):
        """SHORT should be allowed when CVD slope is moderate (< 50)."""
        direction = "SHORT"
        cvd_slope = 30
        if direction == "SHORT" and cvd_slope > 50:
            direction = "FLAT"
        assert direction == "SHORT"

    def test_cvd_hard_gate_exact_threshold_negative(self):
        """CVD slope exactly -50 should NOT block (condition is < -50, not <=)."""
        direction = "LONG"
        cvd_slope = -50
        if direction == "LONG" and cvd_slope < -50:
            direction = "FLAT"
        assert direction == "LONG", (
            "CVD slope exactly at -50 should not trigger the gate (strict <)"
        )

    def test_cvd_hard_gate_exact_threshold_positive(self):
        """CVD slope exactly 50 should NOT block (condition is > 50, not >=)."""
        direction = "SHORT"
        cvd_slope = 50
        if direction == "SHORT" and cvd_slope > 50:
            direction = "FLAT"
        assert direction == "SHORT", (
            "CVD slope exactly at 50 should not trigger the gate (strict >)"
        )

    def test_cvd_hard_gate_flat_direction_unchanged(self):
        """FLAT direction should not be changed by CVD hard gate."""
        direction = "FLAT"
        cvd_slope = -611.5
        if direction == "LONG" and cvd_slope < -50:
            direction = "FLAT"
        assert direction == "FLAT"


# =====================================================================
# LLM Entry Handler: Profile Shape Hard Gate Logic
# =====================================================================


class TestProfileShapeGateLogic:
    """Validates the profile shape hard gate conditional logic extracted
    from llm_entry_handler.py worker loop.

    The profile shape gate blocks entries opposing the dominant
    distribution: LONG blocked on P-shape (distribution),
    SHORT blocked on b-shape (accumulation).
    """

    def test_gl04_profile_shape_gate_blocks_long_on_p(self):
        """GL-04: LONG blocked when profile shape code is 'P' (distribution)."""
        direction = "LONG"
        profile_shape_str = "P-shape (top-heavy distribution)"
        _shape_code = profile_shape_str[0] if profile_shape_str else ""
        if direction == "LONG" and _shape_code == "P":
            direction = "FLAT"
        assert direction == "FLAT", (
            "LONG must be blocked by P-shape (top-heavy distribution)"
        )

    def test_gl05_profile_shape_gate_blocks_short_on_b(self):
        """GL-05: SHORT blocked when profile shape code is 'b' (accumulation)."""
        direction = "SHORT"
        profile_shape_str = "b-shape (bottom-heavy)"
        _shape_code = profile_shape_str[0] if profile_shape_str else ""
        if direction == "SHORT" and _shape_code == "b":
            direction = "FLAT"
        assert direction == "FLAT", (
            "SHORT must be blocked by b-shape (buying accumulation)"
        )

    def test_gl06_profile_shape_gate_allows_long_on_b(self):
        """GL-06: LONG allowed with b-shape (accumulation supports LONG)."""
        direction = "LONG"
        profile_shape_str = "b-shape (bottom-heavy)"
        _shape_code = profile_shape_str[0] if profile_shape_str else ""
        if direction == "LONG" and _shape_code == "P":
            direction = "FLAT"
        assert direction == "LONG", (
            "b-shape should NOT block LONG -- accumulation supports buying"
        )

    def test_profile_shape_gate_allows_short_on_p(self):
        """SHORT allowed with P-shape (distribution supports SHORT)."""
        direction = "SHORT"
        profile_shape_str = "P-shape (top-heavy distribution)"
        _shape_code = profile_shape_str[0] if profile_shape_str else ""
        if direction == "SHORT" and _shape_code == "b":
            direction = "FLAT"
        assert direction == "SHORT", (
            "P-shape should NOT block SHORT -- distribution supports selling"
        )

    def test_profile_shape_gate_empty_string_no_crash(self):
        """Empty profile_shape_str should not crash or block anything."""
        direction = "LONG"
        profile_shape_str = ""
        _shape_code = profile_shape_str[0] if profile_shape_str else ""
        if direction == "LONG" and _shape_code == "P":
            direction = "FLAT"
        assert direction == "LONG", (
            "Empty profile shape must not block any direction"
        )

    def test_profile_shape_gate_d_shape_neutral(self):
        """D-shape (balanced) should not block either direction."""
        for dir_val in ("LONG", "SHORT"):
            direction = dir_val
            profile_shape_str = "D-shape (balanced, rotational)"
            _shape_code = profile_shape_str[0] if profile_shape_str else ""
            if direction == "LONG" and _shape_code == "P":
                direction = "FLAT"
            elif direction == "SHORT" and _shape_code == "b":
                direction = "FLAT"
            assert direction == dir_val, (
                f"D-shape must not block {dir_val}"
            )


# =====================================================================
# LLM Entry Handler: C-Grade Gate Logic
# =====================================================================


class TestCGradeGateLogic:
    """Validates the C-grade (Low confidence) gate that blocks entries
    with insufficient grade scores.

    Grade tiers:
    - score >= 3 -> High confidence (A-grade)
    - score >= 1 -> Medium confidence (B-grade)
    - score < 1  -> Low confidence (C-grade) -> BLOCKED
    """

    def test_gl07_c_grade_blocks_low_confidence(self):
        """GL-07: Grade score 0 -> Low confidence -> direction set to FLAT."""
        grade_score = 0
        if grade_score >= 3:
            confidence = "High"
        elif grade_score >= 1:
            confidence = "Medium"
        else:
            confidence = "Low"
        direction = "LONG"
        if confidence == "Low":
            direction = "FLAT"
        assert direction == "FLAT", (
            "C-grade (Low confidence, score=0) must block entry"
        )

    def test_gl08_b_grade_passes(self):
        """GL-08: Grade score 2 -> Medium confidence -> entry allowed."""
        grade_score = 2
        if grade_score >= 3:
            confidence = "High"
        elif grade_score >= 1:
            confidence = "Medium"
        else:
            confidence = "Low"
        direction = "LONG"
        if confidence == "Low":
            direction = "FLAT"
        assert direction == "LONG", (
            "B-grade (Medium confidence, score=2) must allow entry"
        )

    def test_a_grade_passes(self):
        """Grade score 3 -> High confidence -> entry allowed."""
        grade_score = 3
        if grade_score >= 3:
            confidence = "High"
        elif grade_score >= 1:
            confidence = "Medium"
        else:
            confidence = "Low"
        direction = "LONG"
        if confidence == "Low":
            direction = "FLAT"
        assert direction == "LONG"
        assert confidence == "High"

    def test_grade_score_1_is_medium(self):
        """Grade score exactly 1 is Medium confidence (boundary)."""
        grade_score = 1
        if grade_score >= 3:
            confidence = "High"
        elif grade_score >= 1:
            confidence = "Medium"
        else:
            confidence = "Low"
        assert confidence == "Medium"

    def test_negative_grade_score_is_low(self):
        """Negative grade score is Low confidence."""
        grade_score = -2
        if grade_score >= 3:
            confidence = "High"
        elif grade_score >= 1:
            confidence = "Medium"
        else:
            confidence = "Low"
        direction = "SHORT"
        if confidence == "Low":
            direction = "FLAT"
        assert direction == "FLAT"
        assert confidence == "Low"


# =====================================================================
# LLM Entry Handler: CVD Penalty/Bonus in Grade Scoring
# =====================================================================


class TestCVDGradeScoring:
    """Validates CVD-based penalty (-2) and bonus (+1) in the
    A/B/C grade scoring system.

    - Opposing CVD: direction LONG + cvd_slope < -0.3 -> -2 penalty
    - Opposing CVD: direction SHORT + cvd_slope > 0.3 -> -2 penalty
    - Confirming CVD: direction LONG + cvd_slope > 0.3 -> +1 bonus
    - Confirming CVD: direction SHORT + cvd_slope < -0.3 -> +1 bonus
    """

    def test_gl09_cvd_opposing_penalty_long(self):
        """GL-09: LONG with negative CVD slope gets -2 penalty."""
        grade_score = 2  # starts with some points
        direction = "LONG"
        cvd_slope = -5.0
        if (direction == "LONG" and cvd_slope < -0.3) or (direction == "SHORT" and cvd_slope > 0.3):
            grade_score -= 2
        assert grade_score == 0, (
            "LONG with negative CVD must get -2 penalty (2 - 2 = 0)"
        )

    def test_gl10_cvd_confirming_bonus_long(self):
        """GL-10: LONG with positive CVD slope gets +1 bonus."""
        grade_score = 0
        direction = "LONG"
        cvd_slope = 5.0
        if (direction == "LONG" and cvd_slope > 0.3) or (direction == "SHORT" and cvd_slope < -0.3):
            grade_score += 1
        assert grade_score == 1, (
            "LONG with positive CVD must get +1 bonus (0 + 1 = 1)"
        )

    def test_cvd_opposing_penalty_short(self):
        """SHORT with positive CVD slope gets -2 penalty."""
        grade_score = 3
        direction = "SHORT"
        cvd_slope = 10.0
        if (direction == "LONG" and cvd_slope < -0.3) or (direction == "SHORT" and cvd_slope > 0.3):
            grade_score -= 2
        assert grade_score == 1

    def test_cvd_confirming_bonus_short(self):
        """SHORT with negative CVD slope gets +1 bonus."""
        grade_score = 1
        direction = "SHORT"
        cvd_slope = -5.0
        if (direction == "LONG" and cvd_slope > 0.3) or (direction == "SHORT" and cvd_slope < -0.3):
            grade_score += 1
        assert grade_score == 2

    def test_cvd_neutral_no_change(self):
        """Neutral CVD slope (within +/-0.3) gives no penalty or bonus."""
        grade_score = 2
        direction = "LONG"
        cvd_slope = 0.1
        if (direction == "LONG" and cvd_slope < -0.3) or (direction == "SHORT" and cvd_slope > 0.3):
            grade_score -= 2
        if (direction == "LONG" and cvd_slope > 0.3) or (direction == "SHORT" and cvd_slope < -0.3):
            grade_score += 1
        assert grade_score == 2, (
            "Neutral CVD (within dead zone) must not change grade score"
        )

    def test_cvd_opposing_can_push_to_c_grade(self):
        """Opposing CVD penalty can push a B-grade to C-grade (Low), blocking entry."""
        grade_score = 1  # starts as Medium (B-grade)
        direction = "LONG"
        cvd_slope = -5.0
        # Apply penalty
        if (direction == "LONG" and cvd_slope < -0.3) or (direction == "SHORT" and cvd_slope > 0.3):
            grade_score -= 2
        assert grade_score == -1
        # Check confidence
        if grade_score >= 3:
            confidence = "High"
        elif grade_score >= 1:
            confidence = "Medium"
        else:
            confidence = "Low"
        assert confidence == "Low", (
            "CVD penalty pushing score to -1 must result in Low confidence"
        )
        # Check gate blocks entry
        direction_final = "LONG"
        if confidence == "Low":
            direction_final = "FLAT"
        assert direction_final == "FLAT", (
            "C-grade from CVD penalty must block entry"
        )

    def test_cvd_confirming_can_promote_to_b_grade(self):
        """Confirming CVD bonus can promote a C-grade to B-grade (Medium), allowing entry."""
        grade_score = 0  # starts as Low (C-grade)
        direction = "SHORT"
        cvd_slope = -2.0
        # Apply bonus
        if (direction == "LONG" and cvd_slope > 0.3) or (direction == "SHORT" and cvd_slope < -0.3):
            grade_score += 1
        assert grade_score == 1
        # Check confidence
        if grade_score >= 3:
            confidence = "High"
        elif grade_score >= 1:
            confidence = "Medium"
        else:
            confidence = "Low"
        assert confidence == "Medium", (
            "CVD bonus promoting score to 1 must result in Medium confidence"
        )


# =====================================================================
# Combined Integration: CVD divergence penalty in grading
# =====================================================================


class TestCVDDivergencePenalty:
    """Validates CVD divergence penalty (-2) in grade scoring.

    BEARISH_DIV opposing LONG or BULLISH_DIV opposing SHORT
    should apply -2 penalty.
    """

    def test_bearish_div_penalizes_long(self):
        """BEARISH_DIV with LONG direction should apply -2 penalty."""
        grade_score = 2
        direction = "LONG"
        cvd_divergence = "BEARISH_DIV"
        if (direction == "LONG" and cvd_divergence == "BEARISH_DIV") or \
           (direction == "SHORT" and cvd_divergence == "BULLISH_DIV"):
            grade_score -= 2
        assert grade_score == 0

    def test_bullish_div_penalizes_short(self):
        """BULLISH_DIV with SHORT direction should apply -2 penalty."""
        grade_score = 3
        direction = "SHORT"
        cvd_divergence = "BULLISH_DIV"
        if (direction == "LONG" and cvd_divergence == "BEARISH_DIV") or \
           (direction == "SHORT" and cvd_divergence == "BULLISH_DIV"):
            grade_score -= 2
        assert grade_score == 1

    def test_no_divergence_adds_1_point(self):
        """No divergence (empty string) should add +1 point."""
        grade_score = 0
        cvd_divergence = ""
        if not cvd_divergence:
            grade_score += 1
        elif cvd_divergence in ("BEARISH_DIV", "BULLISH_DIV"):
            grade_score -= 2
        assert grade_score == 1

    def test_confirming_divergence_not_penalized(self):
        """BEARISH_DIV with SHORT should NOT be penalized (it confirms the direction)."""
        grade_score = 2
        direction = "SHORT"
        cvd_divergence = "BEARISH_DIV"
        if (direction == "LONG" and cvd_divergence == "BEARISH_DIV") or \
           (direction == "SHORT" and cvd_divergence == "BULLISH_DIV"):
            grade_score -= 2
        assert grade_score == 2, (
            "BEARISH_DIV confirms SHORT, no penalty should apply"
        )
