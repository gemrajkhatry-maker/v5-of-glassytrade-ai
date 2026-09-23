"""Value Migration Tracker — session VA development over 15-minute windows.

Samples (POC, VAH, VAL) once per 15-minute window of the session clock and
reports the drift of the latest completed window vs the previous one.  This
makes the session value area's ongoing development an explicit feature: after a
regime collapse or a hard trend move the whole-session VA legitimately spans
both regimes, and "value migration direction" (VAH/VAL/POC drift) is what shows
whether the auction is expanding, contracting, or shifting as one body.
"""

from __future__ import annotations


from quant.contracts.value_objects import ValueMigration


def classify_value_migration(
    vah_drift: float, val_drift: float, eps: float
) -> str:
    """Classify VA drift between two windows.

    - EXPANDING:   VAH up + VAL down (range widening — initiative to new ground)
    - CONTRACTING: VAH down + VAL up (range narrowing — acceptance building)
    - MIGRATING_UP:   VAH + VAL both up (whole value body shifting higher)
    - MIGRATING_DOWN: VAH + VAL both down (whole value body shifting lower)
    - FLAT:        no meaningful movement vs ``eps``
    """
    if vah_drift > eps and val_drift < -eps:
        return "EXPANDING"
    if vah_drift < -eps and val_drift > eps:
        return "CONTRACTING"
    if vah_drift > eps and val_drift > eps:
        return "MIGRATING_UP"
    if vah_drift < -eps and val_drift < -eps:
        return "MIGRATING_DOWN"
    return "FLAT"


def _to_minutes(t: str) -> int | None:
    """Parse ``YYYY-MM-DDTHH:MM:SSZ`` into minutes-of-day, else None."""
    try:
        return int(t[11:13]) * 60 + int(t[14:16])
    except (TypeError, IndexError, ValueError):
        return None


def _fmt_window(session_open_minute: int, window_index: int) -> str:
    total = session_open_minute + window_index * 15
    return f"{total // 60:02d}:{total % 60:02d}"


class ValueMigrationTracker:
    """Incremental sampler of the session VA on the 15-minute session clock."""

    WINDOW_MINUTES = 15

    def __init__(self) -> None:
        self._samples: dict[int, tuple[float, float, float]] = {}
        self._current_idx: int | None = None
        self._current_values: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._session_open_minute: int | None = None
        self._session_date: str = ""

    def reset(self) -> None:
        self._samples.clear()
        self._current_idx = None
        self._current_values = (0.0, 0.0, 0.0)
        self._session_open_minute = None
        self._session_date = ""

    def update(
        self,
        current,
        poc: float,
        vah: float,
        val: float,
        session_open: str | None = None,
    ) -> ValueMigration:
        """Feed the latest bar's VA values; finalize completed windows.

        The last values seen inside a window are kept (sub-window updates
        overwrite), and when the session clock crosses into a new 15-minute
        window the previous window is finalized into the sample map.  Returns
        the current migration state (drift of the two latest windows).
        """
        m = _to_minutes(getattr(current, "time", ""))
        if m is None:
            return self.state()

        if session_open:
            sm = _to_minutes(session_open)
            if sm is not None:
                self._session_open_minute = sm
        if self._session_open_minute is None:
            self._session_open_minute = m

        # New session day → clear state (fresh 15-min clock).
        date = str(current.time)[:10]
        if self._session_date and date != self._session_date:
            self.reset()
            self._session_open_minute = _to_minutes(session_open) or m
        self._session_date = date

        idx = max((m - self._session_open_minute) // self.WINDOW_MINUTES, 0)
        if self._current_idx is None:
            self._current_idx = idx
        elif idx != self._current_idx:
            # Finalize the completed window with its last observed values.
            if self._current_idx not in self._samples:
                self._samples[self._current_idx] = self._current_values
            self._current_idx = idx
        self._current_values = (float(poc), float(vah), float(val))
        return self.state()

    def state(self) -> ValueMigration:
        """Drift of the latest window vs the previous one (latest − previous).

        When two windows have fully closed the two latest samples are compared;
        when only the first window has closed the live values of the developing
        window are compared against it, so the migration indicator goes live as
        soon as the second 15-minute window starts.
        """
        if not self._samples or self._current_idx is None:
            return ValueMigration()
        idxs = sorted(self._samples)
        if len(self._samples) >= 2:
            prev_idx, cur_idx = idxs[-2], idxs[-1]
            prev = self._samples[prev_idx]
            cur = self._samples[cur_idx]
        elif self._current_idx != idxs[-1]:
            prev_idx = idxs[-1]
            prev = self._samples[prev_idx]
            cur = self._current_values
            cur_idx = self._current_idx
        else:
            return ValueMigration()
        poc_drift = cur[0] - prev[0]
        vah_drift = cur[1] - prev[1]
        val_drift = cur[2] - prev[2]
        eps = max(abs(prev[0]), 1.0) * 0.0002
        direction = classify_value_migration(vah_drift, val_drift, eps)
        label = ""
        if self._session_open_minute is not None:
            label = (
                f"{_fmt_window(self._session_open_minute, prev_idx)}→"
                f"{_fmt_window(self._session_open_minute, cur_idx)}"
            )
        return ValueMigration(
            direction=direction,
            poc_drift=poc_drift,
            vah_drift=vah_drift,
            val_drift=val_drift,
            window_label=label,
            has_migration=True,
        )
